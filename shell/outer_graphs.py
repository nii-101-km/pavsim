"""External graphs accept structured numbers and an independent reset event."""
OUTER_GRAPHS = {
    'graph_outer': (('value',), 'series', 1),
    'graph_outer_series2': (('y1', 'y2'), 'series', 2),
    'graph_outer_series3': (('y1', 'y2', 'y3'), 'series', 3),
    'graph_outer_series4': (('y1', 'y2', 'y3', 'y4'), 'series', 4),
    'graph_outer_xy': (('x', 'y'), 'xy', 2),
    'graph_outer_xy_score': (('x', 'y', 'J'), 'xy_score', 2),
}
