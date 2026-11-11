from ..graph import MissingInputError
from ..structures import read_list_structure
from .input_slots import ConnectedInputs


class Splitter(ConnectedInputs):
    node_description = 'Extract structures from a list by position.'
    node_inputs = [('value', 'structure')]
    node_outputs = [('a', 'structure'), ('b', 'structure'), ('c', 'structure')]
    default_params = {}
    _palette = {'name': 'param_splitter',
     'class': 'ParamSplitter',
     'category': 'Shell',
     'state_kind': 'none',
     'description': 'Extract structures from a list by position.',
     'parameter_labels': {},
     'parameter_choices': {},
     'display_name': 'List splitter',
     'input_labels': ['value'],
     'output_labels': ['1', '2', '3']}

    @classmethod
    def descriptor(cls):
        import copy
        data = copy.deepcopy(cls._palette)
        data.update(n_inputs=len(cls.node_inputs), n_outputs=len(cls.node_outputs), parameters=copy.deepcopy(cls.default_params))
        return data

    def execute_block(self, node, inputs, heap):
        if 'value' not in inputs:
            raise MissingInputError('List splitter input is not connected.')
        items = read_list_structure(inputs['value'])
        output = {}
        for i, key in enumerate(('a', 'b', 'c')):
            if i < len(items) and items[i] is not None:
                output[key] = dict(items[i])
                if 'flow_id' not in output[key] and 'flow_id' in inputs['value']:
                    output[key]['flow_id'] = inputs['value']['flow_id']
        return output
