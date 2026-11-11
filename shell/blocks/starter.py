import re
from ..graph import GraphError
from .input_slots import ConnectedInputs


class Starter(ConnectedInputs):
    node_description = 'Starts a data flow.'
    node_inputs = []
    node_outputs = [('start', 'structure')]
    default_params = {'flow_id': '1'}
    _palette = {'name': 'starter',
     'class': 'Starter',
     'category': 'Shell',
     'state_kind': 'none',
     'description': 'Starts a numbered data flow.',
     'parameter_labels': {'flow_id': 'Flow number'},
     'parameter_choices': {},
     'display_name': 'Starter',
     'input_labels': [],
     'output_labels': ['start']}

    @classmethod
    def descriptor(cls):
        import copy
        data = copy.deepcopy(cls._palette)
        data.update(n_inputs=len(cls.node_inputs), n_outputs=len(cls.node_outputs), parameters=copy.deepcopy(cls.default_params))
        return data

    @staticmethod
    def validate_graph(graph):
        roots = {}
        for node_id, node in graph.nodes.items():
            if node.type == 'starter':
                root = str(node.params.get('flow_id', Starter.default_params['flow_id'])).strip()
                if root in roots:
                    raise GraphError(f'Запускаторы {roots[root]} и {node_id}: повторяется номер потока {root}.')
                roots[root] = node_id

    def execute_block(self, node, inputs, heap):
        flow_id = str(node.params.get('flow_id', self.default_params['flow_id'])).strip()
        if not re.fullmatch(r'[1-9][0-9]*', flow_id):
            raise ValueError(f'Запускатор {node.id}: номер потока должен быть положительным целым числом.')
        return {'start': {'type': 'event', 'value': 'start', 'flow_id': flow_id}}
