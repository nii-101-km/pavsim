"""Add explicit starters to test diagrams that exercise optimizers."""
from shell.graph import Connection, Node


def start_graph(graph):
    for index, node in enumerate(list(graph.nodes.values()), 1):
        if node.type not in ('optimizer', 'input_value'):
            continue
        if any(w.to_node == node.id and w.to_port == 'start' for w in graph.connections):
            continue
        starter = f'__starter_{node.id}'
        graph.add_node(Node(starter, 'starter', {'flow_id': str(index)}))
        graph.add_connection(Connection(starter, 'start', node.id, 'start'))
    return graph


def start_model(model):
    counter = [0]
    def visit(diagram):
        starters = {}
        for block in list(diagram.get('blocks', [])):
            if block.get('type') in ('optimizer', 'input_value'):
                if any(str(w.get('to')) == str(block['id']) and w.get('to_port', 0) == (1 if block['type'] == 'optimizer' else 0)
                       for w in diagram.get('connections', [])):
                    continue
                counter[0] += 1
                name = '__starter_' + str(block['id'])
                starters[str(block['id'])] = name
                diagram['blocks'].append({'id': name, 'type': 'starter', 'params': {'flow_id': str(counter[0])}})
                diagram.setdefault('connections', []).append({'from': name, 'to': block['id'], 'to_port': 1 if block['type'] == 'optimizer' else 0})
            elif block.get('type') == 'subsystem':
                visit(block.get('internal', {}))
        for connection in diagram.get('connections', []):
            source = str(connection.get('from'))
            if source in starters and connection.get('from_port', 0) == 3:
                connection['from'], connection['from_port'] = starters[source], 0
    visit(model)
    return model
