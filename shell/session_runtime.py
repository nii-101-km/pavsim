"""Build and execute session diagrams independently of the HTTP server."""
import os
import sys
from pathlib import Path
from shell.registry import ExecutorRegistry
from shell.nodes import get_builtin_type
from shell.blocks.catalog import lookup

BLOCKS_DIR = Path(__file__).resolve().parent.parent / 'blocks'
IN1_TYPE, OUT1_TYPE = 'in1_terminal', 'out1_terminal'
_shared_registry = ExecutorRegistry()
_optimizer_factory = None
if os.environ.get('PAVSIM_NO_ENGINES') != '1' and '--no-engines' not in sys.argv:
    try:
        from engines.numerical import NumericalEngineAdapter
        from engines.typed_experiment import TypedExperimentExecutor
        from engines.optimizer import create_optimizer
        if NumericalEngineAdapter(blocks_dir=str(BLOCKS_DIR)).available:
            _shared_registry.register(TypedExperimentExecutor(blocks_dir=str(BLOCKS_DIR)))
            _optimizer_factory = create_optimizer
    except ImportError:
        pass

def _port_name(node_type, port_index, direction):
    """Resolve a serialized port index from the block's own definition."""
    definition = get_builtin_type(node_type)
    if definition is not None:
        ports = definition.inputs if direction == 'in' else definition.outputs
        names = [port.name for port in ports]
    else:
        block = lookup(node_type, _shared_registry)
        declared = getattr(block, 'ports', None)
        names = declared[0 if direction == 'in' else 1] if declared else ()
        if node_type == IN1_TYPE:
            names = () if direction == 'in' else ('value',)
        elif node_type == OUT1_TYPE:
            names = ('value',) if direction == 'in' else ()
    if type(port_index) is int and 0 <= port_index < len(names):
        return names[port_index]
    return str(port_index)


def _validate_outer_subsystems(model_dict):
    if any(block.get('type') == 'subsystem' for block in model_dict.get('blocks', [])):
        raise ValueError('Подсистемы доступны только внутри динамической системы (Эксперимента).')


def _build_generic_graph(model_dict):
    """Construct the outer graph from the serialized diagram."""
    from shell.graph import DataGraph, Node, Connection

    _validate_outer_subsystems(model_dict)
    blocks = model_dict.get("blocks", [])

    # Build a DataGraph from the model dict
    graph = DataGraph()
    for b in blocks:
        block_type = lookup(b.get('type'), _shared_registry)
        prepare_params = getattr(block_type, 'prepare_params', None)
        params = (prepare_params(b, model_dict.get('connections', [])) if prepare_params
                  else dict(b.get('params', {})))
        node = Node(str(b["id"]), b["type"], params)
        graph.add_node(node)

    # Build id->block lookup for per-instance port resolution
    block_by_id = {str(b["id"]): b for b in blocks}
    for c in model_dict.get("connections", []):
        src_block = block_by_id.get(str(c["from"]))
        dst_block = block_by_id.get(str(c["to"]))
        src_type = src_block.get("type", "") if src_block else ""
        dst_type = dst_block.get("type", "") if dst_block else ""
        from_port = _port_name(src_type, c.get('from_port', 0), 'out')
        to_port = _port_name(dst_type, c.get('to_port', 0), 'in')
        conn = Connection(str(c["from"]), from_port, str(c["to"]), to_port)
        graph.add_connection(conn)

    return graph


def _execute_generic_dataflow(model_dict, session_heap=None, on_plot=None, cancel_event=None, block_instances=None, on_flow=None, on_output=None):
    """Execute the outer graph and serialize its results."""
    graph = _build_generic_graph(model_dict)

    from shell.heap import SessionHeap
    from shell.signal_engine import SignalEngine
    heap = session_heap or SessionHeap()
    engine = SignalEngine(heap, _shared_registry, {'optimizer': _optimizer_factory}, block_instances)
    try:
        results = engine.execute(graph, on_plot=on_plot, cancel_event=cancel_event, on_flow=on_flow, on_output=on_output)
    finally:
        if session_heap is None:
            heap.close()

    # Serialize to the same format as numerical results
    serialized = {}
    for node_id, outputs in results.items():
        if "value" in outputs:
            serialized[node_id] = {"t": [0], "y": [outputs["value"]]}
        elif "params" in outputs:
            serialized[node_id] = {"t": [0], "y": [outputs["params"]]}
        elif "displayed" in outputs:
            serialized[node_id] = {"t": [0], "y": [outputs["displayed"]]}
        elif "_plot" in outputs:
            serialized[node_id] = outputs['_plot']
        elif "_artifacts" in outputs:
            final_val = outputs.get('J')
            serialized[node_id] = {"t": [0], "y": [final_val]}
            for inner_id, series_data in outputs['_artifacts'].get('series', {}).items():
                if series_data:
                    serialized[f"{node_id}/{inner_id}"] = series_data
        else:
            serialized[node_id] = {"t": [0], "y": [list(outputs.values())[0] if outputs else None]}

    reports = [dict(outputs['_report'], block_id=node_id) for node_id, outputs in results.items()
               if '_report' in outputs]
    return {"results": serialized, "n_steps": 1, "raw_results": results, "optimization": reports}


def _model_is_generic(model_dict):
    """Check that all outer blocks are present in the block catalogue."""
    blocks = model_dict.get("blocks", [])
    if not blocks:
        return False
    _validate_outer_subsystems(model_dict)
    types = {b.get('type') for b in blocks} - {IN1_TYPE, OUT1_TYPE}
    return all(lookup(block_type, _shared_registry) is not None for block_type in types)
