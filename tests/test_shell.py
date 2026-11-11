"""Tests for the universal data-graph shell (no numerical engine required).

Verifies:
- Shell imports without xcos_mini
- Basic data chains
- Param assembler
- Cycle detection
- Unknown executor errors
- Round-trip serialization
- Port validation errors
- Multiple connections to same input
- Empty graph error
"""

import sys
import unittest
from shell.heap import SessionHeap
from shell.structures import read_float_structure, read_list_structure
from tests.starter_helpers import start_graph
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestShellImports(unittest.TestCase):
    """Verify shell works without xcos_mini."""

    def test_no_xcos_mini_import(self):
        """Shell must not import xcos_mini (source-level check, non-destructive)."""
        from pathlib import Path
        shell_dir = Path(__file__).resolve().parent.parent / "shell"
        for py_file in shell_dir.glob("*.py"):
            source = py_file.read_text("utf-8")
            # Check for import statements that reference xcos_mini
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("import xcos_mini") or stripped.startswith("from xcos_mini"):
                    self.fail(f"{py_file.name}: unconditional xcos_mini import: {stripped}")

    def test_shell_core_imports(self):
        """All shell core modules import cleanly."""
        from shell.graph import DataGraph, Node, Connection, Port
        from shell.executor import SessionBlock
        from shell.registry import ExecutorRegistry
        from shell.nodes import BUILTIN_TYPES, list_builtin_types
        from shell.engine import GraphRuntime
        self.assertIsNotNone(DataGraph)
        self.assertIsNotNone(SessionBlock)
        self.assertIsNotNone(ExecutorRegistry)
        self.assertIn('input_value', BUILTIN_TYPES)
        self.assertIn('param_assembler', BUILTIN_TYPES)
        self.assertIn('result_display', BUILTIN_TYPES)


class TestDataChain(unittest.TestCase):
    """Test basic data flow through the shell."""

    def setUp(self):
        from shell.signal_engine import SignalEngine
        from shell.registry import ExecutorRegistry
        self.engine = SignalEngine(SessionHeap(), ExecutorRegistry())

    def test_input_to_display(self):
        """input_value(42) -> result_display: result is 42."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 42}))
        g.add_node(Node('n2', 'result_display'))
        g.add_connection(Connection('n1', 'value', 'n2', 'value'))
        result = self.engine.execute(start_graph(g))
        self.assertEqual(read_float_structure(result['n2']['displayed']), 42)

    def test_input_float(self):
        """input_value(3.14) -> result_display: result is 3.14."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 3.14}))
        g.add_node(Node('n2', 'result_display'))
        g.add_connection(Connection('n1', 'value', 'n2', 'value'))
        result = self.engine.execute(start_graph(g))
        self.assertAlmostEqual(read_float_structure(result['n2']['displayed']), 3.14)

    def test_param_assembler(self):
        """Two inputs -> param_assembler -> result_display."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('a1', 'input_value', params={'value': 1.5}))
        g.add_node(Node('a2', 'input_value', params={'value': 2.5}))
        g.add_node(Node('a3', 'param_assembler'))
        g.add_node(Node('a4', 'result_display'))
        g.add_connection(Connection('a1', 'value', 'a3', 'a'))
        g.add_connection(Connection('a2', 'value', 'a3', 'b'))
        g.add_connection(Connection('a3', 'params', 'a4', 'value'))
        result = self.engine.execute(start_graph(g))
        self.assertEqual([read_float_structure(p) for p in read_list_structure(result['a3']['params'])[:2]], [1.5, 2.5])
        self.assertEqual([read_float_structure(p) for p in result['a4']['displayed'][:2]], [1.5, 2.5])

    def test_fanout(self):
        """One input feeds two displays."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('src', 'input_value', params={'value': 99}))
        g.add_node(Node('d1', 'result_display'))
        g.add_node(Node('d2', 'result_display'))
        g.add_connection(Connection('src', 'value', 'd1', 'value'))
        g.add_connection(Connection('src', 'value', 'd2', 'value'))
        result = self.engine.execute(start_graph(g))
        self.assertEqual(read_float_structure(result['d1']['displayed']), 99)
        self.assertEqual(read_float_structure(result['d2']['displayed']), 99)


class TestGraphErrors(unittest.TestCase):
    """Test error conditions in the data graph."""

    def setUp(self):
        from shell.typed_engine import TypedGraphEngine
        from shell.registry import ExecutorRegistry
        self.engine = TypedGraphEngine(SessionHeap(), ExecutorRegistry())

    def test_empty_graph(self):
        """Empty graph raises GraphError."""
        from shell.graph import DataGraph, GraphError
        g = DataGraph()
        with self.assertRaises(GraphError):
            self.engine.execute(g)

    def test_cycle_detection(self):
        """Cycle in graph raises CycleError."""
        from shell.graph import DataGraph, Node, Connection, CycleError
        g = DataGraph()
        g.add_node(Node('x1', 'param_assembler'))
        g.add_node(Node('x2', 'param_assembler'))
        g.add_connection(Connection('x1', 'params', 'x2', 'a'))
        g.add_connection(Connection('x2', 'params', 'x1', 'a'))
        with self.assertRaises(CycleError):
            self.engine.execute(g)

    def test_unknown_node_type(self):
        """Unknown node type raises GraphError."""
        from shell.graph import DataGraph, Node, GraphError
        g = DataGraph()
        g.add_node(Node('u1', 'nonexistent_type'))
        with self.assertRaises(GraphError) as ctx:
            self.engine.execute(g)
        self.assertIn('nonexistent_type', str(ctx.exception))

    def test_invalid_output_port(self):
        """Connection from non-existent output port raises PortError."""
        from shell.graph import DataGraph, Node, Connection, PortError
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 1}))
        g.add_node(Node('n2', 'result_display'))
        g.add_connection(Connection('n1', 'bad_port', 'n2', 'value'))
        with self.assertRaises(PortError):
            self.engine.execute(g)

    def test_invalid_input_port(self):
        """Connection to non-existent input port raises PortError."""
        from shell.graph import DataGraph, Node, Connection, PortError
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 1}))
        g.add_node(Node('n2', 'result_display'))
        g.add_connection(Connection('n1', 'value', 'n2', 'bad_port'))
        with self.assertRaises(PortError):
            self.engine.execute(g)

    def test_multiple_sources_one_input(self):
        """Two connections to same input port raises PortError."""
        from shell.graph import DataGraph, Node, Connection, PortError
        g = DataGraph()
        g.add_node(Node('s1', 'input_value', params={'value': 1}))
        g.add_node(Node('s2', 'input_value', params={'value': 2}))
        g.add_node(Node('d1', 'result_display'))
        g.add_connection(Connection('s1', 'value', 'd1', 'value'))
        g.add_connection(Connection('s2', 'value', 'd1', 'value'))
        with self.assertRaises(PortError):
            self.engine.execute(g)

    def test_connection_to_missing_node(self):
        """Connection referencing non-existent node raises GraphError."""
        from shell.graph import DataGraph, Node, Connection, GraphError
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 1}))
        g.add_connection(Connection('n1', 'value', 'ghost', 'value'))
        with self.assertRaises(GraphError):
            self.engine.execute(g)


class TestSerialization(unittest.TestCase):
    """Test round-trip serialization of graphs."""

    def setUp(self):
        from shell.signal_engine import SignalEngine
        from shell.registry import ExecutorRegistry
        self.engine = SignalEngine(SessionHeap(), ExecutorRegistry())

    def test_round_trip_simple(self):
        """Graph serializes and deserializes correctly."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 42}, x=100, y=200))
        g.add_node(Node('n2', 'result_display', x=300, y=200))
        g.add_connection(Connection('n1', 'value', 'n2', 'value'))

        d = g.to_dict()
        g2 = DataGraph.from_dict(d)

        self.assertEqual(len(g2.nodes), 2)
        self.assertEqual(len(g2.connections), 1)
        self.assertEqual(g2.nodes['n1'].params['value'], 42)
        self.assertEqual(g2.nodes['n1'].x, 100)

        result = self.engine.execute(start_graph(g2))
        self.assertEqual(read_float_structure(result['n2']['displayed']), 42)

    def test_round_trip_assembler(self):
        """Assembler graph round-trips and executes."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('a1', 'input_value', params={'value': 10}))
        g.add_node(Node('a2', 'input_value', params={'value': 20}))
        g.add_node(Node('a3', 'param_assembler'))
        g.add_node(Node('a4', 'result_display'))
        g.add_connection(Connection('a1', 'value', 'a3', 'a'))
        g.add_connection(Connection('a2', 'value', 'a3', 'b'))
        g.add_connection(Connection('a3', 'params', 'a4', 'value'))

        d = g.to_dict()
        g2 = DataGraph.from_dict(d)
        result = self.engine.execute(start_graph(g2))
        self.assertEqual([read_float_structure(p) for p in read_list_structure(result['a3']['params'])[:2]], [10, 20])

    def test_unknown_node_preserved(self):
        """Unknown node types are preserved in round-trip (not deleted)."""
        from shell.graph import DataGraph, Node, Connection
        g = DataGraph()
        g.add_node(Node('n1', 'input_value', params={'value': 1}))
        g.add_node(Node('n2', 'custom_engine_block', params={'foo': 'bar'}))
        g.add_connection(Connection('n1', 'value', 'n2', 'in'))

        d = g.to_dict()
        g2 = DataGraph.from_dict(d)

        # Node is preserved even though we can't execute it
        self.assertIn('n2', g2.nodes)
        self.assertEqual(g2.nodes['n2'].type, 'custom_engine_block')
        self.assertEqual(g2.nodes['n2'].params, {'foo': 'bar'})


class TestRegistry(unittest.TestCase):
    """Test executor registry."""

    def test_empty_registry(self):
        """Empty registry has no executors."""
        from shell.registry import ExecutorRegistry
        reg = ExecutorRegistry()
        self.assertEqual(reg.names(), [])
        self.assertIsNone(reg.get('anything'))
        self.assertNotIn('anything', reg)

    def test_register_and_get(self):
        """Register an executor and retrieve it."""
        from shell.registry import ExecutorRegistry

        class MyExec:
            @property
            def name(self):
                return "my_exec"
            def execute_block(self, node, inputs, heap):
                return {}

        reg = ExecutorRegistry()
        ex = MyExec()
        reg.register(ex)
        self.assertIn('my_exec', reg)
        self.assertIs(reg.get('my_exec'), ex)
        self.assertEqual(reg.names(), ['my_exec'])


if __name__ == '__main__':
    unittest.main()
