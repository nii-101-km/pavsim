"""Second-order dynamic block with two integrated states.

Transfer function: K*omega0**2 / (s**2 + 2*zeta*omega0*s + omega0**2).
One input, one scalar output.  For a unit step and zeta < 1, the response
overshoots and decays toward K.
"""

from xcos_mini.core import Block


class SecondOrder(Block):
    name = "second_order"
    display_name = 'Звено 2-го порядка'
    input_labels = ['u']
    output_labels = ['y']
    n_inputs = 1
    n_outputs = 1
    parameters = {
        "K": 1.0,
        "omega0": 2.0,
        "zeta": 0.2,
        "initial_value": 0.0,
        "initial_velocity": 0.0,
    }
    state_kind = "integrated"
    description = (
        "Second-order system: y'' + 2*zeta*omega0*y' + omega0^2*y "
        "= K*omega0^2*u."
    )

    def state_size(self, params):
        return 2

    def initial_state(self, params):
        return [
            float(params.get("initial_value", 0.0)),
            float(params.get("initial_velocity", 0.0)),
        ]

    def compute(self, t, inputs, params, state):
        return float(state[0])

    def derivative(self, t, inputs, params, state):
        omega0 = float(params["omega0"])
        zeta = float(params["zeta"])
        gain = float(params["K"])
        if not (omega0 > 0.0):
            raise ValueError("'omega0' must be positive")
        if zeta < 0.0:
            raise ValueError("'zeta' must be non-negative")
        position, velocity = map(float, state)
        u = float(inputs[0])
        acceleration = omega0**2 * (gain * u - position) - 2.0 * zeta * omega0 * velocity
        return [velocity, acceleration]
