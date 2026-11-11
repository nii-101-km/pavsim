import math
import unittest
from shell.structures import float_structure, read_float_structure


class FloatStructureTests(unittest.TestCase):
    def test_round_trip_text_value(self):
        packet = float_structure(1.25)
        self.assertEqual(packet, {'type': 'float', 'value': '1.25'})
        self.assertEqual(read_float_structure(packet, field='p1'), 1.25)

    def test_invalid_values_are_rejected_at_boundary(self):
        for value in (True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                float_structure(value)
        for packet in ({'type': 'float', 'value': 1.0}, {'type': 'float', 'value': '1,2'},
                       {'type': 'float', 'value': 'nan'}, {'type': 'float', 'value': '1e999'},
                       {'type': 'text', 'value': '1.0'}, 1.0):
            with self.subTest(packet=packet), self.assertRaisesRegex(ValueError, 'p1'):
                read_float_structure(packet, field='p1')
