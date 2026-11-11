import unittest

from shell.rendezvous import InputRendezvous


class RendezvousTests(unittest.TestCase):
    def test_waits_for_every_connected_input_then_resets(self):
        inputs = InputRendezvous(['p1', 'p2'])
        inputs.put('p2', 'first p2')
        self.assertFalse(inputs.ready())
        self.assertEqual(inputs.waiting_for(), ('p1',))
        inputs.put('p1', 'first p1')
        self.assertEqual(inputs.take(), {'p1': 'first p1', 'p2': 'first p2'})
        self.assertFalse(inputs.ready())
        self.assertEqual(inputs.waiting_for(), ())
        inputs.put('p1', 'second p1')
        self.assertEqual(inputs.waiting_for(), ('p2',))

    def test_repeated_signal_on_occupied_input_fails(self):
        inputs = InputRendezvous(['p1', 'p2'])
        inputs.put('p1', 1)
        with self.assertRaisesRegex(ValueError, 'p1.*уже содержит сигнал'):
            inputs.put('p1', 2)
        inputs.put('p2', 3)
        self.assertEqual(inputs.take(), {'p1': 1, 'p2': 3})
        inputs.put('p1', 2)
        inputs.put('p2', 4)
        self.assertEqual(inputs.take(), {'p1': 2, 'p2': 4})

    def test_drain_returns_unconsumed_packets_for_cleanup(self):
        inputs = InputRendezvous(['p1', 'p2'])
        inputs.put('p1', 'ref1')
        inputs.put('p2', 'ref2')
        self.assertEqual(list(inputs.drain()), ['ref1', 'ref2'])
        self.assertEqual(inputs.waiting_for(), ())

    def test_source_does_not_run_repeatedly_and_invalid_ports_fail(self):
        self.assertFalse(InputRendezvous([]).ready())
        with self.assertRaises(ValueError):
            InputRendezvous(['p1', 'p1'])
        with self.assertRaises(ValueError):
            InputRendezvous(['p1']).put('p2', 1)
