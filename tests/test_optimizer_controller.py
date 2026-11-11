import unittest
import threading

from engines.optimizer import create_optimizer
from shell.cancellation import SessionCancelled
from shell.optimizer_controller import OptimizerSession
from shell.structures import float_structure, read_float_structure


class OptimizerControllerTests(unittest.TestCase):
    def test_session_stop_cancels_optimizer_waiting_for_score(self):
        controller = create_optimizer({'max_evaluations': 20})
        session = OptimizerSession()
        session.attach(controller)
        self.assertEqual(controller.start(flow_id='1')[0], 'candidate')
        session.request_stop()
        with self.assertRaises(SessionCancelled):
            controller.respond(float_structure(1))
        controller.close()
        session.close_session()
        self.assertFalse(controller._thread.is_alive())

    def test_stop_unblocks_wait_for_optimizer_event(self):
        entered = threading.Event(); release = threading.Event()
        controller = create_optimizer({'max_evaluations': 20})
        original = controller.optimize
        def slow_start(*args, **kwargs):
            entered.set()
            release.wait(3)
            return original(*args, **kwargs)
        controller.optimize = slow_start
        session = OptimizerSession(); session.attach(controller)
        errors = []
        def start():
            try:
                controller.start(flow_id='1')
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=start)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            session.request_stop()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(errors[0], SessionCancelled)
        finally:
            release.set()
            worker.join(3)
            controller.close()
        self.assertFalse(controller._thread.is_alive())

    def test_search_exchanges_structures_and_finishes(self):
        controller = create_optimizer({'max_evaluations': 20, 'optimize_p2': False})
        try:
            kind, payload = controller.start()
            scores = 0
            while kind == 'candidate':
                self.assertEqual(set(payload), {'p1', 'p2', 'p3'})
                p1 = read_float_structure(payload['p1'])
                scores += 1
                kind, payload = controller.respond(float_structure((p1 - 1) ** 2))
            self.assertEqual(kind, 'done')
            self.assertGreater(scores, 1)
            self.assertLessEqual(scores, 20)
            self.assertLess(payload['score'], 1)
        finally:
            controller.close()

    def test_invalid_score_can_be_replaced_and_close_cancels(self):
        controller = create_optimizer({'max_evaluations': 20})
        try:
            self.assertEqual(controller.start()[0], 'candidate')
            with self.assertRaises(ValueError):
                controller.respond({'type': 'float', 'value': 'not a number'})
        finally:
            controller.close()
        self.assertFalse(controller._thread.is_alive())

    def test_disabled_optimizer_emits_fixed_values_once(self):
        controller = create_optimizer({'enabled': False, 'p1': 2})
        try:
            kind, values = controller.start()
            self.assertEqual(kind, 'candidate')
            self.assertEqual(read_float_structure(values['p1']), 2)
            kind, report = controller.respond(float_structure(3))
            self.assertEqual(kind, 'done')
            self.assertEqual(report['values']['p1'], 2)
            self.assertEqual(report['evaluations'], 1)
        finally:
            controller.close()
