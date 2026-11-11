from tests.starter_helpers import start_model
from tests.starter_helpers import start_graph
import unittest

from shell.graph import Connection, DataGraph, GraphError, Node
from shell.heap import SessionHeap
from shell.server import _collect_plots, _execute_generic_dataflow
from shell.signal_engine import SignalEngine
from shell.structures import float_structure


class OuterGraphTests(unittest.TestCase):
    def test_xy_score_rejects_invalid_display_settings(self):
        for params in ({'last_points': -1}, {'last_points': 1.5}, {'x_range': '3:1'}, {'y_range': 'a:b'},
                       {'x_start': '1', 'x_end': ''}, {'y_start': '3', 'y_end': '1'}):
            graph = DataGraph()
            for source in ('x', 'y'):
                graph.add_node(Node(source, 'input_value'))
            graph.add_node(Node('plot', 'graph_outer_xy_score', params))
            graph.add_connection(Connection('x', 'value', 'plot', 'x'))
            graph.add_connection(Connection('y', 'value', 'plot', 'y'))
            with self.subTest(params=params), self.assertRaises(ValueError):
                SignalEngine(SessionHeap()).execute(graph)

    def test_multiseries_waits_for_each_connected_value_and_reset_clears_partial(self):
        graph = DataGraph()
        for node in ('a', 'b', 'reset'):
            graph.add_node(Node(node, 'input_value'))
        graph.add_node(Node('plot', 'graph_outer_series2'))
        graph.add_connection(Connection('a', 'value', 'plot', 'y1'))
        graph.add_connection(Connection('b', 'value', 'plot', 'y2'))
        graph.add_connection(Connection('reset', 'value', 'plot', 'reset'))
        signals = [('a', {'value': float_structure(1)}), ('b', {'value': float_structure(2)}),
                   ('a', {'value': float_structure(99)}),
                   ('reset', {'value': {'type': 'event', 'value': 'start'}}),
                   ('b', {'value': float_structure(4)}), ('a', {'value': float_structure(3)})]
        result = SignalEngine(SessionHeap()).execute(graph, initial_outputs=signals)
        self.assertEqual(result['plot']['_plot'], {'t': [1], 'y': [3.0], 'outputs': [[3.0], [4.0]]})

    def test_xy_score_uses_optional_j_and_preserves_order(self):
        for with_score in (False, True):
            graph = DataGraph()
            for source in ('x', 'y', 'j'):
                graph.add_node(Node(source, 'input_value', {'value': 2}))
            graph.add_node(Node('plot', 'graph_outer_xy_score'))
            graph.add_connection(Connection('x', 'value', 'plot', 'x'))
            graph.add_connection(Connection('y', 'value', 'plot', 'y'))
            if with_score:
                graph.add_connection(Connection('j', 'value', 'plot', 'J'))
            result = SignalEngine(SessionHeap()).execute(start_graph(graph))
            self.assertEqual(len(result['plot']['_plot']['outputs']), 3 if with_score else 2)

    def test_unmatched_graph_values_produce_error(self):
        graph = DataGraph()
        for source in ('a', 'b'):
            graph.add_node(Node(source, 'input_value'))
        graph.add_node(Node('plot', 'graph_outer_xy'))
        graph.add_connection(Connection('a', 'value', 'plot', 'x'))
        graph.add_connection(Connection('b', 'value', 'plot', 'y'))
        signals = [('a', {'value': float_structure(1)}), ('a', {'value': float_structure(2)}),
                   ('b', {'value': float_structure(3)})]
        with self.assertRaisesRegex(GraphError, 'plot.*x.*уже содержит сигнал'):
            SignalEngine(SessionHeap()).execute(graph, initial_outputs=signals)

    def test_reset_is_an_independent_signal_and_clears_old_points(self):
        graph = DataGraph()
        graph.add_node(Node('data', 'input_value'))
        graph.add_node(Node('reset', 'input_value'))
        graph.add_node(Node('plot', 'graph_outer'))
        graph.add_connection(Connection('data', 'value', 'plot', 'value'))
        graph.add_connection(Connection('reset', 'value', 'plot', 'reset'))
        signals = [('data', {'value': float_structure(1)}),
                   ('data', {'value': float_structure(2)}),
                   ('reset', {'value': {'type': 'event', 'value': 'start'}}),
                   ('data', {'value': float_structure(3)})]
        result = SignalEngine(SessionHeap()).execute(graph, initial_outputs=signals)
        self.assertEqual(result['plot']['_plot'], {'t': [1], 'y': [3.0]})

    def test_graph_rejects_invalid_data_and_needs_data_wire(self):
        graph = DataGraph()
        graph.add_node(Node('reset', 'input_value'))
        graph.add_node(Node('plot', 'graph_outer'))
        graph.add_connection(Connection('reset', 'value', 'plot', 'reset'))
        with self.assertRaisesRegex(GraphError, 'вход данных'):
            SignalEngine(SessionHeap()).execute(graph)

    def test_real_optimizer_records_each_completed_trial(self):
        model = {'blocks': [
            {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20, 'optimize_p2': False}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'J'}]}},
            {'id': 'plot', 'type': 'graph_outer', 'params': {'label': 'J'}},
        ], 'connections': [
            {'from': 'opt', 'from_port': 0, 'to': 'exp', 'to_port': 0},
            {'from': 'exp', 'from_port': 0, 'to': 'opt', 'to_port': 0},
            {'from': 'exp', 'from_port': 0, 'to': 'plot', 'to_port': 0},
            {'from': 'opt', 'from_port': 3, 'to': 'plot', 'to_port': 1},
        ]}
        updates = []
        result = _execute_generic_dataflow(start_model(model), on_plot=lambda node, data: updates.append((node, data)))
        plot = result['results']['plot']
        self.assertEqual(len(plot['y']), result['optimization'][0]['evaluations'])
        self.assertEqual(plot['t'], list(range(1, len(plot['y']) + 1)))
        self.assertEqual(_collect_plots(model, result['results'])['plot']['data'], plot)
        self.assertEqual(_collect_plots(model, result['results'])['plot']['config']['axis'], 'signal')
        self.assertEqual(updates[0], ('plot', {'t': [], 'y': []}))
        self.assertEqual(updates[-1][1], plot)
        self.assertEqual(len(updates), len(plot['y']) + 1)

    def test_xy_score_pairs_parameters_and_j_for_real_trials(self):
        model = {'blocks': [
            {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'P2', 'type': 'experiment_input', 'params': {'port': 1}},
                                     {'id': 'sum', 'type': 'addition'}, {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'sum', 'to_port': 0},
                                          {'from': 'P2', 'to': 'sum', 'to_port': 1},
                                          {'from': 'sum', 'to': 'J'}]}},
            {'id': 'plot', 'type': 'graph_outer_xy_score'},
        ], 'connections': [
            {'from': 'opt', 'from_port': 0, 'to': 'exp', 'to_port': 0},
            {'from': 'opt', 'from_port': 1, 'to': 'exp', 'to_port': 1},
            {'from': 'exp', 'to': 'opt'},
            {'from': 'opt', 'from_port': 0, 'to': 'plot', 'to_port': 0},
            {'from': 'opt', 'from_port': 1, 'to': 'plot', 'to_port': 1},
            {'from': 'exp', 'from_port': 0, 'to': 'plot', 'to_port': 2},
            {'from': 'opt', 'from_port': 3, 'to': 'plot', 'to_port': 3},
        ]}
        start_model(model)
        model['connections'].sort(key=lambda wire: wire['to'] != 'plot')
        result = _execute_generic_dataflow(model)
        data = result['results']['plot']
        self.assertEqual(len(data['t']), result['optimization'][0]['evaluations'])
        for x, y, score in zip(*data['outputs']):
            self.assertAlmostEqual(x + y, score)
        entries = result['raw_results']['opt']['_output']['entries']
        self.assertEqual(list(zip(*data['outputs'])),
                         [(entry['values']['p1'], entry['values']['p2'], entry['J']) for entry in entries])
        self.assertEqual(_collect_plots(model, result['results'])['plot']['config']['kind'], 'xy_score')
