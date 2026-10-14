"""Delay block: one-step (z^-1) delay; output is the previous input (memory state).

One block per file; the file's directory (``Dynamics``) is its category.
"""

from xcos_mini.core import Block


class Delay(Block):
    name = "delay"
    display_name = 'Задержка на шаг'
    input_labels = ['u']
    output_labels = ['y']
    n_inputs = 1
    n_outputs = 1
    parameters = {"initial_value": 0.0}
    state_kind = "memory"
    description = "One-step (z^-1) delay: output is the input from the previous step."

    def state_size(self, params):
        return 1

    def initial_state(self, params):
        return [float(params.get("initial_value", 0.0))]

    def compute(self, t, inputs, params, state):
        return float(state[0])

    def update_memory(self, t, inputs, params, state):
        return [float(inputs[0])]
