"""Built-in node types for the data graph shell.

Each NodeType defines the default ports and parameters for a node type.
Nodes in the graph can have additional ports added by the user.
"""

from .graph import Port
from .outer_graphs import OUTER_GRAPHS
from .blocks import BLOCKS


class NodeType:
    """Definition of a node type available in the shell."""

    def __init__(self, name, description, inputs=None, outputs=None,
                 default_params=None, executor_name=None):
        self.name = name
        self.description = description
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.default_params = default_params or {}
        self.executor_name = executor_name  # None means built-in

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "default_params": dict(self.default_params),
            "executor": self.executor_name,
        }


# --------------------------------------------------------------------------- #
# Built-in node types
# --------------------------------------------------------------------------- #

def _definition(name, block):
    return NodeType(
        name=name, description=block.node_description,
        inputs=[Port(port, 'input', hint) for port, hint in block.node_inputs],
        outputs=[Port(port, 'output', hint) for port, hint in block.node_outputs],
        default_params=dict(block.default_params),
    )


BUILTIN_TYPES = {name: _definition(name, block) for name, block in BLOCKS.items()}
INPUT_VALUE = BUILTIN_TYPES['input_value']
PARAM_ASSEMBLER = BUILTIN_TYPES['param_assembler']
PARAM_SPLITTER = BUILTIN_TYPES['param_splitter']
RESULT_DISPLAY = BUILTIN_TYPES['result_display']
STARTER = BUILTIN_TYPES['starter']

for graph_name, (ports, _, _) in OUTER_GRAPHS.items():
    BUILTIN_TYPES[graph_name] = NodeType(
        name=graph_name, description='Structured graph.',
        inputs=[Port(name, 'input', 'structure') for name in (*ports, 'reset')],
        outputs=[], default_params={'label': ''})


GRAPH_OUTER = BUILTIN_TYPES['graph_outer']


def get_builtin_type(name):
    """Return a built-in NodeType by name, or None."""
    return BUILTIN_TYPES.get(name)


def list_builtin_types():
    """Return all built-in node types as a list of dicts."""
    return [t.to_dict() for t in BUILTIN_TYPES.values()]
