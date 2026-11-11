import threading
import unittest
from unittest.mock import patch

from engines.typed_experiment import TypedExperimentExecutor
from engines.numerical import NumericalEngineAdapter
from engines.trial_resources import TrialResources
from shell.cancellation import SessionCancelled
from shell.graph import Node


class Resource:
    def __init__(self, events, fail_close=False):
        self.events = events
        self.fail_close = fail_close
        self.stopped = threading.Event()

    def request_stop(self):
        self.events.append('stop')
        self.stopped.set()

    def close_trial(self):
        self.events.append('close')
        if self.fail_close:
            raise RuntimeError('cleanup failed')


class TrialResourceTests(unittest.TestCase):
    def setUp(self):
        self.executor = TypedExperimentExecutor('blocks')
        self.model = {'_inner_model': {'blocks': [{'id': 'c', 'type': 'constant', 'params': {'value': 1}}],
                                       'connections': []}, '_j_connected': False}

    def test_each_trial_closes_its_resources_before_next_trial(self):
        events = []
        instance = self.executor.create_session_block('exp', self.model)
        def simulate(*args, trial_resources, **kwargs):
            events.append('start')
            trial_resources.add(Resource(events))
            return {'results': {}}
        with patch('engines.typed_experiment.NumericalEngineAdapter.simulate', side_effect=simulate):
            instance.execute_block(Node('exp', 'typed_experiment', self.model), {}, None)
            instance.execute_block(Node('exp', 'typed_experiment', self.model), {}, None)
        self.assertEqual(events, ['start', 'close', 'start', 'close'])
        instance.close_session()
        self.assertEqual(events, ['start', 'close', 'start', 'close'])

    def test_real_numerical_instances_close_after_each_trial(self):
        events = []
        adapter = NumericalEngineAdapter('blocks')
        library = adapter._get_lib()
        instantiate = library.instantiate
        def track(name):
            block = instantiate(name)
            block.close_trial = lambda: events.append('close ' + name)
            return block
        instance = self.executor.create_session_block('exp', self.model)
        with patch.object(library, 'instantiate', side_effect=track), \
             patch('engines.typed_experiment.NumericalEngineAdapter', return_value=adapter):
            instance.execute_block(Node('exp', 'typed_experiment', self.model), {}, None)
            self.assertEqual(events, ['close constant'])
            instance.execute_block(Node('exp', 'typed_experiment', self.model), {}, None)
            self.assertEqual(events, ['close constant', 'close constant'])
        instance.close_session()
        self.assertEqual(events, ['close constant', 'close constant'])

    def test_active_trial_is_notified_and_closed_on_session_stop(self):
        events = []
        instance = self.executor.create_session_block('exp', self.model)
        registered = threading.Event()
        resource = Resource(events)
        errors = []
        def simulate(*args, trial_resources, cancel_check, **kwargs):
            trial_resources.add(resource)
            registered.set()
            if not resource.stopped.wait(2):
                raise AssertionError('Stop was not delivered')
            cancel_check()
        def run():
            try:
                instance.execute_block(Node('exp', 'typed_experiment', self.model), {}, None)
            except BaseException as exc:
                errors.append(exc)
        with patch('engines.typed_experiment.NumericalEngineAdapter.simulate', side_effect=simulate):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(registered.wait(2))
            instance.request_stop()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(events, ['stop', 'close'])
        self.assertIsInstance(errors[0], SessionCancelled)

    def test_cleanup_attempts_all_resources_even_when_one_fails(self):
        events = []
        trial = TrialResources()
        trial.add(Resource(events, fail_close=True))
        trial.add(Resource(events))
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            trial.close()
        self.assertEqual(events, ['close', 'close'])
        trial.close()
