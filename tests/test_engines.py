"""Tests for the structured block interface and numerical adapter."""
import math
import unittest

from engines.numerical import NumericalEngineAdapter
from engines.test_engine import TestExecutor
from shell.graph import Connection, DataGraph, GraphError, Node
from shell.heap import SessionHeap
from shell.registry import ExecutorRegistry
from shell.signal_engine import SignalEngine
from shell.structures import read_float_structure
from tests.starter_helpers import start_graph


class TestStructuredExecutor(unittest.TestCase):
    def setUp(self):
        registry = ExecutorRegistry(); registry.register(TestExecutor())
        self.engine = SignalEngine(SessionHeap(), registry)

    def test_doubler_scalar(self):
        graph = DataGraph()
        for node, kind, params in [('src', 'input_value', {'value': 5}),
                                   ('dbl', 'test_doubler', {}), ('out', 'result_display', {})]:
            graph.add_node(Node(node, kind, params))
        graph.add_connection(Connection('src', 'value', 'dbl', 'a'))
        graph.add_connection(Connection('dbl', 'result', 'out', 'value'))
        result = self.engine.execute(start_graph(graph))
        self.assertAlmostEqual(read_float_structure(result['out']['displayed']), 10)

    def test_doubler_list(self):
        graph = DataGraph()
        for node, kind, params in [('a', 'input_value', {'value': 3}), ('b', 'input_value', {'value': 4}),
                                   ('asm', 'param_assembler', {}), ('dbl', 'test_doubler', {})]:
            graph.add_node(Node(node, kind, params))
        graph.add_connection(Connection('a', 'value', 'asm', 'a'))
        graph.add_connection(Connection('b', 'value', 'asm', 'b'))
        graph.add_connection(Connection('asm', 'params', 'dbl', 'a'))
        result = self.engine.execute(start_graph(graph))
        self.assertAlmostEqual(read_float_structure(result['dbl']['result']), 14)


class TestNumericalAdapter(unittest.TestCase):
    @staticmethod
    def model(tau):
        return {'blocks': [{'id': 'c', 'type': 'constant', 'params': {'value': 1}},
                           {'id': 'fo', 'type': 'first_order', 'params': {'tau': tau, 'gain': 1}}],
                'connections': [{'from': 'c', 'to': 'fo'}]}

    def test_first_order_step_response(self):
        data = NumericalEngineAdapter().simulate(self.model(1), 1, .01, 'rk4')['results']['fo']
        self.assertAlmostEqual(data['y'][-1], 1 - math.exp(-1), places=3)

    def test_first_order_parameter(self):
        data = NumericalEngineAdapter().simulate(self.model(2), .5, .01, 'rk4')['results']['fo']
        self.assertAlmostEqual(data['y'][-1], 1 - math.exp(-.25), places=3)

    def test_series_output(self):
        data = NumericalEngineAdapter().simulate(self.model(1), 1, .1, 'rk4')['results']['fo']
        self.assertGreater(len(data['t']), 5)
        self.assertAlmostEqual(data['t'][0], 0)


class TestShellWithoutExecutor(unittest.TestCase):
    def test_builtin_only(self):
        graph = DataGraph(); graph.add_node(Node('source', 'input_value', {'value': 7}))
        graph.add_node(Node('display', 'result_display'))
        graph.add_connection(Connection('source', 'value', 'display', 'value'))
        result = SignalEngine(SessionHeap()).execute(start_graph(graph))
        self.assertEqual(read_float_structure(result['display']['displayed']), 7)

    def test_unknown_executor_is_reported(self):
        graph = DataGraph(); graph.add_node(Node('unknown', 'some_executor_node'))
        with self.assertRaisesRegex(GraphError, 'some_executor_node'):
            SignalEngine(SessionHeap()).execute(graph)
