from ..structures import list_structure
from .input_slots import ConnectedInputs


class Assembler(ConnectedInputs):
    node_description = 'Collects named input values into a parameter dictionary.'
    node_inputs = [('a', 'structure'), ('b', 'structure'), ('c', 'structure')]
    node_outputs = [('params', 'dict')]
    default_params = {}
    _palette = {'name': 'param_assembler',
     'class': 'ParamAssembler',
     'category': 'Shell',
     'state_kind': 'none',
     'description': 'Collects named input values into a parameter dictionary.',
     'parameter_labels': {},
     'parameter_choices': {},
     'display_name': 'Param Assembler',
     'input_labels': ['a', 'b', 'c'],
     'output_labels': ['params']}

    @classmethod
    def descriptor(cls):
        import copy
        data = copy.deepcopy(cls._palette)
        data.update(n_inputs=len(cls.node_inputs), n_outputs=len(cls.node_outputs), parameters=copy.deepcopy(cls.default_params))
        return data

    def execute_block(self, node, inputs, heap):
        packet = list_structure([inputs.get('a'), inputs.get('b'), inputs.get('c')])
        flow_ids = [value.get('flow_id') for value in inputs.values()]
        if flow_ids and all(isinstance(flow_id, str) and flow_id for flow_id in flow_ids) and len(set(flow_ids)) == 1:
            packet['flow_id'] = flow_ids[0]
        return {'params': packet}
