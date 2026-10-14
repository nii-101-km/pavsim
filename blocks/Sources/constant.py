"""Constant block: outputs a constant value.

One block per file; the file's directory (``Sources``) is its category.
"""

from xcos_mini.core import Block


class Constant(Block):
    name = "constant"
    display_name = 'Константа'
    input_labels = []
    output_labels = ['c']
    n_inputs = 0
    n_outputs = 1
    parameters = {"value": 0.0}
    description = "Outputs a constant value."

    def compute(self, t, inputs, params, state):
        return float(params["value"])
