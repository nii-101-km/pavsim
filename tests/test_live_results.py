import unittest
import threading

from shell.live_results import LiveResults


def collect(_model, results):
    return {key: {'data': value} for key, value in results.items() if key == 'plot'}


class LiveResultsTests(unittest.TestCase):
    def test_flow_updates_wake_waiters_and_completion_clears_state(self):
        store = LiveResults(collect)
        model = {'blocks': []}
        store.prepare(model, 'run')
        seen = []
        waiter = threading.Thread(target=lambda: seen.append(store.wait_flows('run', 0, 2)))
        waiter.start()
        store.publish_flows('run', {'b': [{'flow_id': '1'}]})
        waiter.join(2)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(seen[0]['blocks']['b'][0]['flow_id'], '1')
        store.finish(model, 'run')
        final = store.wait_flows('run', seen[0]['seq'], 1)
        self.assertTrue(final['complete'])
        self.assertEqual(final['blocks'], {})

    def test_updates_are_isolated_and_completed(self):
        model = {'blocks': [{'id': 'plot', 'type': 'graph_outer'},
                            {'id': 'opt', 'type': 'optimizer'}]}
        store = LiveResults(collect)
        store.prepare(model, 'run')
        store.publish_output('run', 'plot', {'y': [1]})
        store.publish_output('run', 'opt', {'entries': [2]})
        store.publish_flows('run', {'opt': [{'flow_id': '1'}]})
        snapshot = store.get('run', 'plots', 'plot')
        snapshot['data']['y'].append(99)
        self.assertEqual(store.get('run', 'plots', 'plot')['data']['y'], [1])
        store.finish(model, 'run', {'plot': {'y': [1, 2]}},
                     {'opt': {'_output': {'entries': [2, 3]}}})
        self.assertTrue(store.get('run', 'plots', 'plot')['complete'])
        self.assertEqual(store.get('run', 'outputs', 'opt')['data']['entries'], [2, 3])
        self.assertEqual(store.get('run', 'flows'), {'blocks': {}, 'complete': True})

    def test_old_runs_are_evicted_as_a_unit(self):
        store = LiveResults(collect, limit=1)
        store.prepare({'blocks': []}, 'old')
        store.prepare({'blocks': []}, 'new')
        self.assertIsNone(store.get('old', 'flows'))
        self.assertIsNotNone(store.get('new', 'flows'))
        store.finish({'blocks': []}, 'old')
        self.assertIsNone(store.get('old', 'flows'))
