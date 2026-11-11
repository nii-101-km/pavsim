"""One isolated worker process per session, with a small command/event protocol.

The manager does not import block implementations. All diagrams, execution,
object references and output snapshots belong to the child process.
"""
from __future__ import annotations

import copy
import multiprocessing
import secrets
import threading
import time

from .cancellation import SessionCancelled


def _session_worker(channel, session_id):
    from shell.cancellation import SessionCancelled
    from shell.heap import SessionHeap
    from shell.session_runtime import _build_generic_graph, _execute_generic_dataflow, _model_is_generic, _shared_registry
    from shell.session_blocks import SessionBlocks
    from shell.signal_engine import SignalEngine

    heap = SessionHeap(session_id)
    cancel = threading.Event()
    failed = threading.Event()
    send_lock = threading.Lock()
    state_lock = threading.Lock()
    snapshots = {}
    model = None
    execution = None
    execution_failures = []
    session_blocks = SessionBlocks()
    block_instances = {}
    notified = False

    def request_block_stop():
        nonlocal notified
        if notified:
            return []
        notified = True
        return session_blocks.request_stop()

    def send(kind, **fields):
        with send_lock:
            channel.send({'event': kind, **fields})

    def publish(node_id, output):
        with state_lock:
            version = snapshots.get(node_id, (0, None))[0] + 1
            snapshots[node_id] = (version, output)
        send('output_changed', block_id=node_id, version=version)

    def publish_flows(blocks):
        send('flow_state', blocks=blocks)

    def execute(diagram, instances):
        try:
            result = _execute_generic_dataflow(diagram, heap, publish, cancel, instances, publish_flows, publish)
            if cancel.is_set():
                raise SessionCancelled('Сессия остановлена.')
            send('completed', result=result)
        except SessionCancelled:
            pass
        except BaseException as exc:
            execution_failures.append(str(exc))
            cancel.set()
            failed.set()
            send('error', message=str(exc), error_type=type(exc).__name__)

    try:
        send('ready', session_id=session_id)
        while not failed.is_set():
            if not channel.poll(.1):
                continue
            command = channel.recv()
            kind = command.get('command')
            if kind == 'prepare':
                if execution and execution.is_alive():
                    send('error', message='Нельзя менять схему во время расчёта.')
                    continue
                model = None
                with state_lock:
                    snapshots.clear()
                try:
                    candidate = copy.deepcopy(command['model'])
                    if not _model_is_generic(candidate):
                        raise ValueError('Схема содержит неподдерживаемые блоки.')
                    graph = _build_generic_graph(candidate)
                    SignalEngine(heap)._resolve_ports(graph)
                    graph.validate(allow_cycles=True)
                    block_instances = session_blocks.prepare(graph, _shared_registry)
                    model = candidate
                    send('prepared')
                except Exception as exc:
                    send('error', message=str(exc), error_type=type(exc).__name__)
            elif kind == 'start':
                if model is None:
                    send('error', message='Сначала подготовьте схему.')
                elif execution and execution.is_alive():
                    send('error', message='Расчёт уже выполняется.')
                else:
                    cancel.clear()
                    execution_failures.clear()
                    execution = threading.Thread(target=execute, args=(model, block_instances), daemon=True)
                    send('started')
                    execution.start()
            elif kind == 'get_output':
                block_id = str(command.get('block_id', ''))
                with state_lock:
                    snapshot = snapshots.get(block_id)
                    snapshot = copy.deepcopy(snapshot)
                if snapshot is None:
                    send('error', message=f'Вывод блока {block_id} недоступен.')
                else:
                    send('output', block_id=block_id, version=snapshot[0], value=snapshot[1])
            elif kind in ('stop', 'close'):
                cancel.set()
                errors = request_block_stop()
                if execution:
                    execution.join()
                errors.extend(execution_failures)
                errors.extend(session_blocks.close())
                heap.close()
                send('stopped', cleanup_errors=errors)
                if errors:
                    raise SystemExit(2)
                return
            else:
                send('error', message=f'Неизвестная команда: {kind!r}.')
    except (EOFError, BrokenPipeError, OSError):
        cancel.set()
        request_block_stop()
        if execution:
            execution.join()
    finally:
        request_block_stop()
        if execution and execution.is_alive():
            execution.join()
        session_blocks.close()
        heap.close()
        channel.close()


class SessionProcess:
    """Manage one worker; timeout on stop escalates to OS termination."""
    def __init__(self, session_id=None, *, worker=_session_worker):
        self.session_id = session_id or secrets.token_urlsafe(24)
        context = multiprocessing.get_context('spawn')
        self._channel, child = context.Pipe()
        self._process = context.Process(target=worker, args=(child, self.session_id), daemon=True)
        self._process.start()
        child.close()
        self._send_lock = threading.Lock()
        self._run_lock = threading.Lock()

    @property
    def pid(self):
        return self._process.pid

    def is_alive(self):
        return self._process.is_alive()

    def send(self, command, **fields):
        with self._send_lock:
            self._channel.send({'command': command, **fields})

    def receive(self, timeout=None):
        if not self._channel.poll(timeout):
            raise TimeoutError('Нет ответа процесса сессии.')
        return self._channel.recv()

    def run(self, model, on_output=None, on_flow=None):
        """Prepare and run a diagram, forwarding changed output snapshots."""
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError('В этой сессии уже выполняется расчёт.')
        try:
            self.send('prepare', model=model)
            event = self.receive()
            if event['event'] == 'error':
                raise ValueError(event['message'])
            if event['event'] != 'prepared':
                raise RuntimeError(f'Неожиданное событие: {event["event"]}.')
            self.send('start')
            event = self.receive()
            if event['event'] == 'error':
                raise RuntimeError(event['message'])
            if event['event'] != 'started':
                raise RuntimeError(f'Неожиданное событие: {event["event"]}.')
            pending = set()
            dirty = set()
            completed = None
            while completed is None or pending:
                event = self.receive()
                kind = event['event']
                if kind == 'output_changed':
                    block_id = event['block_id']
                    if block_id in pending:
                        dirty.add(block_id)
                    elif completed is None:
                        pending.add(block_id)
                        self.send('get_output', block_id=block_id)
                elif kind == 'output':
                    block_id = event['block_id']
                    pending.discard(block_id)
                    if on_output:
                        on_output(block_id, event['value'])
                    if block_id in dirty and completed is None:
                        dirty.discard(block_id)
                        pending.add(block_id)
                        self.send('get_output', block_id=block_id)
                elif kind == 'completed':
                    completed = event['result']
                elif kind == 'flow_state':
                    if on_flow:
                        on_flow(event['blocks'])
                elif kind == 'stopped':
                    raise SessionCancelled('Сессия остановлена.')
                elif kind == 'error':
                    raise RuntimeError(event['message'])
            return completed
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise SessionCancelled('Процесс сессии завершён.') from exc
        finally:
            self._run_lock.release()

    def stop(self, timeout=2):
        if not self.is_alive():
            self._process.join()
            return 'stopped' if self._process.exitcode == 0 else 'cleanup_failed'
        try:
            self.send('stop')
        except (BrokenPipeError, EOFError, OSError):
            pass
        self._process.join(timeout)
        if self.is_alive():
            self._process.terminate()
            self._process.join(timeout)
            if self.is_alive():
                self._process.kill()
                self._process.join()
            return 'terminated'
        return 'stopped' if self._process.exitcode == 0 else 'cleanup_failed'

    def close(self):
        try:
            return self.stop()
        finally:
            self._channel.close()


class SessionProcesses:
    """Track worker lifetimes and expire abandoned sessions."""
    def __init__(self, ttl_seconds=1800, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._sessions = {}
        self._lock = threading.RLock()

    def create(self):
        session = SessionProcess()
        try:
            if session.receive(10).get('event') != 'ready':
                raise RuntimeError('Процесс сессии не готов.')
        except BaseException:
            session.close()
            raise
        with self._lock:
            self._sessions[session.session_id] = (session, self.clock())
        return session

    def touch(self, session_id):
        from .heap import InvalidReference
        self.expire()
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None or not entry[0].is_alive():
                raise InvalidReference('Session is missing or has expired.')
            self._sessions[session_id] = (entry[0], self.clock())
            return entry[0]

    def close(self, session_id):
        with self._lock:
            entry = self._sessions.pop(session_id, None)
        return entry[0].close() if entry else None

    def expire(self):
        now = self.clock()
        with self._lock:
            expired = [sid for sid, (_, touched) in self._sessions.items() if now - touched >= self.ttl_seconds]
        for sid in expired:
            self.close(sid)
        return len(expired)

    def close_all(self):
        with self._lock:
            sessions = list(self._sessions)
        for session_id in sessions:
            self.close(session_id)
