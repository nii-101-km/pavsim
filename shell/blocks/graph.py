"""Runtime state and input handling for external graph blocks."""
import copy
import math

from ..graph import GraphError
from ..outer_graphs import OUTER_GRAPHS
from ..structures import read_float_structure


class OuterGraphRuntime:
    def __init__(self, graph, results, tracker, on_plot=None, only_node=None):
        self.results = results
        self.tracker = tracker
        self.on_plot = on_plot
        self.pending = {}
        for node_id, node in graph.nodes.items():
            if (only_node is not None and node_id != only_node) or node.type not in OUTER_GRAPHS:
                continue
            if node.type == 'graph_outer_xy_score':
                self._validate_display(node_id, node.params)
            ports, _, required = OUTER_GRAPHS[node.type]
            connected = {wire.to_port for wire in graph.get_input_connections(node_id)}
            missing = [port for port in ports[:required] if port not in connected]
            if missing:
                raise GraphError(f'График {node_id}: подключите вход данных: {", ".join(missing)}.')
            active = [port for port in ports if port in connected]
            self.pending[node_id] = dict.fromkeys(active)
            plot = {'t': [], 'y': []}
            if node.type != 'graph_outer':
                plot['outputs'] = [[] for _ in active]
            results[node_id] = {'_plot': plot}

    @staticmethod
    def _validate_display(node_id, params):
        count = params.get('last_points', 0)
        if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count) or count < 0 or int(count) != count:
            raise ValueError(f'График {node_id}: число последних точек должно быть целым неотрицательным.')
        for axis in ('x', 'y'):
            start, end = params.get(axis + '_start'), params.get(axis + '_end')
            if start is not None or end is not None:
                start = '' if start is None else str(start).strip()
                end = '' if end is None else str(end).strip()
                if bool(start) != bool(end):
                    raise ValueError(f'График {node_id}: задайте начало и конец оси {axis.upper()}.')
                text = start + ':' + end if start else ''
            else:
                text = params.get(axis + '_range', '')
            if not isinstance(text, str):
                raise ValueError(f'График {node_id}: диапазон оси {axis.upper()} должен быть числовым.')
            if text.strip():
                try:
                    bounds = [float(part.strip().replace(',', '.')) for part in text.split(':')]
                except ValueError:
                    bounds = []
                if len(bounds) != 2 or not all(math.isfinite(v) for v in bounds) or bounds[0] >= bounds[1]:
                    raise ValueError(f'График {node_id}: начало оси {axis.upper()} должно быть меньше конца.')

    def deliver(self, node_id, port, packet):
        plot = self.results[node_id]['_plot']
        if port == 'reset':
            if packet.get('type') != 'event' or packet.get('value') != 'start':
                raise ValueError(f'График {node_id}: на вход сброса нужен сигнал начала.')
            plot['t'].clear()
            plot['y'].clear()
            for channel in plot.get('outputs', []):
                channel.clear()
            for pending_port, pending in self.pending[node_id].items():
                if pending is not None:
                    self.tracker.change(node_id, pending[1], 'waiting', -1, pending_port)
            self.pending[node_id] = dict.fromkeys(self.pending[node_id])
        else:
            value = read_float_structure(packet, field=f'График {node_id}')
            pending = self.pending[node_id]
            if pending[port] is not None:
                raise GraphError(f'График {node_id}: вход {port} уже содержит сигнал; следующий сигнал не принят.')
            pending[port] = (value, packet.get('flow_id'))
            self.tracker.change(node_id, packet.get('flow_id'), 'waiting', 1, port)
            if all(item is not None for item in pending.values()):
                values = [item[0] for item in pending.values()]
                for pending_port, item in pending.items():
                    self.tracker.change(node_id, item[1], 'waiting', -1, pending_port)
                self.pending[node_id] = dict.fromkeys(pending)
                plot['t'].append(len(plot['y']) + 1)
                plot['y'].append(values[0])
                for channel, point in zip(plot.get('outputs', []), values):
                    channel.append(point)
        if self.on_plot:
            self.on_plot(node_id, copy.deepcopy(plot))

    def check_complete(self):
        for node_id, pending in self.pending.items():
            if any(value is not None for value in pending.values()):
                missing = [port for port, value in pending.items() if value is None]
                raise GraphError(f'График {node_id}: не поступили сигналы на входы {", ".join(missing)}.')


class GraphBlock:
    """A graph handles each connected port independently."""
    requires_signal = False

    @staticmethod
    def descriptor(name):
        ports, kind, _ = OUTER_GRAPHS[name]
        if name == 'graph_outer':
            return {'name': name, 'class': 'OuterGraph', 'category': 'Shell',
                    'n_inputs': 2, 'n_outputs': 0, 'state_kind': 'memory', 'parameters': {'label': ''},
                    'description': 'Plots numeric structures; a start signal clears the graph.',
                    'parameter_labels': {'label': 'Label'}, 'parameter_choices': {},
                    'display_name': 'Graph (structures)', 'input_labels': ['value', 'reset'], 'output_labels': []}
        params = ({'label': '', 'x_start': '', 'x_end': '', 'y_start': '', 'y_end': '', 'last_points': 0}
                  if kind == 'xy_score' else {'label': '', 'x_range': '', 'y_range': ''}
                  if kind == 'xy' else {'label': ''})
        return {'name': name, 'class': 'OuterGraph', 'category': 'Shell',
                'n_inputs': len(ports) + 1, 'n_outputs': 0, 'state_kind': 'memory', 'parameters': params,
                'description': 'Plots numeric structures and clears on a start signal.',
                'parameter_labels': {'label': 'Label', 'x_range': 'X range', 'y_range': 'Y range',
                                     'last_points': 'Last points (0 = all)'},
                'parameter_choices': {}, 'display_name': name,
                'input_labels': list(ports) + ['reset'], 'output_labels': []}

    @classmethod
    def from_context(cls, node, graph, context):
        connected = [wire.to_port for wire in graph.get_input_connections(node.id)]
        runtime = OuterGraphRuntime(graph, context['results'], context['tracker'],
                                    context['on_plot'], only_node=node.id)
        return cls(node.id, connected, runtime)
    def __init__(self, node_id, connected_ports, runtime):
        self.node_id = node_id
        self.independent_ports = frozenset(connected_ports)
        self.runtime = runtime
        self.result = None

    @property
    def active(self):
        return False

    def on_signal(self, port, packet):
        self.runtime.deliver(self.node_id, port, packet)
        return None

    def check_complete(self):
        pending = self.runtime.pending[self.node_id]
        if any(value is not None for value in pending.values()):
            missing = [port for port, value in pending.items() if value is None]
            raise GraphError(f'График {self.node_id}: не поступили сигналы на входы {", ".join(missing)}.')

    def close(self):
        pass
