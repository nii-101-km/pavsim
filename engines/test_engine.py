"""Example of an external structured-signal block."""
from shell.structures import float_structure, read_float_structure, read_list_structure


class TestExecutor:
    name = 'test_doubler'

    def execute_block(self, node, inputs, heap):
        total = 0.0
        for packet in inputs.values():
            values = read_list_structure(packet) if packet.get('type') == 'list' else [packet]
            total += sum(read_float_structure(value) for value in values if value is not None)
        return {'result': float_structure(total * 2)}

    def describe(self):
        return {'name': self.name, 'description': 'Test executor: doubles numeric structures.'}
