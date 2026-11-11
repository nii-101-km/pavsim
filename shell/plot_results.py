"""Build graph output packets from simulation results."""

from .outer_graphs import OUTER_GRAPHS


def _collect_plots(model_dict, results):
    """Collect plot data for graph_* blocks from simulation results.

    Returns a dict keyed by block_id with plot packet format:
    {block_id: {"data": {t, y/outputs}, "config": {kind, params, labels, score_connected, axis}}}
    """
    plots = {}

    def collect(diagram, prefix=''):
        for block in diagram.get('blocks', []):
            key = prefix + str(block['id'])
            kind = block.get('type', '')
            if kind.startswith('graph_') and key in results:
                inputs = sorted(
                    [c for c in diagram.get('connections', []) if str(c['to']) == str(block['id'])],
                    key=lambda c: int(c.get('to_port', 0))
                )
                labels = [str(c['from']) + ':' + str(int(c.get('from_port', 0)) + 1) for c in inputs]
                params = dict(block.get('params', {}))
                outer = OUTER_GRAPHS.get(kind)
                plots[key] = {
                    'data': results[key],
                    'config': {
                        'kind': outer[1] if outer else 'xy_score' if kind == 'graph_xyz' else 'xy' if kind == 'graph_xy' else 'series',
                        'params': params,
                        'labels': labels,
                        'score_connected': any(int(c.get('to_port', 0)) == 2 for c in inputs),
                        'axis': 'signal' if outer else 't'
                    }
                }
            if block.get('internal'):
                collect(block['internal'], key + '/')
            # Numerical blocks contain an inner model with graph blocks
            if kind == 'numerical':
                inner_model = block.get('params', {}).get('model')
                if inner_model and isinstance(inner_model, dict):
                    collect(inner_model, str(block['id']) + '/')

    collect(model_dict)
    return plots
