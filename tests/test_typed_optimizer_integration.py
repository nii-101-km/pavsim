from tests.starter_helpers import start_model
import unittest

from shell.server import _execute_generic_dataflow
from shell.server import _unified_library


class TypedOptimizerIntegrationTests(unittest.TestCase):
    def test_constants_started_together_feed_one_experiment_flow(self):
        model = {'blocks': [
            {'id': 'start', 'type': 'starter', 'params': {'flow_id': '7'}},
            {'id': 'a', 'type': 'input_value', 'params': {'value': 1}},
            {'id': 'b', 'type': 'input_value', 'params': {'value': 2}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'P2', 'type': 'experiment_input', 'params': {'port': 1}},
                                     {'id': 'sum', 'type': 'addition'}, {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'sum', 'to_port': 0},
                                          {'from': 'P2', 'to': 'sum', 'to_port': 1},
                                          {'from': 'sum', 'to': 'J'}]}},
            {'id': 'view', 'type': 'result_display'},
        ], 'connections': [
            {'from': 'start', 'to': 'a'}, {'from': 'start', 'to': 'b'},
            {'from': 'a', 'to': 'exp', 'to_port': 0}, {'from': 'b', 'to': 'exp', 'to_port': 1},
            {'from': 'exp', 'to': 'view'},
        ]}
        result = _execute_generic_dataflow(model)
        self.assertEqual(result['raw_results']['view']['displayed']['flow_id'], '7')
        self.assertAlmostEqual(float(result['raw_results']['view']['displayed']['value']), 3)

    def test_experiment_checks_the_flows_from_two_optimizers(self):
        model = {'blocks': [
            {'id': 'a', 'type': 'optimizer', 'params': {'max_evaluations': 20}},
            {'id': 'b', 'type': 'optimizer', 'params': {'max_evaluations': 20}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'P2', 'type': 'experiment_input', 'params': {'port': 1}},
                                     {'id': 'sum', 'type': 'addition'}, {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'sum', 'to_port': 0},
                                          {'from': 'P2', 'to': 'sum', 'to_port': 1},
                                          {'from': 'sum', 'to': 'J'}]}},
        ], 'connections': [
            {'from': 'a', 'to': 'exp', 'to_port': 0}, {'from': 'b', 'to': 'exp', 'to_port': 1},
            {'from': 'exp', 'to': 'a'}, {'from': 'exp', 'to': 'b'},
        ]}
        start_model(model)
        with self.assertRaisesRegex(ValueError, r'разным потокам.*p1=1.*p2=2'):
            _execute_generic_dataflow(model)

    def test_optimizer_and_constant_share_starter_flow(self):
        model = {'blocks': [
            {'id': 'start', 'type': 'starter', 'params': {'flow_id': '7'}},
            {'id': 'opt', 'type': 'optimizer', 'params': {'enabled': False, 'p1': 1}},
            {'id': 'constant', 'type': 'input_value', 'params': {'value': 2}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                     {'id': 'P2', 'type': 'experiment_input', 'params': {'port': 1}},
                                     {'id': 'sum', 'type': 'addition'}, {'id': 'J', 'type': 'experiment_result'}],
                          'connections': [{'from': 'P1', 'to': 'sum', 'to_port': 0},
                                          {'from': 'P2', 'to': 'sum', 'to_port': 1},
                                          {'from': 'sum', 'to': 'J'}]}},
        ], 'connections': [{'from': 'start', 'to': 'opt', 'to_port': 1}, {'from': 'start', 'to': 'constant'},
                           {'from': 'opt', 'to': 'exp', 'to_port': 0},
                           {'from': 'constant', 'to': 'exp', 'to_port': 1},
                           {'from': 'exp', 'to': 'opt'}]}
        result = _execute_generic_dataflow(model)
        self.assertEqual(result['raw_results']['exp']['J']['flow_id'], '7')
        self.assertAlmostEqual(float(result['raw_results']['exp']['J']['value']), 3)
    def test_optimizer_and_real_experiment_exchange_typed_signals(self):
        model = {'blocks': [
            {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20, 'optimize_p2': False}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [
                 {'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                 {'id': 'J', 'type': 'experiment_result', 'params': {}},
             ], 'connections': [{'from': 'P1', 'from_port': 0, 'to': 'J', 'to_port': 0}]}},
        ], 'connections': [
            {'from': 'opt', 'from_port': 0, 'to': 'exp', 'to_port': 0},
            {'from': 'exp', 'from_port': 0, 'to': 'opt', 'to_port': 0},
        ]}
        result = _execute_generic_dataflow(start_model(model))
        self.assertEqual(len(result['optimization']), 1)
        self.assertGreater(result['optimization'][0]['evaluations'], 1)
        self.assertEqual(result['raw_results']['exp']['J']['type'], 'float')

    def test_objective_is_available_inside_experiment(self):
        library = _unified_library()
        self.assertEqual(library['block_contexts']['objective'], ['numerical'])
        self.assertTrue(any('objective' in category['blocks'] and 'numerical' in category['contexts']
                            for category in library['tree']))
        self.assertFalse(any('experiment' in category['blocks'] for category in library['tree']))

    def test_objective_is_evaluated_inside_experiment(self):
        model = {'blocks': [
            {'id': 'source', 'type': 'input_value', 'params': {'value': 0}},
            {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
             'internal': {'blocks': [
                 {'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                 {'id': 'obj', 'type': 'objective', 'params': {'objective': 'ise', 'target': 1}},
                 {'id': 'J', 'type': 'experiment_result', 'params': {}},
             ], 'connections': [
                 {'from': 'P1', 'from_port': 0, 'to': 'obj', 'to_port': 0},
                 {'from': 'obj', 'from_port': 0, 'to': 'J', 'to_port': 0}]}},
            {'id': 'view', 'type': 'result_display'},
        ], 'connections': [
            {'from': 'source', 'from_port': 0, 'to': 'exp', 'to_port': 0},
            {'from': 'exp', 'from_port': 0, 'to': 'view', 'to_port': 0},
        ]}
        result = _execute_generic_dataflow(start_model(model))
        self.assertAlmostEqual(float(result['raw_results']['view']['displayed']['value']), 1.0)

    def test_experiment_preserves_all_graph_channels(self):
        model = {'blocks': [{'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
                             'internal': {'blocks': [
                                 {'id': 'a', 'type': 'constant', 'params': {'value': 2}},
                                 {'id': 'b', 'type': 'constant', 'params': {'value': 5}},
                                 {'id': 'graph', 'type': 'graph_series2', 'params': {}},
                             ], 'connections': [
                                 {'from': 'a', 'from_port': 0, 'to': 'graph', 'to_port': 0},
                                 {'from': 'b', 'from_port': 0, 'to': 'graph', 'to_port': 1},
                             ]}}], 'connections': []}
        graph = _execute_generic_dataflow(start_model(model))['results']['exp/graph']
        self.assertEqual([channel[-1] for channel in graph['outputs']], [2, 5])

    def test_outer_subsystem_is_rejected_with_explanation(self):
        model = {'blocks': [{'id': 'sub', 'type': 'subsystem', 'internal': {}}], 'connections': []}
        with self.assertRaisesRegex(ValueError, 'только внутри динамической системы'):
            _execute_generic_dataflow(model)

    def test_subsystem_inside_experiment_still_runs(self):
        subsystem = {'id': 'sub', 'type': 'subsystem', 'internal': {
            'blocks': [
                {'id': 'In1', 'type': 'in1_terminal'}, {'id': 'Out1', 'type': 'out1_terminal'},
            ], 'connections': [{'from': 'In1', 'to': 'Out1'}]}}
        experiment = {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
                      'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                              subsystem, {'id': 'gain', 'type': 'gain', 'params': {'gain': 1}},
                                              {'id': 'J', 'type': 'experiment_result'}],
                                   'connections': [{'from': 'P1', 'to': 'sub'}, {'from': 'sub', 'to': 'gain'},
                                                   {'from': 'gain', 'to': 'J'}]}}
        model = {'blocks': [{'id': 'source', 'type': 'input_value', 'params': {'value': 7}},
                            experiment, {'id': 'view', 'type': 'result_display'}],
                 'connections': [{'from': 'source', 'to': 'exp'}, {'from': 'exp', 'to': 'view'}]}
        result = _execute_generic_dataflow(start_model(model))
        self.assertEqual(float(result['raw_results']['view']['displayed']['value']), 7)

    def test_subsystem_output_connects_directly_to_experiment_j(self):
        for gain in (None, 3, 'second_output'):
            with self.subTest(gain=gain):
                blocks = [{'id': 'In1', 'type': 'in1_terminal'}, {'id': 'Out1', 'type': 'out1_terminal'}]
                wires = [{'from': 'In1', 'to': 'Out1'}]
                if gain == 'second_output':
                    blocks.append({'id': 'split', 'type': 'splitter'})
                    wires = [{'from': 'In1', 'to': 'split'},
                             {'from': 'split', 'from_port': 1, 'to': 'Out1'}]
                elif gain is not None:
                    blocks.append({'id': 'g', 'type': 'gain', 'params': {'gain': gain}})
                    wires = [{'from': 'In1', 'to': 'g'}, {'from': 'g', 'to': 'Out1'}]
                subsystem = {'id': 'sub', 'type': 'subsystem', 'internal': {'blocks': blocks, 'connections': wires}}
                exp = {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
                       'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                               subsystem, {'id': 'J', 'type': 'experiment_result'}],
                                    'connections': [{'from': 'P1', 'to': 'sub'}, {'from': 'sub', 'to': 'J'}]}}
                model = {'blocks': [{'id': 'source', 'type': 'input_value', 'params': {'value': 7}},
                                    exp, {'id': 'view', 'type': 'result_display'}],
                         'connections': [{'from': 'source', 'to': 'exp'}, {'from': 'exp', 'to': 'view'}]}
                result = _execute_generic_dataflow(start_model(model))
                factor = gain if isinstance(gain, int) else 1
                self.assertEqual(float(result['raw_results']['view']['displayed']['value']), 7 * factor)
                self.assertNotIn('exp/J', result['results'])
