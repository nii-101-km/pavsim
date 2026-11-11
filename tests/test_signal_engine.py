import unittest

from shell.graph import Connection, DataGraph, GraphError, Node
from shell.heap import SessionHeap
from shell.registry import ExecutorRegistry
from shell.signal_engine import SignalEngine
from shell.structures import float_structure, read_float_structure
from engines.optimizer import create_optimizer
from tests.starter_helpers import start_graph


class Join:
    name = 'join'

    def __init__(self):
        self.seen = []

    def execute_block(self, node, inputs, heap):

        params = node.params
        self.seen.append((read_float_structure(inputs['a']), read_float_structure(inputs['b'])))
        return {'out': float_structure(sum(self.seen[-1]))}


class Forward:
    name = 'forward_signal'

    def execute_block(self, node, inputs, heap):

        params = node.params
        return {'out': inputs['value']}


class Quadratic:
    name = 'quadratic'
    def execute_block(self, node, inputs, heap):
        params = node.params
        value = read_float_structure(inputs['p1'])
        return {'J': dict(float_structure((value - 1) ** 2), flow_id=inputs['p1']['flow_id'])}


class SharedTrial:
    name = 'shared_trial'
    def execute_block(self, node, inputs, heap):
        params = node.params
        if inputs['a'].get('flow_id') != inputs['b'].get('flow_id'):
            raise ValueError('разные потоки')
        a = read_float_structure(inputs['a'])
        b = read_float_structure(inputs['b'])
        return {'J': dict(float_structure((a - 1) ** 2 + (b - 1) ** 2), flow_id=inputs['a']['flow_id'])}


class SignalEngineTests(unittest.TestCase):
    def test_block_selects_how_each_input_signal_is_processed(self):
        class EachSignal:
            def __init__(self, ports):
                self.ports = set(ports)
            def receive(self, port, packet):
                if port not in self.ports:
                    raise ValueError('unknown port')
                return {port: packet}
            def waiting_for(self):
                return ()
            def drain(self):
                return iter(())
        class Eager:
            name = 'eager'
            create_input_state = EachSignal
            def __init__(self):
                self.seen = []
            def execute_block(self, node, inputs, heap):
                params = node.params
                self.seen.append(next(iter(inputs)))
                return {}
        graph = DataGraph()
        for name, kind in [('a', 'input_value'), ('b', 'input_value'), ('target', 'eager')]:
            graph.add_node(Node(name, kind))
        graph.add_connection(Connection('a', 'value', 'target', 'x'))
        graph.add_connection(Connection('b', 'value', 'target', 'y'))
        eager = Eager(); registry = ExecutorRegistry(); registry.register(eager)
        SignalEngine(SessionHeap(), registry).execute(graph, initial_outputs=[
            ('a', {'value': float_structure(1)}), ('b', {'value': float_structure(2)})])
        self.assertEqual(eager.seen, ['x', 'y'])

    def test_error_releases_undelivered_depth_first_branches(self):
        class Fail:
            name = 'fail'
            def execute_block(self, node, inputs, heap):
                params = node.params
                raise ValueError('failed')
        graph = DataGraph()
        for node, kind in [('source', 'input_value'), ('bad', 'fail'), ('next', 'forward_signal')]:
            graph.add_node(Node(node, kind))
        graph.add_connection(Connection('source', 'value', 'bad', 'value'))
        graph.add_connection(Connection('source', 'value', 'next', 'value'))
        heap = SessionHeap(); original = heap.put('payload')
        registry = ExecutorRegistry(); registry.register(Fail()); registry.register(Forward())
        with self.assertRaisesRegex(ValueError, 'failed'):
            SignalEngine(heap, registry).execute(graph, initial_outputs=[('source', {'value': original})])
        self.assertEqual(len(heap._references), 1)
        heap.release(original)
        self.assertFalse(heap._objects)

    def test_wire_branches_are_processed_depth_first(self):
        order = []
        class Recorder:
            name = 'recorder'
            def execute_block(self, node, inputs, heap):
                params = node.params
                order.append(params['name'])
                return {'out': inputs['value']}
        graph = DataGraph(); graph.add_node(Node('start', 'starter', {'flow_id': '1'}))
        for name in ('a', 'b', 'c', 'd'):
            graph.add_node(Node(name, 'recorder', {'name': name}))
        for source, port, dest in (('start', 'start', 'a'), ('start', 'start', 'b'),
                                   ('a', 'out', 'c'), ('b', 'out', 'd')):
            graph.add_connection(Connection(source, port, dest, 'value'))
        registry = ExecutorRegistry(); registry.register(Recorder())
        SignalEngine(SessionHeap(), registry).execute(graph)
        self.assertEqual(order, ['a', 'c', 'b', 'd'])

    def test_same_flow_inputs_join_into_one_working_badge(self):
        graph = self.graph()
        registry = ExecutorRegistry(); registry.register(Join())
        states = []
        packet = dict(float_structure(1), flow_id='1')
        SignalEngine(SessionHeap(), registry).execute(graph, initial_outputs=[
            ('a', {'value': packet}), ('b', {'value': packet})], on_flow=states.append)
        self.assertTrue(any(len(state.get('join', [])) == 2 and
                            all(token['state'] == 'waiting' for token in state['join'])
                            for state in states))
        self.assertTrue(any(len(state.get('join', [])) == 1 and
                            state['join'][0]['state'] == 'working'
                            for state in states))

    def graph(self):
        graph = DataGraph()
        for node, kind in [('a', 'input_value'), ('b', 'input_value'), ('join', 'join'), ('view', 'result_display')]:
            graph.add_node(Node(node, kind))
        graph.add_connection(Connection('a', 'value', 'join', 'a'))
        graph.add_connection(Connection('b', 'value', 'join', 'b'))
        graph.add_connection(Connection('join', 'out', 'view', 'value'))
        return graph

    def test_repeated_input_is_rejected(self):
        heap = SessionHeap()
        registry = ExecutorRegistry()
        join = Join()
        registry.register(join)
        signals = [('a', {'value': float_structure(1)}), ('a', {'value': float_structure(2)}),
                   ('b', {'value': float_structure(10)}), ('b', {'value': float_structure(20)})]
        with self.assertRaisesRegex(GraphError, 'join.*a.*уже содержит сигнал'):
            SignalEngine(heap, registry).execute(self.graph(), initial_outputs=signals)

    def test_missing_signal_reports_port_and_releases_pending_reference(self):
        heap = SessionHeap()
        ref = heap.put({'large': [1, 2, 3]})
        registry = ExecutorRegistry()
        registry.register(Join())
        signals = [('a', {'value': ref}), ('b', {})]
        # Use a plain forwarder to avoid interpreting the reference as a number.
        class Consume:
            name = 'join'
            def execute_block(self, node, inputs, heap):
                params = node.params
                return {}
        registry.register(Consume())
        with self.assertRaisesRegex(GraphError, 'join: b'):
            SignalEngine(heap, registry).execute(self.graph(), initial_outputs=signals)
        self.assertEqual(len(heap._references), 1)  # only the caller's original lease
        heap.release(ref)
        self.assertFalse(heap._objects)

    def test_rejected_reference_is_released(self):
        heap = SessionHeap()
        ref = heap.put('payload')
        registry = ExecutorRegistry(); registry.register(Join())
        with self.assertRaisesRegex(GraphError, 'уже содержит сигнал'):
            SignalEngine(heap, registry).execute(self.graph(), initial_outputs=[
                ('a', {'value': ref}), ('a', {'value': ref})])
        self.assertEqual(len(heap._references), 1)
        heap.release(ref)
        self.assertFalse(heap._objects)

    def test_feedback_is_bounded_and_releases_references_on_limit(self):
        graph = DataGraph()
        graph.add_node(Node('f', 'forward_signal'))
        graph.add_connection(Connection('f', 'out', 'f', 'value'))
        heap = SessionHeap()
        ref = heap.put('payload')
        registry = ExecutorRegistry()
        registry.register(Forward())
        with self.assertRaisesRegex(GraphError, 'предел'):
            SignalEngine(heap, registry).execute(graph, initial_outputs=[('f', {'out': ref})], max_invocations=3000)
        self.assertEqual(len(heap._references), 1)
        heap.release(ref)
        self.assertFalse(heap._objects)

    def test_telemetry_failure_does_not_leak_delivered_reference(self):
        graph = DataGraph()
        graph.add_node(Node('source', 'input_value'))
        graph.add_node(Node('consumer', 'forward_signal'))
        graph.add_connection(Connection('source', 'value', 'consumer', 'value'))
        heap = SessionHeap()
        original = dict(heap.put('payload'), flow_id='1')
        registry = ExecutorRegistry(); registry.register(Forward())
        def fail_on_working(blocks):
            if any(token['state'] == 'working' for values in blocks.values() for token in values):
                raise RuntimeError('telemetry unavailable')
        with self.assertRaisesRegex(RuntimeError, 'telemetry unavailable'):
            SignalEngine(heap, registry).execute(graph, initial_outputs=[('source', {'value': original})], on_flow=fail_on_working)
        self.assertEqual(len(heap._references), 1)
        heap.release(original)
        self.assertFalse(heap._objects)

    def test_telemetry_failure_after_all_inputs_arrive_releases_both_references(self):
        graph = self.graph()
        heap = SessionHeap(); original = dict(heap.put('payload'), flow_id='1')
        registry = ExecutorRegistry(); registry.register(Join())
        def fail_on_both_waiting(blocks):
            tokens = blocks.get('join', [])
            if len(tokens) == 2 and all(token['state'] == 'waiting' for token in tokens):
                raise RuntimeError('telemetry unavailable')
        with self.assertRaisesRegex(RuntimeError, 'telemetry unavailable'):
            SignalEngine(heap, registry).execute(graph, initial_outputs=[
                ('a', {'value': original}), ('b', {'value': original})], on_flow=fail_on_both_waiting)
        self.assertEqual(len(heap._references), 1)
        heap.release(original)
        self.assertFalse(heap._objects)

    def test_optimizer_repeats_trials_through_the_graph(self):
        graph = DataGraph()
        graph.add_node(Node('opt', 'optimizer', {'max_evaluations': 20, 'optimize_p2': False}))
        graph.add_node(Node('trial', 'quadratic'))
        graph.add_connection(Connection('opt', 'p1', 'trial', 'p1'))
        graph.add_connection(Connection('trial', 'J', 'opt', 'J'))
        registry = ExecutorRegistry()
        registry.register(Quadratic())
        result = SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(start_graph(graph))
        report = result['opt']['_report']
        self.assertGreater(report['evaluations'], 1)
        self.assertLess(report['score'], 1)

    def test_two_independent_optimizers_do_not_exchange_results(self):
        graph = DataGraph()
        for suffix in ('1', '2'):
            graph.add_node(Node('opt' + suffix, 'optimizer', {'max_evaluations': 20, 'optimize_p2': False}))
            graph.add_node(Node('trial' + suffix, 'quadratic'))
            graph.add_connection(Connection('opt' + suffix, 'p1', 'trial' + suffix, 'p1'))
            graph.add_connection(Connection('trial' + suffix, 'J', 'opt' + suffix, 'J'))
        registry = ExecutorRegistry()
        registry.register(Quadratic())
        result = SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(start_graph(graph))
        self.assertGreater(result['opt1']['_report']['evaluations'], 1)
        self.assertGreater(result['opt2']['_report']['evaluations'], 1)

    def test_two_optimizers_with_different_flows_cannot_share_trial(self):
        graph = DataGraph()
        graph.add_node(Node('trial', 'shared_trial'))
        for suffix, port in (('1', 'a'), ('2', 'b')):
            graph.add_node(Node('opt' + suffix, 'optimizer', {'max_evaluations': 20, 'optimize_p2': False}))
            graph.add_connection(Connection('opt' + suffix, 'p1', 'trial', port))
            graph.add_connection(Connection('trial', 'J', 'opt' + suffix, 'J'))
        registry = ExecutorRegistry()
        registry.register(SharedTrial())
        with self.assertRaisesRegex(ValueError, 'разные потоки'):
            SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(start_graph(graph))

    def test_shared_trial_rejects_different_flows_before_one_finishes(self):
        graph = DataGraph()
        graph.add_node(Node('trial', 'shared_trial'))
        for suffix, port, limit in (('1', 'a', 20), ('2', 'b', 30)):
            graph.add_node(Node('opt' + suffix, 'optimizer', {'max_evaluations': limit, 'optimize_p2': False}))
            graph.add_connection(Connection('opt' + suffix, 'p1', 'trial', port))
            graph.add_connection(Connection('trial', 'J', 'opt' + suffix, 'J'))
        registry = ExecutorRegistry()
        registry.register(SharedTrial())
        with self.assertRaisesRegex(ValueError, 'разные потоки'):
            SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(start_graph(graph))

    def test_optimizer_delay_holds_back_other_blocks(self):
        graph = DataGraph()
        for suffix, delay in (('slow', .02), ('fast', 0)):
            graph.add_node(Node('opt' + suffix, 'optimizer', {'max_evaluations': 20, 'optimize_p2': False, 'trial_delay': delay}))
            graph.add_node(Node('trial' + suffix, 'quadratic'))
            graph.add_node(Node('plot' + suffix, 'graph_outer'))
            graph.add_connection(Connection('opt' + suffix, 'p1', 'trial' + suffix, 'p1'))
            graph.add_connection(Connection('trial' + suffix, 'J', 'opt' + suffix, 'J'))
            graph.add_connection(Connection('trial' + suffix, 'J', 'plot' + suffix, 'value'))
        registry = ExecutorRegistry()
        registry.register(Quadratic())
        updates = []
        SignalEngine(SessionHeap(), registry, {'optimizer': create_optimizer}).execute(
            start_graph(graph), on_plot=lambda node, data: updates.append((node, len(data['y']))))
        self.assertLess(updates.index(('plotslow', 2)), updates.index(('plotfast', 2)))
