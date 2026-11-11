"""Common catalogue of outer block implementations."""
from . import BLOCKS
from .graph import GraphBlock
from .optimizer import OptimizerBlock
from ..outer_graphs import OUTER_GRAPHS

BLOCK_TYPES = {**BLOCKS, **dict.fromkeys(OUTER_GRAPHS, GraphBlock), 'optimizer': OptimizerBlock}


def lookup(name, registry):
    return BLOCK_TYPES.get(name) or registry.get(name)


def prepare_handlers(graph, registry, results, tracker, on_plot, on_output, services, instances, cancel):
    context = {'results': results, 'tracker': tracker, 'on_plot': on_plot, 'on_output': on_output,
               'services': services, 'instances': instances, 'cancel': cancel}
    prepared = {}
    for node_id, node in graph.nodes.items():
        factory = getattr(lookup(node.type, registry), 'from_context', None)
        if factory is not None:
            prepared[node_id] = factory(node, graph, context)
    return prepared
