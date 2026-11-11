import copy
from ..graph import MissingInputError
from ..structures import read_list_structure, validate_structure
from .input_slots import ConnectedInputs


class Display(ConnectedInputs):
    node_description = 'Displays the received value as a result (sink node).'
    node_inputs = [('value', 'any')]
    node_outputs = []
    default_params = {}
    _palette = {'name': 'result_display',
     'class': 'ResultDisplay',
     'category': 'Shell',
     'state_kind': 'none',
     'description': 'Displays the received value as a result (sink node).',
     'parameter_labels': {},
     'parameter_choices': {},
     'display_name': 'Result Display',
     'input_labels': ['value'],
     'output_labels': []}

    @classmethod
    def descriptor(cls):
        import copy
        data = copy.deepcopy(cls._palette)
        data.update(n_inputs=len(cls.node_inputs), n_outputs=len(cls.node_outputs), parameters=copy.deepcopy(cls.default_params))
        return data

    def _snapshot(self, packet, heap):
        validate_structure(packet)
        if packet['type'] == 'object_ref':
            return copy.deepcopy(heap.read(packet))
        if packet['type'] == 'list':
            return [self._snapshot(item, heap) if item is not None else None for item in read_list_structure(packet)]
        return copy.deepcopy(packet)

    def execute_block(self, node, inputs, heap):
        if 'value' not in inputs:
            raise MissingInputError('Result Display input is not connected.')
        from ..typed_engine import BlockOutcome
        return BlockOutcome({}, result={'displayed': self._snapshot(inputs['value'], heap)})
