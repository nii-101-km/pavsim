import unittest
from shell.graph import DataGraph, Node, Connection, GraphError
from shell.heap import SessionHeap
from shell.registry import ExecutorRegistry
from shell.typed_engine import TypedGraphEngine


class Source:
    name = 'source'
    def execute_block(self, node, inputs, heap):
        return {'out': heap.put({'rows': [1, 2, 3]})}


class Failing:
    name = 'failing'
    def execute_block(self, node, inputs, heap):
        self.asserted = heap.read(inputs['value'])
        raise ValueError('block failure')


class Forward:
    name = 'forward'
    def execute_block(self, node, inputs, heap):
        heap.read(inputs['value'])
        return {'out': inputs['value']}


class AllocatingFailure:
    name = 'allocating_failure'
    def execute_block(self, node, inputs, heap):
        heap.put({'unfinished': True})
        raise ValueError('failed after allocation')


class TypedEngineTests(unittest.TestCase):
    def test_obsolete_executor_interface_is_rejected(self):
        class Legacy:
            name = 'legacy'
            def execute(self, inputs, params):
                raise AssertionError('Старый интерфейс не должен вызываться')
        graph = DataGraph(); graph.add_node(Node('old', 'legacy'))
        registry = ExecutorRegistry(); registry.register(Legacy())
        with self.assertRaisesRegex(GraphError, 'интерфейс execute_block'):
            TypedGraphEngine(SessionHeap(), registry).execute(graph)

    def test_pack_and_unpack_preserve_flow_without_guessing_mixed_inputs(self):
        from shell.structures import read_list_structure
        engine = TypedGraphEngine(SessionHeap())
        block = Node('pack', 'param_assembler')
        a = {'type': 'float', 'value': '1', 'flow_id': '1.1'}
        b = {'type': 'float', 'value': '2', 'flow_id': '1.1'}
        packet = engine._execute_typed(block, {'a': a, 'b': b}, None)['params']
        self.assertEqual(packet['flow_id'], '1.1')
        unpacked = engine._execute_typed(Node('split', 'param_splitter'), {'value': packet}, None)
        self.assertEqual(unpacked['a']['flow_id'], '1.1')
        self.assertEqual(unpacked['b']['flow_id'], '1.1')
        different = dict(b, flow_id='2.1')
        mixed = engine._execute_typed(block, {'a': a, 'b': different}, None)['params']
        self.assertNotIn('flow_id', mixed)
        self.assertEqual([item['flow_id'] for item in read_list_structure(mixed) if item], ['1.1', '2.1'])

    def build(self, sink_types):
        graph = DataGraph()
        graph.add_node(Node('source', 'source'))
        for i, kind in enumerate(sink_types):
            graph.add_node(Node(str(i), kind))
            graph.add_connection(Connection('source', 'out', str(i), 'value'))
        return graph

    def test_fanout_uses_single_object_and_visualizers_copy(self):
        heap = SessionHeap()
        registry = ExecutorRegistry(); registry.register(Source())
        output = TypedGraphEngine(heap, registry).execute(self.build(['result_display'] * 3))
        self.assertEqual([output[str(i)]['displayed'] for i in range(3)], [{'rows': [1, 2, 3]}] * 3)
        self.assertIsNot(output['0']['displayed'], output['1']['displayed'])
        self.assertEqual(len(heap._objects), 0)

    def test_failure_releases_failed_and_unvisited_consumers(self):
        heap = SessionHeap()
        registry = ExecutorRegistry(); registry.register(Source()); registry.register(Failing())
        with self.assertRaisesRegex(ValueError, 'block failure'):
            TypedGraphEngine(heap, registry).execute(self.build(['failing', 'result_display']))
        self.assertEqual(len(heap._objects), 0)

    def test_forwarded_reference_survives_input_release(self):
        heap = SessionHeap()
        registry = ExecutorRegistry(); registry.register(Source()); registry.register(Forward())
        graph = DataGraph()
        for name, kind in [('s', 'source'), ('f', 'forward'), ('d', 'result_display')]:
            graph.add_node(Node(name, kind))
        graph.add_connection(Connection('s', 'out', 'f', 'value'))
        graph.add_connection(Connection('f', 'out', 'd', 'value'))
        result = TypedGraphEngine(heap, registry).execute(graph)
        self.assertEqual(result['d']['displayed'], {'rows': [1, 2, 3]})
        self.assertEqual(len(heap._objects), 0)

    def test_failed_block_does_not_leak_new_allocations(self):
        heap = SessionHeap()
        registry = ExecutorRegistry(); registry.register(AllocatingFailure())
        graph = DataGraph(); graph.add_node(Node('failure', 'allocating_failure'))
        with self.assertRaisesRegex(ValueError, 'failed after allocation'):
            TypedGraphEngine(heap, registry).execute(graph)
        self.assertEqual(len(heap._objects), 0)
