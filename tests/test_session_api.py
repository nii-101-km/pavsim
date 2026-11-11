from tests.starter_helpers import start_model
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from shell import server


class SessionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def post(self, path, payload):
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_flow_event_stream_pushes_updates_and_completion(self):
        run_id = 'f' * 32
        model = {'blocks': []}
        server.LIVE_RESULTS.prepare(model, run_id)
        with urllib.request.urlopen(self.base + '/api/flow-events?run=' + run_id, timeout=5) as stream:
            self.assertTrue(stream.headers['Content-Type'].startswith('text/event-stream'))
            first = json.loads(stream.readline().decode().removeprefix('data: '))
            stream.readline()
            self.assertFalse(first['complete'])
            server.LIVE_RESULTS.publish_flows(run_id, {'b': [{'flow_id': '1'}]})
            update = json.loads(stream.readline().decode().removeprefix('data: '))
            stream.readline()
            self.assertEqual(update['blocks']['b'][0]['flow_id'], '1')
            server.LIVE_RESULTS.finish(model, run_id)
            final = json.loads(stream.readline().decode().removeprefix('data: '))
            self.assertTrue(final['complete'])
            self.assertEqual(final['blocks'], {})

    def test_distinct_sessions_and_expired_session_rejected(self):
        _, left = self.post('/api/session', {})
        _, right = self.post('/api/session', {})
        self.assertNotEqual(left['session_id'], right['session_id'])
        self.assertEqual(self.post('/api/session/touch', left)[0], 200)
        server.SESSION_HEAPS.close(left['session_id'])
        self.assertEqual(self.post('/api/session/touch', left)[0], 404)
        self.assertEqual(self.post('/api/session/touch', right)[0], 200)
        server.SESSION_HEAPS.close(right['session_id'])

    def test_simulation_rejects_expired_session(self):
        status, result = self.post('/api/simulate', {'session_id': 'not-a-session', 'model': {}})
        self.assertEqual(status, 400)
        self.assertIn('session', result['error'].lower())

    def test_different_optimizer_flows_are_reported_by_process(self):
        _, session = self.post('/api/session', {})
        model = {'blocks': [
            {'id': 'a', 'type': 'optimizer', 'params': {'max_evaluations': 20}},
            {'id': 'b', 'type': 'optimizer', 'params': {'max_evaluations': 20}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'P2', 'type': 'experiment_input', 'params': {'port': 1}},
                                     {'id': 'sum', 'type': 'addition'}, {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'sum', 'to_port': 0},
                                          {'from': 'P2', 'to': 'sum', 'to_port': 1}, {'from': 'sum', 'to': 'J'}]}},
        ], 'connections': [{'from': 'a', 'to': 'exp', 'to_port': 0}, {'from': 'b', 'to': 'exp', 'to_port': 1},
                           {'from': 'exp', 'to': 'a'}, {'from': 'exp', 'to': 'b'}]}
        try:
            status, result = self.post('/api/simulate', {'model': start_model(model), 'session_id': session['session_id']})
            self.assertEqual(status, 400)
            self.assertIn('разным потокам', result['error'])
            self.assertIn('p1=1', result['error'])
            self.assertIn('p2=2', result['error'])
        finally:
            server.SESSION_HEAPS.close(session['session_id'])

    def test_plot_receives_points_while_optimization_is_running(self):
        model = {'blocks': [
            {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20, 'optimize_p2': False, 'trial_delay': .03}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'J'}]}},
            {'id': 'plot', 'type': 'graph_outer'},
        ], 'connections': [
            {'from': 'opt', 'from_port': 0, 'to': 'exp', 'to_port': 0},
            {'from': 'exp', 'to': 'opt'}, {'from': 'exp', 'to': 'plot'},
            {'from': 'opt', 'from_port': 3, 'to': 'plot', 'to_port': 1},
        ]}
        start_model(model)
        model['connections'].sort(key=lambda wire: wire['to'] != 'plot')
        run_id = 'a' * 32
        response = []
        worker = threading.Thread(target=lambda: response.append(self.post('/api/simulate', {'model': model, 'run_id': run_id})))
        worker.start()
        observed = None
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline and worker.is_alive():
                try:
                    with urllib.request.urlopen(self.base + '/api/plot?run=' + run_id + '&block=plot') as stream:
                        snapshot = json.load(stream)
                    if snapshot.get('complete') is False and snapshot['data']['y']:
                        observed = snapshot
                        with urllib.request.urlopen(self.base + '/api/flows?run=' + run_id) as stream:
                            flows = json.load(stream)
                        self.assertFalse(flows['complete'])
                        self.assertIsInstance(flows['blocks'], dict)
                        break
                except urllib.error.HTTPError:
                    pass
                time.sleep(.01)
        finally:
            worker.join(timeout=5)
        self.assertIsNotNone(observed, 'No points were visible while the run was active')
        self.assertFalse(worker.is_alive())
        self.assertEqual(response[0][0], 200)
        with urllib.request.urlopen(self.base + '/api/plot?run=' + run_id + '&block=plot') as stream:
            final = json.load(stream)
        self.assertTrue(final['complete'])
        self.assertGreater(len(final['data']['y']), len(observed['data']['y']))
        with urllib.request.urlopen(self.base + '/api/output?run=' + run_id + '&block=opt') as stream:
            log = json.load(stream)
        self.assertTrue(log['complete'])
        self.assertEqual(len(log['data']['entries']), len(final['data']['y']))
        self.assertEqual(log['data']['entries'][0]['flow_id'], '1')
        with urllib.request.urlopen(self.base + '/api/flows?run=' + run_id) as stream:
            self.assertEqual(json.load(stream), {'blocks': {}, 'complete': True})

    def test_stop_cancels_work_without_stopping_another_session(self):
        _, first = self.post('/api/session', {})
        _, second = self.post('/api/session', {})
        model = {'blocks': [
            {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20, 'trial_delay': 30}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'J'}]}},
            {'id': 'plot', 'type': 'graph_outer'},
        ], 'connections': [{'from': 'opt', 'to': 'exp'}, {'from': 'exp', 'to': 'opt'},
                           {'from': 'exp', 'to': 'plot'}]}
        start_model(model)
        model['connections'].sort(key=lambda wire: wire['to'] != 'plot')
        run_id = 'b' * 32
        response = []
        worker = threading.Thread(target=lambda: response.append(self.post('/api/simulate', {
            'model': model, 'run_id': run_id, 'session_id': first['session_id']})))
        worker.start()
        try:
            deadline = time.monotonic() + 5
            seen = False
            while time.monotonic() < deadline and worker.is_alive():
                try:
                    with urllib.request.urlopen(self.base + '/api/plot?run=' + run_id + '&block=plot') as stream:
                        seen = bool(json.load(stream)['data']['y'])
                    if seen:
                        break
                except urllib.error.HTTPError:
                    pass
                time.sleep(.01)
            self.assertTrue(seen)
            status, stopped = self.post('/api/session/stop', first)
            self.assertEqual(status, 200)
            self.assertEqual(stopped['status'], 'stopped')
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(response[0][0], 400)
            self.assertEqual(self.post('/api/session/touch', first)[0], 404)
            self.assertEqual(self.post('/api/session/touch', second)[0], 200)
        finally:
            server.SESSION_HEAPS.close(first['session_id'])
            server.SESSION_HEAPS.close(second['session_id'])
            worker.join(timeout=5)
