"""State and signal handling for one outer optimizer block."""
import copy
import re

from ..graph import GraphError
from .input_slots import ConnectedInputs


class OptimizerBlock(ConnectedInputs):
    ports = (('J', 'start'), ('p1', 'p2', 'p3'))
    independent_ports = frozenset({'start', 'J'})
    default_params = {
        'algorithm': 'coordinate', 'algorithm_options': '', 'enabled': True,
        'p1': .2, 'p2': .1, 'p3': 0.,
        'optimize_p1': True, 'optimize_p2': True, 'optimize_p3': False,
        'min_p1': 0., 'max_p1': 5., 'min_p2': 0., 'max_p2': 5.,
        'min_p3': 0., 'max_p3': 2., 'max_evaluations': 100, 'trial_delay': 0.,
    }

    @classmethod
    def descriptor(cls):
        return {
            'name': 'optimizer', 'class': 'Optimizer', 'category': 'Optimization',
            'n_inputs': len(cls.ports[0]), 'n_outputs': len(cls.ports[1]), 'state_kind': 'memory',
            'parameters': dict(cls.default_params),
            'description': 'Starts on a signal and outputs parameter candidates to minimize J.',
            'parameter_labels': {
                'algorithm': 'Algorithm', 'algorithm_options': 'Options', 'enabled': 'Enabled',
                'p1': 'p1', 'p2': 'p2', 'p3': 'p3',
                'optimize_p1': 'Tune p1', 'optimize_p2': 'Tune p2', 'optimize_p3': 'Tune p3',
                'min_p1': 'p1 min', 'max_p1': 'p1 max', 'min_p2': 'p2 min', 'max_p2': 'p2 max',
                'min_p3': 'p3 min', 'max_p3': 'p3 max', 'max_evaluations': 'Max evaluations',
                'trial_delay': 'Delay between trials (s)',
            },
            'parameter_choices': {'algorithm': ['coordinate', 'nelder_mead', 'gradient', 'hooke_jeeves', 'heavy_ball']},
            'display_name': 'Optimizer', 'input_labels': list(cls.ports[0]), 'output_labels': list(cls.ports[1]),
        }

    @staticmethod
    def create_session_block(block_id, params):
        from ..optimizer_controller import OptimizerSession
        return OptimizerSession()

    @classmethod
    def from_context(cls, node, graph, context):
        return cls(node, [wire.to_port for wire in graph.get_input_connections(node.id)],
                   bool(graph.get_output_connections(node.id)), context['services'].get('optimizer'),
                   context['instances'].get(node.id), context['cancel'], context['on_output'])
    def __init__(self, node, connected_inputs, has_outputs, factory, session, cancel, on_output):
        self.node = node
        self.factory = factory
        self.session = session
        self.cancel = cancel
        self.on_output = on_output
        self.controller = None
        self.entries = []
        self.result = None
        if set(connected_inputs) != {'J', 'start'}:
            raise GraphError(f'Оптимизатор {node.id}: подключите входы J и запуска.')
        if not has_outputs:
            raise GraphError(f'Оптимизатор {node.id}: подключите хотя бы один выход.')
        if factory is None:
            raise GraphError('Исполнитель оптимизатора недоступен.')

    def start(self, signal):
        if signal.get('type') != 'event' or signal.get('value') != 'start':
            raise ValueError(f'Оптимизатор {self.node.id}: нужен сигнал запуска.')
        flow_id = signal.get('flow_id')
        if not isinstance(flow_id, str) or not re.fullmatch(r'[1-9][0-9]*(?:\.[1-9][0-9]*)*', flow_id):
            raise ValueError(f'Оптимизатор {self.node.id}: в сигнале запуска нужен номер потока.')
        if self.controller is not None:
            raise GraphError(f'Оптимизатор {self.node.id}: повторный запуск во время подбора.')
        self.result = None
        controller = self.factory(self.node.params)
        controller.session_cancel = self.cancel
        self.controller = controller
        if self.session is not None:
            self.session.attach(controller)
        kind, payload = controller.start(flow_id=flow_id)
        return self._finish_or_outputs(kind, payload)

    def on_signal(self, port, signal):
        if port == 'start':
            return self.start(signal)
        if port == 'J':
            return self.receive({'J': signal})
        raise GraphError(f'Оптимизатор {self.node.id}: неизвестный вход {port}.')

    @property
    def active(self):
        return self.controller is not None

    def check_complete(self):
        if self.controller is not None and self.controller._waiting:
            raise GraphError(f'Расчёт остановился: оптимизатор {self.node.id} ждёт J.')

    def receive(self, inputs):
        controller = self.controller
        if controller is None:
            raise GraphError(f'Оптимизатор {self.node.id}: J пришёл до сигнала запуска.')
        if set(inputs) != {'J'}:
            raise GraphError(f'Оптимизатор {self.node.id}: требуется подключение к входу J.')
        actual = inputs['J'].get('flow_id')
        if actual != controller.flow_id:
            raise GraphError(f'Оптимизатор {self.node.id}: J пришёл из потока {actual}, ожидается {controller.flow_id}.')
        kind, payload = controller.respond(inputs['J'])
        self.entries.append(controller.entries[-1])
        if self.on_output:
            self.on_output(self.node.id, {'kind': 'optimizer_log', 'entries': copy.deepcopy(self.entries)})
        kind, payload = controller._delay_candidate(kind, payload)
        return self._finish_or_outputs(kind, payload)

    def _finish_or_outputs(self, kind, payload):
        if kind == 'candidate':
            return payload
        self.result = {'_report': payload, '_output': {'kind': 'optimizer_log', 'entries': copy.deepcopy(self.entries)}}
        self.close()
        return None

    def close(self):
        controller, self.controller = self.controller, None
        if controller is not None:
            try:
                controller.close()
            finally:
                if self.session is not None:
                    self.session.detach(controller)
