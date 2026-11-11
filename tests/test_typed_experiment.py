import unittest
from engines.typed_experiment import TypedExperimentExecutor
from shell.graph import Node


def inner(input_connected=True, output_connected=True):
    return {'blocks': [
        {'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
        {'id': 'J', 'type': 'experiment_result', 'params': {}},
        {'id': 'constant', 'type': 'constant', 'params': {'value': 2}},
    ], 'connections': ([{'from': 'P1', 'from_port': 0, 'to': 'J', 'to_port': 0}]
                        if input_connected and output_connected else [])}


class TypedExperimentTests(unittest.TestCase):
    def setUp(self):
        self.executor = TypedExperimentExecutor('blocks')
        self.params = {'_inner_model': inner(), '_j_connected': True, 't_end': 1, 'h': .1, 'method': 'rk4'}

    def execute(self, inputs, params):
        return self.executor.execute_block(Node('exp', 'typed_experiment', params), inputs, None).ports

    def test_round_trip_input_and_output_structures(self):
        result = self.execute({'p1': {'type': 'float', 'value': '1.2'}}, self.params)
        self.assertEqual(result['J']['type'], 'float')
        self.assertAlmostEqual(float(result['J']['value']), 1.2)

    def test_parameter_flow_is_preserved_in_result(self):
        result = self.execute({'p1': {'type': 'float', 'value': '1.2', 'flow_id': '3.2'}}, self.params)
        self.assertEqual(result['J']['flow_id'], '3.2')

    def test_different_or_missing_flow_ids_are_rejected_before_simulation(self):
        from unittest.mock import patch
        first = {'type': 'float', 'value': '1', 'flow_id': '1'}
        for second in ({'type': 'float', 'value': '2', 'flow_id': '2'},
                       {'type': 'float', 'value': '2'}):
            with self.subTest(second=second), patch('engines.typed_experiment.NumericalEngineAdapter') as adapter:
                with self.assertRaisesRegex(ValueError, 'поток'):
                    self.execute({'p1': first, 'p2': second}, self.params)
                adapter.assert_not_called()

    def test_missing_either_side_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'p1'):
            self.execute({}, self.params)
        params = dict(self.params, _j_connected=False)
        with self.assertRaisesRegex(ValueError, 'J'):
            self.execute({'p1': {'type': 'float', 'value': '1'}}, params)

    def test_both_sides_unused_is_allowed(self):
        params = dict(self.params, _inner_model=inner(False, False), _j_connected=False)
        self.assertNotIn('J', self.execute({}, params))

    def test_unknown_port_is_not_silently_ignored(self):
        params = dict(self.params, _inner_model=inner(False, False), _j_connected=False)
        with self.assertRaisesRegex(ValueError, 'p4'):
            self.execute({'p4': {'type': 'float', 'value': '1'}}, params)

    def test_result_wire_from_missing_block_is_an_error(self):
        model = {'blocks': [{'id': 'J', 'type': 'experiment_result'}],
                 'connections': [{'from': 'missing', 'to': 'J'}]}
        with self.assertRaisesRegex(ValueError, 'J source'):
            self.execute({}, dict(self.params, _inner_model=model))
