"""Graph display block: records its input for plotting.

One block per file; the file's directory (``Visualization``) is its category.
"""

from xcos_mini.core import Block


class GraphDisplay(Block):
    name = "graph_display"
    display_name = 'График'
    input_labels = ['сигнал']
    output_labels = []
    n_inputs = 1
    n_outputs = 0
    parameters = {"label": "signal"}
    description = "Displays (records) its input signal for plotting."

    def compute(self, t, inputs, params, state):
        # Return the input so the recorded series is the displayed signal.
        return float(inputs[0])
