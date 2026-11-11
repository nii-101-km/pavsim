import unittest

from engines.optimizer import create_optimizer
from shell.graph import Connection, DataGraph, GraphError, Node
from shell.heap import SessionHeap
from shell.registry import ExecutorRegistry
from shell.signal_engine import SignalEngine
from shell.structures import float_structure, read_float_structure


class Trial:
    name = 'trial'
    def execute_block(self, node, inputs, heap):
        params = node.params
        return {'J': dict(float_structure(read_float_structure(inputs['p1'])), flow_id=inputs['p1']['flow_id'])}


def diagram():
    graph = DataGraph()
    graph.add_node(Node('launch', 'starter', {'flow_id': '1'}))
    graph.add_node(Node('opt', 'optimizer', {'max_evaluations': 20, 'optimize_p2': False}))
    graph.add_node(Node('trial', 'trial'))
    graph.add_node(Node('plot', 'graph_outer'))
    graph.add_connection(Connection('launch', 'start', 'plot', 'reset'))
    graph.add_connection(Connection('launch', 'start', 'opt', 'start'))
    graph.add_connection(Connection('opt', 'p1', 'trial', 'p1'))
    graph.add_connection(Connection('trial', 'J', 'opt', 'J'))
    graph.add_connection(Connection('trial', 'J', 'plot', 'value'))
    return graph


class StarterTests(unittest.TestCase):
    def test_constant_emits_only_on_start_and_keeps_flow_number(self):
        graph = DataGraph()
        graph.add_node(Node('launch', 'starter', {'flow_id': '7'}))
        graph.add_node(Node('constant', 'input_value', {'value': 1.25}))
        graph.add_node(Node('view', 'result_display'))
        graph.add_connection(Connection('launch', 'start', 'constant', 'start'))
        graph.add_connection(Connection('constant', 'value', 'view', 'value'))
        result = SignalEngine(SessionHeap()).execute(graph)
        self.assertEqual(result['view']['displayed'], {'type': 'float', 'value': '1.25', 'flow_id': '7'})

    def test_constant_without_start_fails_clearly(self):
        graph = DataGraph(); graph.add_node(Node('c', 'input_value', {'value': 1}))
        with self.assertRaisesRegex(ValueError, 'сигнал запуска'):
            SignalEngine(SessionHeap()).execute(graph)

    def test_starter_runs_optimizer_and_resets_graph(self):
        registry = ExecutorRegistry(); registry.register(Trial())
        events = []
        states = []
        result = SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(
            diagram(), on_plot=lambda node, data: events.append(list(data['y'])), on_flow=states.append)
        self.assertEqual(events[0], [])
        self.assertEqual(len(result['plot']['_plot']['y']), 20)
        self.assertEqual(result['opt']['_report']['evaluations'], 20)
        log = result['opt']['_output']['entries']
        self.assertEqual(len(log), 20)
        self.assertEqual(log[0]['flow_id'], '1')
        self.assertEqual(log[0]['J'], log[0]['values']['p1'])
        self.assertTrue(any(any(token['flow_id'] == '1' and token['state'] == 'working'
                                for token in state.get('opt', [])) for state in states))
        self.assertTrue(any(any(token['flow_id'] == '1' and token['state'] == 'working'
                                for token in state.get('trial', []))
                            and not state.get('opt') for state in states))
        self.assertEqual(states[-1], {})

    def test_optimizer_requires_start_connection(self):
        graph = diagram()
        graph.connections = [wire for wire in graph.connections if not (wire.to_node == 'opt' and wire.to_port == 'start')]
        registry = ExecutorRegistry(); registry.register(Trial())
        with self.assertRaisesRegex(GraphError, 'запуска'):
            SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(graph)

    def test_optimizer_badge_stays_visible_during_trial_delay(self):
        import threading
        graph = diagram()
        graph.nodes['opt'].params['trial_delay'] = 1
        registry = ExecutorRegistry(); registry.register(Trial())
        cancel = threading.Event()
        delay_seen = threading.Event()
        states = []
        def on_flow(state):
            states.append(state)
            if any(t['state'] == 'working' for t in state.get('opt', [])) and any(
                not prior.get('opt') and prior.get('trial') for prior in states):
                delay_seen.set()
        def run():
            try:
                SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(
                    graph, on_flow=on_flow, cancel_event=cancel)
            except Exception:
                pass
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(delay_seen.wait(3))
            self.assertFalse(cancel.wait(.05))
            self.assertEqual(len(states[-1].get('opt', [])), 1)
        finally:
            cancel.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(states[-1], {})

    def test_optimizer_rejects_untagged_or_wrong_flow_result(self):
        for flow_id in (None, '99'):
            class WrongTrial:
                name = 'trial'
                def execute_block(self, node, inputs, heap):
                    params = node.params
                    packet = float_structure(1)
                    if flow_id is not None:
                        packet['flow_id'] = flow_id
                    return {'J': packet}
            registry = ExecutorRegistry(); registry.register(WrongTrial())
            with self.subTest(flow_id=flow_id), self.assertRaisesRegex(GraphError, 'ожидается 1'):
                SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(diagram())

    def test_second_start_during_optimization_is_rejected(self):
        graph = diagram()
        graph.connections = [wire for wire in graph.connections if wire.from_node != 'opt' or wire.to_node != 'trial']
        graph.add_node(Node('view', 'result_display'))
        graph.add_connection(Connection('opt', 'p1', 'view', 'value'))
        registry = ExecutorRegistry(); registry.register(Trial())
        initial = [('launch', {'start': {'type': 'event', 'value': 'start', 'flow_id': '1'}}),
                   ('launch', {'start': {'type': 'event', 'value': 'start', 'flow_id': '1'}})]
        with self.assertRaisesRegex(GraphError, 'повторный запуск'):
            SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(graph, initial_outputs=initial)

    def test_optimizer_accepts_new_start_after_completion(self):
        registry = ExecutorRegistry(); registry.register(Trial())
        event = {'type': 'event', 'value': 'start', 'flow_id': '1'}
        result = SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(
            diagram(), initial_outputs=[('launch', {'start': event}), ('launch', {'start': event})])
        self.assertEqual(len(result['opt']['_output']['entries']), 40)
        self.assertEqual(len(result['plot']['_plot']['y']), 20)
