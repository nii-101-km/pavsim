"""Execute outer graphs with typed structures and automatic reference leases."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .engine import GraphRuntime
from .graph import GraphError, MissingInputError
from .nodes import BUILTIN_TYPES
from .blocks.catalog import lookup
from .structures import fork_structure, structure_references, validate_structure


@dataclass
class BlockOutcome:
    ports: dict
    artifacts: dict = field(default_factory=dict)
    result: dict | None = None


class TypedGraphEngine(GraphRuntime):
    def __init__(self, heap, registry=None, block_instances=None):
        super().__init__(registry)
        self.heap = heap
        self.block_instances = block_instances or {}

    def _release_refs(self, refs):
        for packet in refs.values():
            self.heap.release(packet)

    def _execute_typed(self, node, inputs, heap_scope):
        executor = self.block_instances.get(node.id) or lookup(node.type, self.registry)
        if executor is None:
            if node.type in BUILTIN_TYPES:
                raise GraphError(f'Unsupported typed built-in: {node.type}')
            raise GraphError(f'No executor registered for node type {node.type!r}.')
        native_call = getattr(executor, 'execute_block', None)
        if not callable(native_call):
            raise GraphError(f'Блок {node.id}: исполнитель не поддерживает интерфейс execute_block.')
        return native_call(node, inputs, heap_scope)

    def execute(self, graph):
        self._resolve_ports(graph)
        graph.validate()
        order = graph.topological_order()
        pending = {}  # connection identity -> one consumer's leased packet
        results = {}
        try:
            for node_id in order:
                node = graph.nodes[node_id]
                inputs = {}
                input_refs = {}
                incoming = graph.get_input_connections(node_id)
                for wire in incoming:
                    if id(wire) not in pending:
                        raise MissingInputError(f"Output {wire.from_port!r} of node {wire.from_node!r} has no value.")
                for wire in incoming:
                    packet = pending.pop(id(wire))
                    inputs[wire.to_port] = packet
                    input_refs.update(structure_references(packet))
                output_refs = {}
                heap_scope = self.heap.block_scope()
                try:
                    outputs = self._execute_typed(node, inputs, heap_scope)
                    artifacts = {}
                    result_override = None
                    if isinstance(outputs, BlockOutcome):
                        artifacts, result_override, outputs = outputs.artifacts, outputs.result, outputs.ports
                    if not isinstance(outputs, dict):
                        raise GraphError(f'Block {node_id} returned an invalid result.')
                    for packet in outputs.values():
                        validate_structure(packet)
                        output_refs.update(structure_references(packet))
                    for wire in graph.get_output_connections(node_id):
                        if wire.from_port not in outputs:
                            raise MissingInputError(f"Output {wire.from_port!r} of node {node_id!r} has no value.")
                        pending[id(wire)] = fork_structure(self.heap, outputs[wire.from_port])
                    # Never expose already-released handles as usable results.
                    if result_override is not None:
                        results[node_id] = result_override
                    else:
                        results[node_id] = {name: copy.deepcopy(packet) for name, packet in outputs.items()
                                            if not structure_references(packet)}
                    if artifacts:
                        results[node_id]['_artifacts'] = copy.deepcopy(artifacts)
                finally:
                    # Outputs may borrow an input reference; release each original lease once.
                    try:
                        self._release_refs({key: value for key, value in {**input_refs, **output_refs}.items()
                                            if key not in heap_scope.owned})
                    finally:
                        heap_scope.close()
            return results
        finally:
            remaining = {}
            for packet in pending.values():
                remaining.update(structure_references(packet))
            self._release_refs(remaining)
