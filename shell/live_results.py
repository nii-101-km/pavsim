"""Thread-safe snapshots of recent runs, independent of the HTTP server."""
from collections import OrderedDict
import copy
import threading

from .outer_graphs import OUTER_GRAPHS


class LiveResults:
    def __init__(self, collect_plots, limit=5):
        self._collect_plots = collect_plots
        self._limit = limit
        self._runs = OrderedDict()
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)

    def prepare(self, model, run_id):
        placeholders, outputs = {}, {}
        def walk(diagram, prefix=''):
            for block in diagram.get('blocks', []):
                key = prefix + str(block['id'])
                if block.get('type') in OUTER_GRAPHS:
                    placeholders[key] = {'t': [], 'y': []}
                if block.get('type') == 'optimizer':
                    outputs[key] = {'data': {'kind': 'optimizer_log', 'entries': []}, 'complete': False}
                if block.get('internal'):
                    walk(block['internal'], key + '/')
        walk(model)
        plots = self._collect_plots(model, placeholders)
        for packet in plots.values():
            packet['complete'] = False
        with self._lock:
            self._runs[run_id] = {'plots': plots, 'outputs': outputs,
                                  'flows': {'blocks': {}, 'complete': False},
                                  'flow_seq': 0}
            while len(self._runs) > self._limit:
                self._runs.popitem(last=False)
            self._changed.notify_all()

    def finish(self, model, run_id, results=None, raw_results=None):
        plots = self._collect_plots(model, results or {})
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run['plots'].update(plots)
            for packet in run['plots'].values():
                packet['complete'] = True
            run['flows'] = {'blocks': {}, 'complete': True}
            run['flow_seq'] += 1
            self._changed.notify_all()
            for node_id, result in (raw_results or {}).items():
                if node_id in run['outputs'] and '_output' in result:
                    run['outputs'][node_id]['data'] = result['_output']
            for packet in run['outputs'].values():
                packet['complete'] = True

    def publish_output(self, run_id, node_id, data):
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            packet = run['plots'].get(node_id) or run['outputs'].get(node_id)
            if packet is not None:
                packet['data'] = data

    def publish_flows(self, run_id, blocks):
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run['flows'] = {'blocks': blocks, 'complete': False}
                run['flow_seq'] += 1
                self._changed.notify_all()

    def wait_flows(self, run_id, after, timeout=10):
        """Return the latest process state; intermediate states need not queue."""
        with self._changed:
            def ready():
                run = self._runs.get(run_id)
                return run is not None and run['flow_seq'] > after
            if not ready():
                self._changed.wait_for(ready, timeout)
            run = self._runs.get(run_id)
            if run is None:
                return None
            return copy.deepcopy({**run['flows'], 'seq': run['flow_seq']})

    def get(self, run_id, kind, block_id=None):
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            packet = run[kind] if kind == 'flows' else run[kind].get(block_id)
            return copy.deepcopy(packet)
