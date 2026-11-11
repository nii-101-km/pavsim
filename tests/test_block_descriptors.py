import unittest

from engines.optimizer import create_optimizer
from engines.typed_experiment import TypedExperimentExecutor
from shell.blocks import BLOCKS
from shell.blocks.optimizer import OptimizerBlock
from shell.nodes import get_builtin_type
from shell.server import _optimizer_block, _typed_experiment_block, _shell_builtin_blocks
from shell.session_runtime import _port_name


class BlockDescriptorTests(unittest.TestCase):
    def test_common_block_ports_and_defaults_are_taken_from_the_block(self):
        palette = {item['name']: item for item in _shell_builtin_blocks()}
        for name, block in BLOCKS.items():
            with self.subTest(block=name):
                definition = get_builtin_type(name)
                descriptor = palette[name]
                self.assertEqual(descriptor, block.descriptor())
                self.assertEqual(descriptor['parameters'], definition.default_params)
                self.assertEqual(descriptor['n_inputs'], len(definition.inputs))
                self.assertEqual(descriptor['n_outputs'], len(definition.outputs))
                for direction, ports in [('in', definition.inputs), ('out', definition.outputs)]:
                    self.assertEqual([_port_name(name, i, direction) for i in range(len(ports))],
                                     [port.name for port in ports])

    def test_optimizer_uses_one_port_and_default_definition(self):
        descriptor = _optimizer_block()
        self.assertEqual(descriptor['input_labels'], list(OptimizerBlock.ports[0]))
        self.assertEqual(descriptor['output_labels'], list(OptimizerBlock.ports[1]))
        controller = create_optimizer({})
        self.assertEqual(controller.params, descriptor['parameters'])
        self.assertEqual([_port_name('optimizer', i, 'in') for i in range(2)], descriptor['input_labels'])
        controller.close()

    def test_experiment_uses_one_port_and_default_definition(self):
        descriptor = _typed_experiment_block()
        self.assertEqual(descriptor['input_labels'], list(TypedExperimentExecutor.ports[0]))
        self.assertEqual(descriptor['output_labels'], list(TypedExperimentExecutor.ports[1]))
        self.assertEqual(descriptor['parameters'], TypedExperimentExecutor.default_params)
        self.assertEqual([_port_name('typed_experiment', i, 'in') for i in range(3)], descriptor['input_labels'])
