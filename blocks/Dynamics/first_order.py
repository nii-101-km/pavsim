"""First-order low-pass block: y' = (gain*u - y)/tau, y(0)=y0 (integrated state).

One block per file; the file's directory (``Dynamics``) is its category.
"""

from xcos_mini.core import Block


class FirstOrder(Block):
    name = "first_order"
    display_name = 'Апериодическое звено'
    input_labels = ['u']
    output_labels = ['y']
    n_inputs = 1
    n_outputs = 1
    parameters = {"tau": 1.0, "initial_value": 0.0, "gain": 1.0}
    state_kind = "integrated"
    description = "First-order low-pass: dy/dt = (gain*u - y)/tau."

    def state_size(self, params):
        return 1

    def initial_state(self, params):
        return [float(params.get("initial_value", 0.0))]

    def compute(self, t, inputs, params, state):
        return float(state[0])

    def derivative(self, t, inputs, params, state):
        tau = float(params["tau"])
        if tau <= 0:
            raise ValueError("'tau' must be positive")
        return [(float(params.get('gain', 1.0)) * float(inputs[0]) - float(state[0])) / tau]
