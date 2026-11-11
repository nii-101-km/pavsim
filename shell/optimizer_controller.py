"""Adapt the existing bounded search to a request/score signal exchange."""
import queue
import threading
import math
import time

from .cancellation import SessionCancelled
from .structures import float_structure, read_float_structure


class _Cancelled(BaseException):
    pass


class OptimizerController:
    """One search instance, suspended while the graph computes each score."""
    def __init__(self, params, *, optimize, defaults):
        self.optimize = optimize
        self.params = dict(defaults)
        self.params.update(params)
        delay = self.params.get('trial_delay', 0)
        if isinstance(delay, bool):
            raise ValueError('Оптимизатор: задержка должна быть неотрицательным числом.')
        try:
            self.trial_delay = float(delay)
        except (TypeError, ValueError):
            raise ValueError('Оптимизатор: задержка должна быть неотрицательным числом.')
        if not math.isfinite(self.trial_delay) or self.trial_delay < 0:
            raise ValueError('Оптимизатор: задержка должна быть неотрицательным числом.')
        self.session_cancel = None
        self._events = queue.Queue()
        self._scores = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._started = False
        self._waiting = False
        self.flow_id = None
        self.entries = []
        self._candidate = None
        self._cancelled = threading.Event()

    def _thread_main(self):
        try:
            self._run()
        except Exception as exc:
            self._events.put(('error', exc))

    def _run(self):
        params = self.params
        keys = [f'p{i}' for i in range(1, 4)]
        model = {'blocks': [{'id': 'optimizer', 'params': params.copy()}]}
        bounds = [[params[f'min_{key}'], params[f'max_{key}']] if params[f'optimize_{key}']
                  else [params[key], params[key]] for key in keys]

        def evaluate(candidate):
            if self._cancelled.is_set():
                raise _Cancelled()
            current = candidate['blocks'][0]['params']
            self._events.put(('candidate', {key: float_structure(current[key]) for key in keys}))
            score = self._scores.get()
            if score is _Cancelled or self._cancelled.is_set():
                raise _Cancelled()
            metrics = {'settled': None, 'iae': score, 'ise': score}
            return metrics, [(0.0, score)], score

        if not isinstance(params['enabled'], bool):
            raise ValueError('Оптимизатор: параметр enabled должен быть логическим.')
        if not params['enabled']:
            try:
                _, _, score = evaluate(model)
                values = {key: params[key] for key in keys}
                self._events.put(('done', {'values': values, 'score': score, 'evaluations': 1,
                                           'converged': None, 'enabled': False}))
            except _Cancelled:
                pass
            return

        settings = {'bounds': bounds, 'algorithm': params['algorithm'],
                    'algorithm_options': params['algorithm_options'],
                    'max_evaluations': params['max_evaluations'],
                    'objective': 'ise', 't_end': 1, 'h': 1}
        binding = {'parameters': [('optimizer', key) for key in keys],
                   'evaluate': evaluate, 'cache': False}
        try:
            report = self.optimize(model, lambda candidate: candidate, settings, binding)
            report['values'] = {key: report['coefficients'][f'k{i}'] for i, key in enumerate(keys, 1)}
            self._events.put(('done', report))
        except _Cancelled:
            pass
        except Exception as exc:
            self._events.put(('error', exc))

    def start(self, *, flow_id=None):
        if self._started:
            raise RuntimeError('Optimizer already started.')
        self.flow_id = flow_id
        self._started = True
        self._thread.start()
        return self._next()

    def _delay_candidate(self, kind, payload):
        if kind == 'candidate' and self.trial_delay:
            deadline = time.monotonic() + self.trial_delay
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if self._cancelled.wait(min(remaining, .05)) or (self.session_cancel and self.session_cancel.is_set()):
                    raise SessionCancelled('Оптимизатор остановлен.')
        return kind, payload

    def _next(self):
        kind, payload = self._events.get()
        if self._cancelled.is_set() or kind == 'cancelled':
            raise SessionCancelled('Оптимизатор остановлен.')
        self._waiting = kind == 'candidate'
        if kind == 'error':
            raise payload
        if kind == 'candidate' and self.flow_id is not None:
            payload = {key: dict(value, flow_id=self.flow_id) for key, value in payload.items()}
        if kind == 'candidate':
            self._candidate = {key: read_float_structure(value, field=key) for key, value in payload.items()}
        return kind, payload

    def respond(self, packet):
        if self._cancelled.is_set():
            raise SessionCancelled('Оптимизатор остановлен.')
        if not self._waiting:
            raise RuntimeError('Optimizer is not waiting for J.')
        score = read_float_structure(packet, field='J')
        self.entries.append({'trial': len(self.entries) + 1, 'flow_id': self.flow_id,
                             'values': dict(self._candidate), 'J': score})
        self._waiting = False
        try:
            self._scores.put_nowait(score)
        except queue.Full:
            if self._cancelled.is_set():
                raise SessionCancelled('Оптимизатор остановлен.')
            raise RuntimeError('Оптимизатор уже получил результат J.')
        return self._next()

    def request_stop(self):
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        self._events.put(('cancelled', None))
        try:
            self._scores.put_nowait(_Cancelled)
        except queue.Full:
            pass

    def close(self):
        self.request_stop()
        if self._started:
            self._thread.join()


class OptimizerSession:
    """Expose the active optimizer to session-wide cancellation."""
    def __init__(self):
        self._lock = threading.Lock()
        self._stopped = False
        self._active = None

    def attach(self, controller):
        with self._lock:
            if self._stopped:
                raise SessionCancelled('Сессия остановлена.')
            self._active = controller

    def detach(self, controller):
        with self._lock:
            if self._active is controller:
                self._active = None

    def request_stop(self):
        with self._lock:
            self._stopped = True
            controller = self._active
        if controller is not None:
            controller.request_stop()

    def close_session(self):
        self.request_stop()
