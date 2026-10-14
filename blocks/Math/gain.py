"""Gain block: output = gain * input.

One block per file; the file's directory (``Math``) is its category.
"""

from xcos_mini.core import Block


class Gain(Block):
    name = "gain"
    display_name = 'Усилитель'
    input_labels = ['u']
    output_labels = ['K·u']
    n_inputs = 1
    n_outputs = 1
    parameters = {"gain": 1.0}
    description = "Outputs gain * input."

    def compute(self, t, inputs, params, state):
        return float(params["gain"]) * float(inputs[0])
