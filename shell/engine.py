"""Common graph port preparation for structured-signal executors."""
from .nodes import BUILTIN_TYPES
from .registry import ExecutorRegistry


class GraphRuntime:
    def __init__(self, registry=None):
        self.registry = registry or ExecutorRegistry()

    def _resolve_ports(self, graph):
        for node in graph.nodes.values():
            if node.type in BUILTIN_TYPES:
                if not node.inputs and not node.outputs:
                    definition = BUILTIN_TYPES[node.type]
                    node.inputs = list(definition.inputs)
                    node.outputs = list(definition.outputs)
            else:
                node._permissive = True
