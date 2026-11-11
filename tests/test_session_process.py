from tests.starter_helpers import start_model
import os
import time
import unittest

from shell.session_process import SessionProcess


def unresponsive_worker(channel, session_id):
    channel.send({'event': 'ready', 'session_id': session_id})
    time.sleep(30)


def wait_for(session, name, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = session.receive(max(0, deadline - time.monotonic()))
        if event['event'] == 'error':
            raise AssertionError(event)
        if event['event'] == name:
            return event
    raise TimeoutError(name)


class SessionProcessTests(unittest.TestCase):
    def test_separate_process_runs_a_diagram_and_exposes_output(self):
        session = SessionProcess()
        try:
            self.assertNotEqual(session.pid, os.getpid())
            wait_for(session, 'ready')
            diagram = {'blocks': [{'id': 'input', 'type': 'input_value', 'params': {'value': 3}},
                                  {'id': 'plot', 'type': 'graph_outer'}],
                       'connections': [{'from': 'input', 'to': 'plot'}]}
            session.send('prepare', model=start_model(diagram))
            wait_for(session, 'prepared')
            session.send('start')
            wait_for(session, 'started')
            event = wait_for(session, 'output_changed')
            self.assertEqual(event['block_id'], 'plot')
            wait_for(session, 'completed')
            session.send('get_output', block_id='plot')
            output = wait_for(session, 'output')
            self.assertEqual(output['value']['y'], [3.0])
            self.assertEqual(session.stop(), 'stopped')
            self.assertFalse(session.is_alive())
        finally:
            session.close()

    def test_cancels_waiting_optimizer_and_stops_session(self):
        session = SessionProcess()
        try:
            wait_for(session, 'ready')
            diagram = {'blocks': [
                {'id': 'opt', 'type': 'optimizer', 'params': {'max_evaluations': 20, 'trial_delay': 30}},
                {'id': 'exp', 'type': 'typed_experiment', 'params': {'t_end': 1, 'h': .1},
                 'internal': {'blocks': [{'id': 'P1', 'type': 'experiment_input', 'params': {'port': 0}},
                                         {'id': 'J', 'type': 'experiment_result'}],
                              'connections': [{'from': 'P1', 'to': 'J'}]}},
                {'id': 'plot', 'type': 'graph_outer'},
            ], 'connections': [{'from': 'opt', 'to': 'exp'}, {'from': 'exp', 'to': 'opt'},
                               {'from': 'exp', 'to': 'plot'}]}
            start_model(diagram)
            diagram['connections'].sort(key=lambda wire: wire['to'] != 'plot')
            session.send('prepare', model=diagram)
            wait_for(session, 'prepared')
            session.send('start')
            wait_for(session, 'started')
            wait_for(session, 'output_changed')
            self.assertEqual(session.stop(timeout=2), 'stopped')
            self.assertFalse(session.is_alive())
        finally:
            session.close()

    def test_unresponsive_worker_is_forcibly_terminated(self):
        session = SessionProcess(worker=unresponsive_worker)
        try:
            wait_for(session, 'ready')
            self.assertEqual(session.stop(timeout=.1), 'terminated')
            self.assertFalse(session.is_alive())
        finally:
            session.close()
