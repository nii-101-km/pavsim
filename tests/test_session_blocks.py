import unittest

from shell.graph import DataGraph, Node
from shell.heap import SessionHeap
from shell.registry import ExecutorRegistry
from shell.session_blocks import SessionBlocks
from shell.typed_engine import TypedGraphEngine
from shell.structures import float_structure


class Instance:
    def __init__(self, name, events, fail=False):
        self.name, self.events, self.fail = name, events, fail

    def execute_block(self, node, inputs, heap):

        params = node.params
        self.events.append(('execute', self.name))
        return {'out': float_structure(5)}

    def request_stop(self):
        self.events.append(('stop', self.name))
        if self.fail:
            raise RuntimeError('stop failed')

    def close_session(self):
        self.events.append(('close', self.name))


class Factory:
    name = 'custom'
    def __init__(self, events):
        self.events = events
    def create_session_block(self, block_id, params):
        return Instance(block_id, self.events, params.get('fail', False))
    def execute_block(self, node, inputs, heap):
        params = node.params
        raise AssertionError('Must use the per-session instance')


class SessionBlockTests(unittest.TestCase):
    def test_all_instances_receive_stop_even_if_one_hook_fails(self):
        events = []
        registry = ExecutorRegistry(); registry.register(Factory(events))
        graph = DataGraph(); graph.add_node(Node('one', 'custom', {'fail': True})); graph.add_node(Node('two', 'custom'))
        lifecycle = SessionBlocks(); instances = lifecycle.prepare(graph, registry)
        self.assertEqual(len(lifecycle.request_stop()), 1)
        self.assertEqual(lifecycle.close(), [])
        self.assertEqual(events, [('stop', 'one'), ('stop', 'two'), ('close', 'one'), ('close', 'two')])
        self.assertEqual(lifecycle.close(), [])
        self.assertEqual(set(instances), {'one', 'two'})

    def test_execution_uses_same_instance_that_is_closed(self):
        events = []
        registry = ExecutorRegistry(); registry.register(Factory(events))
        graph = DataGraph(); graph.add_node(Node('one', 'custom'))
        lifecycle = SessionBlocks(); instances = lifecycle.prepare(graph, registry)
        TypedGraphEngine(SessionHeap(), registry, instances).execute(graph)
        lifecycle.request_stop(); lifecycle.close()
        self.assertEqual(events, [('execute', 'one'), ('stop', 'one'), ('close', 'one')])

    def test_partial_preparation_is_cleaned_up(self):
        events = []
        class Broken(Factory):
            def create_session_block(self, block_id, params):
                if block_id == 'two':
                    raise ValueError('failed to create')
                return super().create_session_block(block_id, params)
        registry = ExecutorRegistry(); registry.register(Broken(events))
        graph = DataGraph(); graph.add_node(Node('one', 'custom')); graph.add_node(Node('two', 'custom'))
        lifecycle = SessionBlocks()
        with self.assertRaisesRegex(ValueError, 'failed to create'):
            lifecycle.prepare(graph, registry)
        self.assertEqual(events, [('stop', 'one'), ('close', 'one')])
        self.assertEqual(lifecycle.close(), [])
