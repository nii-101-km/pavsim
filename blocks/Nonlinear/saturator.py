"""Saturator block: output = clamp(input, -limit, +limit) (non-stateful).

One block per file; the file's directory (``Nonlinear``) is its category.
"""

from xcos_mini.core import Block


class Saturator(Block):
    name = "saturator"
    display_name = 'Ограничитель'
    input_labels = ['u']
    output_labels = ['y']
    n_inputs = 1
    n_outputs = 1
    parameters = {"limit": 1.0}
    description = "Clamps its input to [-limit, +limit]."

    def compute(self, t, inputs, params, state):
        x = float(inputs[0])
        lim = float(params["limit"])
        if lim < 0:
            raise ValueError("'limit' must be non-negative")
        return max(-lim, min(lim, x))
