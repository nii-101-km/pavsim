"""Signal generator block: sine / square / ramp / step from time.

One block per file; the file's directory (``Sources``) is its category.
"""

import math

from xcos_mini.core import Block


class SignalGenerator(Block):
    name = "signal_generator"
    display_name = 'Генератор сигналов'
    input_labels = []
    output_labels = ['y']
    n_inputs = 0
    n_outputs = 1
    parameters = {
        "type": "sine",        # sine | square | ramp | step
        "amplitude": 1.0,
        "frequency": 0.5,
        "phase": 0.0,
        "slope": 1.0,
        "t0": 0.0,
        "offset": 0.0,
    }
    description = "Generates sine, square, ramp, or step signals from time."

    def compute(self, t, inputs, params, state):
        kind = params.get("type", "sine")
        amp = float(params.get("amplitude", 1.0))
        freq = float(params.get("frequency", 0.5))
        phase = float(params.get("phase", 0.0))
        offset = float(params.get("offset", 0.0))
        if kind == "sine":
            return amp * math.sin(2.0 * math.pi * freq * t + phase) + offset
        if kind == "square":
            s = 1.0 if math.sin(2.0 * math.pi * freq * t + phase) >= 0.0 else -1.0
            return amp * s + offset
        if kind == "ramp":
            return float(params.get("slope", 1.0)) * t + offset
        if kind == "step":
            return amp if t >= float(params.get("t0", 0.0)) else 0.0 + offset
        raise ValueError(f"Unknown signal type '{kind}'")
