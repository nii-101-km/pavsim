"""Subsystem container block for xcos_mini.

A Subsystem is a single block on the parent diagram that encapsulates
an internal diagram. It has exactly one input and one output.

The internal diagram is stored in the block's `internal` field in the
JSON model. During model construction, the expansion function
(xcos_mini.subsystem.expand_subsystems) resolves the internal diagram
into flat blocks and rewires external connections through the In1/Out1
boundary terminals.

The Subsystem.compute method is never called during simulation because
the expansion replaces it with its internal blocks before the Engine runs.
"""
from xcos_mini.core import Block


class Subsystem(Block):
    """Container block that holds an internal diagram.

    n_inputs=1, n_outputs=1. The internal diagram is accessed via the
    `internal` attribute (set from the model dict during construction).
    """
    name = "subsystem"
    display_name = 'Подсистема'
    input_labels = ['In1']
    output_labels = ['Out1']
    n_inputs = 1
    n_outputs = 1
    parameters = {}
    state_kind = "none"
    description = "Subsystem container: double-click to edit internal diagram"

    def __init__(self):
        super().__init__()
        self.internal = None  # dict: {blocks: [...], connections: [...]}

    def compute(self, t, inputs, params, state):
        raise NotImplementedError(
            "Subsystem must be expanded before simulation. "
            "This indicates a bug in the model construction pipeline."
        )
