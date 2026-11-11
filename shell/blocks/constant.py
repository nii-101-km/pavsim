import re
from ..structures import float_structure
from .input_slots import ConnectedInputs


class Constant(ConnectedInputs):
    node_description = 'Outputs a constant in the flow that starts it.'
    node_inputs = [('start', 'structure')]
    node_outputs = [('value', 'number')]
    default_params = {'value': 0.0}
    _palette = {'name': 'input_value',
     'class': 'InputValue',
     'category': 'Shell',
     'state_kind': 'none',
     'description': 'Outputs a constant value in the flow that starts it.',
     'parameter_labels': {'value': 'Value'},
     'parameter_choices': {},
     'display_name': 'Input Value',
     'input_labels': ['start'],
     'output_labels': ['value']}

    @classmethod
    def descriptor(cls):
        import copy
        data = copy.deepcopy(cls._palette)
        data.update(n_inputs=len(cls.node_inputs), n_outputs=len(cls.node_outputs), parameters=copy.deepcopy(cls.default_params))
        return data

    def execute_block(self, node, inputs, heap):
        signal = inputs.get('start')
        if not isinstance(signal, dict) or signal.get('type') != 'event' or signal.get('value') != 'start':
            raise ValueError(f'Константа {node.id}: подключите сигнал запуска.')
        flow_id = signal.get('flow_id')
        if not isinstance(flow_id, str) or not re.fullmatch(r'[1-9][0-9]*(?:\.[1-9][0-9]*)*', flow_id):
            raise ValueError(f'Константа {node.id}: у сигнала запуска нет корректного номера потока.')
        return {'value': dict(float_structure(node.params.get('value', self.default_params['value'])), flow_id=flow_id)}
