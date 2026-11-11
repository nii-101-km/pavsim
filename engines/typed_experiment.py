"""Typed outer-port boundary for a scalar experiment."""
from __future__ import annotations

import copy
import math
import re
import threading

from shell.cancellation import SessionCancelled
from shell.blocks.input_slots import ConnectedInputs
from shell.structures import float_structure, read_float_structure
from .numerical import NumericalEngineAdapter
from .trial_resources import TrialResources


class TypedExperimentExecutor(ConnectedInputs):
    name = 'typed_experiment'
    ports = (('p1', 'p2', 'p3'), ('J',))
    default_params = {'t_end': 10.0, 'h': .02, 'method': 'rk4'}

    @classmethod
    def descriptor(cls):
        return {
            'name': cls.name, 'class': 'TypedExperiment', 'category': 'Computation',
            'n_inputs': len(cls.ports[0]), 'n_outputs': len(cls.ports[1]), 'state_kind': 'memory',
            'parameters': dict(cls.default_params),
            'description': 'Run an experiment with structured p1, p2, p3 and J ports.',
            'parameter_labels': {'t_end': 'End time', 'h': 'Step', 'method': 'Method'},
            'parameter_choices': {'method': ['rk4', 'euler']}, 'display_name': 'Experiment',
            'input_labels': list(cls.ports[0]), 'output_labels': list(cls.ports[1]),
        }

    @staticmethod
    def prepare_params(block, connections):
        params = dict(block.get('params', {}))
        params['_inner_model'] = block.get('internal', {})
        params['_j_connected'] = any(str(wire.get('from')) == str(block['id']) for wire in connections)
        return params

    def __init__(self, blocks_dir):
        self.blocks_dir = blocks_dir

    def create_session_block(self, block_id, params):
        return TypedExperimentSession(self)

    def execute_block(self, node, inputs, heap):
        from shell.typed_engine import BlockOutcome
        result = self._run(inputs, node.params)
        series = result.pop('series')
        return BlockOutcome(result, {'series': series})

    def _run(self, inputs, params, *, trial_resources=None, cancel_check=None):
        if trial_resources is None:
            trial = TrialResources()
            try:
                return self._run(inputs, params, trial_resources=trial, cancel_check=cancel_check)
            finally:
                trial.close()
        unknown = set(inputs) - {'p1', 'p2', 'p3'}
        if unknown:
            raise ValueError(f"Experiment: unknown input port(s): {', '.join(sorted(unknown))}.")
        flow_ids = {}
        for name, packet in inputs.items():
            flow_id = packet.get('flow_id') if isinstance(packet, dict) else None
            if flow_id is not None and (not isinstance(flow_id, str) or not re.fullmatch(r'[1-9][0-9]*(?:\.[1-9][0-9]*)*', flow_id)):
                raise ValueError(f'Эксперимент: у входа {name} некорректный номер потока.')
            flow_ids[name] = flow_id
        if len(flow_ids) > 1 and any(value is None for value in flow_ids.values()):
            raise ValueError('Эксперимент: у всех подключённых параметров должен быть номер потока.')
        if len(set(flow_ids.values())) > 1:
            details = ', '.join(f'{name}={flow_ids[name]}' for name in sorted(flow_ids))
            raise ValueError(f'Эксперимент: параметры принадлежат разным потокам ({details}).')
        flow_id = next(iter(flow_ids.values()), None)
        model = copy.deepcopy(params.get('_inner_model') or {'blocks': [], 'connections': []})
        blocks, wires = model.get('blocks', []), model.get('connections', [])
        input_terminals = {}
        result_terminal = None
        for block in blocks:
            kind, bid = block.get('type'), str(block.get('id'))
            if kind == 'experiment_input':
                port = block.get('params', {}).get('port', 0)
                if type(port) is not int or port not in range(3):
                    raise ValueError(f'Experiment input {bid}: invalid port number.')
                key = f'p{port + 1}'
                if key in input_terminals:
                    raise ValueError(f'Experiment: duplicate {key} terminal.')
                input_terminals[key] = block
            elif kind == 'experiment_result':
                if result_terminal is not None:
                    raise ValueError('Experiment: duplicate J terminal.')
                result_terminal = bid

        for key in ('p1', 'p2', 'p3'):
            terminal = input_terminals.get(key)
            used_inside = bool(terminal) and any(str(w.get('from')) == str(terminal['id']) for w in wires)
            used_outside = key in inputs
            if used_inside != used_outside:
                raise ValueError(f'Experiment: {key} must be connected both inside and outside, or unused on both sides.')
            if used_inside:
                value = read_float_structure(inputs[key], field=key)
                terminal['type'] = 'constant'
                terminal['params'] = {'value': value}

        j_wires = [w for w in wires if result_terminal is not None and str(w.get('to')) == result_terminal]
        if len(j_wires) > 1:
            raise ValueError('Experiment: J has multiple inputs.')
        if bool(j_wires) != bool(params.get('_j_connected')):
            raise ValueError('Experiment: J must be connected both inside and outside, or unused on both sides.')

        # A subsystem is expanded away by the numerical engine. Keep a sink at
        # J so expansion rewires the actual source (and port) to a stable ID.
        j_source = str(j_wires[0]['from']) if j_wires else None
        subsystem_source = any(str(block['id']) == j_source and block.get('type') == 'subsystem'
                               for block in blocks)
        model['blocks'] = [b for b in blocks if b.get('type') not in ('experiment_input', 'experiment_result')]
        model['connections'] = [w for w in wires if str(w.get('to')) != result_terminal]
        if subsystem_source:
            model['blocks'].append({'id': result_terminal, 'type': 'graph_display', 'params': {}})
            model['connections'].append(dict(j_wires[0]))
        if not model['blocks']:
            if j_wires:
                raise ValueError('Experiment: J source has no result.')
            return {'series': {}}
        adapter = NumericalEngineAdapter(blocks_dir=self.blocks_dir)
        result = adapter.simulate(model, params.get('t_end', self.default_params['t_end']), params.get('h', self.default_params['h']),
                                  params.get('method', self.default_params['method']),
                                  trial_resources=trial_resources, cancel_check=cancel_check)
        # Keep complete plot packets, including every channel of multi-series graphs.
        output = {'series': result['results']}
        if j_wires:
            source = j_wires[0]
            data = (result['results'].pop(result_terminal, None) if subsystem_source
                    else result['results'].get(str(source['from'])))
            if not data:
                raise ValueError('Experiment: J source has no result.')
            index = 0 if subsystem_source else int(source.get('from_port', 0))
            if 'outputs' in data:
                if index >= len(data['outputs']) or not data['outputs'][index]:
                    raise ValueError('Experiment: J source has no output data.')
                value = data['outputs'][index][-1]
            else:
                if not data.get('y'):
                    raise ValueError('Experiment: J source has no output data.')
                value = data['y'][-1]
            output['J'] = float_structure(value)
            if flow_id is not None:
                output['J']['flow_id'] = flow_id
        return output

    def describe(self):
        return {'name': self.name, 'description': 'Scalar experiment with typed outer ports.'}


class TypedExperimentSession(ConnectedInputs):
    """Keep only the active trial; release its numerical blocks after each run."""
    def __init__(self, executor):
        self.executor = executor
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._active = None

    def _check_stop(self):
        if self._stopped.is_set():
            raise SessionCancelled('Сессия остановлена.')

    def execute_block(self, node, inputs, heap):
        from shell.typed_engine import BlockOutcome
        trial = TrialResources()
        with self._lock:
            self._check_stop()
            self._active = trial
        try:
            result = self.executor._run(inputs, node.params, trial_resources=trial, cancel_check=self._check_stop)
            series = result.pop('series')
            return BlockOutcome(result, {'series': series})
        finally:
            try:
                trial.close()
            finally:
                with self._lock:
                    self._active = None

    def request_stop(self):
        self._stopped.set()
        with self._lock:
            trial = self._active
        if trial is not None:
            trial.request_stop()

    def close_session(self):
        self.request_stop()
