"""Integrator block: dx/dt = gain*input; output is the state (integrated state).

One block per file; the file's directory (``Dynamics``) is its category.
"""

from xcos_mini.core import Block


class Integrator(Block):
    name = "integrator"
    display_name = 'Интегратор'
    input_labels = ['u']
    output_labels = ['y']
    n_inputs = 1
    n_outputs = 1
    parameters = {"initial_value": 0.0, "gain": 1.0}
    state_kind = "integrated"
    description = "Integrates its input over time (dx/dt = gain*input). Output is the state."

    def state_size(self, params):
        return 1

    def initial_state(self, params):
        return [float(params.get("initial_value", 0.0))]

    def compute(self, t, inputs, params, state):
        return float(state[0])

    def derivative(self, t, inputs, params, state):
        return [float(params.get('gain', 1.0)) * float(inputs[0])]
