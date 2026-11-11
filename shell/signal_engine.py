"""Repeatable signal delivery for the outer structured-data graph."""
from .graph import GraphError, Port
from .cancellation import SessionCancelled
from .blocks.receiver import make_block_receiver
from .blocks.catalog import BLOCK_TYPES, lookup, prepare_handlers
from .flow_tracker import FlowTracker
from .structures import fork_structure, structure_references, validate_structure
from .typed_engine import TypedGraphEngine


class SignalEngine(TypedGraphEngine):
    """Run blocks whenever all their connected inputs have a fresh signal.

    ``initial_outputs`` injects a sequence of outputs from already-started
    controllers. Its packets are borrowed: the caller retains their leases.
    A controller must use the same graph delivery path for subsequent signals.
    """

    def __init__(self, heap, registry=None, block_services=None, block_instances=None):
        super().__init__(heap, registry, block_instances)
        self.block_services = block_services or {}

    def execute(self, graph, *, initial_outputs=(), max_invocations=100000, on_plot=None, cancel_event=None, on_flow=None, on_output=None):
        self._resolve_ports(graph)
        for node in graph.nodes.values():
            block_type = lookup(node.type, self.registry)
            ports = getattr(block_type, 'ports', None)
            if ports:
                node.inputs = [Port(name, 'input') for name in ports[0]]
                node.outputs = [Port(name, 'output') for name in ports[1]]
                node._permissive = False
        graph.validate(allow_cycles=True)
        tasks = []
        results = {}
        invocations = 0
        invoked = set()
        tracker = FlowTracker(on_flow)

        for executor in BLOCK_TYPES.values():
            check_graph = getattr(executor, 'validate_graph', None)
            if check_graph:
                check_graph(graph)

        handlers = prepare_handlers(graph, self.registry, results, tracker, on_plot, on_output,
                                    self.block_services, self.block_instances, cancel_event)
        def deliver(node_id, outputs):
            if cancel_event is not None and cancel_event.is_set():
                raise SessionCancelled('Сессия остановлена.')
            for packet in outputs.values():
                validate_structure(packet)
            wires = [wire for wire in graph.get_output_connections(node_id) if wire.from_port in outputs]
            # LIFO work stack: earlier wires are visited first, including their
            # complete descendants. Each task owns its own heap references.
            for wire in reversed(wires):
                packet = fork_structure(self.heap, outputs[wire.from_port])
                tasks.append(('wire', wire, packet))

        def count_invocation():
            nonlocal invocations
            invocations += 1
            if invocations > max_invocations:
                raise GraphError('Превышен предел запусков блоков: проверьте схему на бесконечный цикл.')

        receivers = {}
        for node_id, node in graph.nodes.items():
            handler = handlers.get(node_id)
            policy = handler or self.block_instances.get(node_id) or lookup(node.type, self.registry)
            receivers[node_id] = make_block_receiver(
                node, (wire.to_port for wire in graph.get_input_connections(node_id)), handler,
                getattr(policy, 'create_input_state', None), tracker, self.heap, deliver,
                invoked.add, self._release_refs, self._execute_typed,
                results.__setitem__, count_invocation)

        try:
            initial = list(initial_outputs)
            injected = set()
            for node_id, _ in initial:
                if node_id not in graph.nodes:
                    raise GraphError(f'Block {node_id!r} does not exist.')
                injected.add(node_id)
            sources = [node_id for node_id in graph.nodes
                       if node_id not in handlers
                       and not graph.get_input_connections(node_id) and node_id not in injected]
            for node_id in reversed(sources):
                tasks.append(('source', node_id, None))
            for node_id, outputs in reversed(initial):
                tasks.append(('emit', node_id, outputs))
            while tasks:
                if cancel_event is not None and cancel_event.is_set():
                    raise SessionCancelled('Сессия остановлена.')
                kind, target, packet = tasks.pop()
                if kind == 'source':
                    receivers[target].start()
                    continue
                if kind == 'emit':
                    deliver(target, packet)
                    continue
                wire = target
                receivers[wire.to_node].on_signal(wire.to_port, packet)
            waiting = [(node_id, receiver.waiting_for()) for node_id, receiver in receivers.items() if receiver.waiting_for()]
            if waiting:
                detail = '; '.join(f'{node}: {", ".join(ports)}' for node, ports in waiting)
                raise GraphError(f'Расчёт остановился: не поступили сигналы на входы {detail}.')
            inactive = [node_id for node_id in graph.nodes
                        if node_id not in invoked and not receivers[node_id].active
                        and receivers[node_id].requires_signal
                        and graph.get_input_connections(node_id)]
            if inactive:
                raise GraphError('Расчёт остановился: нет сигналов для блоков: ' + ', '.join(inactive))
            for block in receivers.values():
                block.check_complete()
            return results
        finally:
            try:
                tracker.clear()
            finally:
                errors = []
                try:
                    for block in receivers.values():
                        try:
                            block.close()
                        except Exception as exc:
                            errors.append(str(exc))
                finally:
                    refs = {}
                    for kind, _, packet in tasks:
                        if kind == 'wire':
                            refs.update(structure_references(packet))
                    self._release_refs(refs)
                if errors:
                    raise RuntimeError('Ошибка остановки блоков: ' + '; '.join(errors))
