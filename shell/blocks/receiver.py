"""Per-block signal receivers and ownership of incoming references."""
from .input_slots import InputSlots
from ..graph import GraphError
from ..structures import structure_references, validate_structure
import copy


class BufferedBlock:
    """A block whose chosen input policy may retain signals until it is ready."""
    def __init__(self, node, ports, input_factory, tracker, heap, deliver,
                 mark_invoked, release, execute, record_result, count_invocation):
        self.node = node
        self.inputs = (input_factory or InputSlots)(ports)
        self.tracker = tracker
        self.heap = heap
        self.deliver = deliver
        self.mark_invoked = mark_invoked
        self.release = release
        self.execute_typed = execute
        self.record_result = record_result
        self.count_invocation = count_invocation

    active = False
    requires_signal = True

    def on_signal(self, port, packet):
        node_id = self.node.id
        try:
            ready_inputs = self.inputs.receive(port, packet)
        except BaseException as exc:
            self.release(structure_references(packet))
            if isinstance(exc, ValueError):
                raise GraphError(f'Блок {node_id}: {exc}') from exc
            raise
        try:
            self.tracker.change(node_id, packet.get('flow_id'), 'waiting', 1, port)
        except BaseException:
            if ready_inputs is not None:
                refs = {}
                for value in ready_inputs.values():
                    refs.update(structure_references(value))
                self.release(refs)
            raise
        if ready_inputs is not None:
            self._run(ready_inputs)

    def start(self):
        self._run({})

    def _run(self, inputs):
        from ..typed_engine import BlockOutcome
        node_id = self.node.id
        self.mark_invoked(node_id)
        input_refs = {}
        for packet in inputs.values():
            input_refs.update(structure_references(packet))
        output_refs = {}
        scope = self.heap.block_scope()
        working_flows = set()
        try:
            self.count_invocation()
            for port, packet in inputs.items():
                self.tracker.change(node_id, packet.get('flow_id'), 'waiting', -1, port)
            for packet in inputs.values():
                flow_id = packet.get('flow_id')
                if isinstance(flow_id, str) and flow_id not in working_flows:
                    working_flows.add(flow_id)
                    self.tracker.change(node_id, flow_id, 'working', 1)
            outputs = self.execute_typed(self.node, inputs, scope)
            artifacts, result_override = {}, None
            if isinstance(outputs, BlockOutcome):
                artifacts, result_override, outputs = outputs.artifacts, outputs.result, outputs.ports
            if not isinstance(outputs, dict):
                raise GraphError(f'Block {node_id} returned an invalid result.')
            for packet in outputs.values():
                validate_structure(packet)
                output_refs.update(structure_references(packet))
            self.deliver(node_id, outputs)
            result = (result_override if result_override is not None else
                      {key: copy.deepcopy(packet) for key, packet in outputs.items()
                       if not structure_references(packet)})
            if artifacts:
                result['_artifacts'] = copy.deepcopy(artifacts)
            self.record_result(node_id, result)
        finally:
            try:
                for flow_id in working_flows:
                    self.tracker.change(node_id, flow_id, 'working', -1)
            finally:
                try:
                    refs = {**input_refs, **output_refs}
                    self.release({key: value for key, value in refs.items() if key not in scope.owned})
                finally:
                    scope.close()

    def waiting_for(self):
        return self.inputs.waiting_for()

    def drain(self):
        return self.inputs.drain()

    def close(self):
        refs = {}
        for packet in self.drain():
            refs.update(structure_references(packet))
        self.release(refs)

    def check_complete(self):
        pass


class DirectBlock:
    """A stateful block that processes each connected input independently."""
    def __init__(self, node, ports, handler, tracker, deliver, mark_invoked,
                 release, record_result, count_invocation):
        self.node = node
        self.handler = handler
        self.tracker = tracker
        self.deliver = deliver
        self.mark_invoked = mark_invoked
        self.release = release
        self.record_result = record_result
        self.count_invocation = count_invocation
        if not set(ports).issubset(handler.independent_ports):
            raise GraphError(f'Блок {node.id}: неподдерживаемые входы.')

    def on_signal(self, port, packet):
        node_id = self.node.id
        try:
            self.count_invocation()
            self.tracker.change(node_id, packet.get('flow_id'), 'working', 1)
            try:
                emitted = self.handler.on_signal(port, packet)
            finally:
                self.tracker.change(node_id, packet.get('flow_id'), 'working', -1)
            self.mark_invoked(node_id)
            if self.handler.result is not None:
                self.record_result(node_id, self.handler.result)
            if emitted:
                self.deliver(node_id, emitted)
        finally:
            self.release(structure_references(packet))

    def waiting_for(self):
        return ()

    @property
    def active(self):
        return self.handler.active

    @property
    def requires_signal(self):
        return getattr(self.handler, 'requires_signal', True)

    def check_complete(self):
        self.handler.check_complete()

    def close(self):
        self.handler.close()


def make_block_receiver(node, ports, handler, input_factory, tracker, heap,
                        deliver, mark_invoked, release, execute, record_result,
                        count_invocation):
    ports = tuple(ports)
    if handler is not None:
        return DirectBlock(node, ports, handler, tracker, deliver, mark_invoked,
                           release, record_result, count_invocation)
    return BufferedBlock(node, ports, input_factory, tracker, heap, deliver,
                         mark_invoked, release, execute, record_result, count_invocation)
