"""Multiplication block: output = input0 * input1.

One block per file; the file's directory (``Math``) is its category.
"""

from xcos_mini.core import Block


class Multiplication(Block):
    name = "multiplication"
    display_name = 'Умножитель'
    input_labels = ['a', 'b']
    output_labels = ['a·b']
    n_inputs = 2
    n_outputs = 1
    parameters = {}
    description = "Outputs the product of its two inputs."

    def compute(self, t, inputs, params, state):
        return float(inputs[0]) * float(inputs[1])
