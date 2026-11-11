"""Data graph for the shell: nodes, ports, connections, validation, topological sort.

This module is part of the universal data-graph shell. It does NOT import
any numerical simulation engine. The graph is a DAG of data nodes connected
by named ports.
"""

from __future__ import annotations

from collections import deque


class GraphError(Exception):
    """Base error for data graph problems."""


class CycleError(GraphError):
    """A cycle was detected in the data graph."""

    def __init__(self, cycle):
        self.cycle = list(cycle)
        super().__init__(
            "Cycle detected in data graph: " + " -> ".join(self.cycle)
        )


class PortError(GraphError):
    """Port connection error (invalid port, duplicate input, etc.)."""


class MissingInputError(GraphError):
    """A required input port is not connected."""


class Port:
    """A named port on a node."""

    def __init__(self, name, direction, type_hint=None):
        self.name = name
        self.direction = direction  # "input" or "output"
        self.type_hint = type_hint  # optional: "number", "dict", "any"

    def to_dict(self):
        d = {"name": self.name, "direction": self.direction}
        if self.type_hint:
            d["type"] = self.type_hint
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], d["direction"], d.get("type"))


class Node:
    """A node in the data graph."""

    def __init__(self, node_id, node_type, params=None, x=0, y=0):
        self.id = node_id
        self.type = node_type
        self.params = params or {}
        self.x = x
        self.y = y
        self.inputs = []   # list of Port
        self.outputs = []  # list of Port
        self._permissive = False  # skip port name validation (executor-backed)

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "params": dict(self.params),
            "x": self.x,
            "y": self.y,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
        }

    @classmethod
    def from_dict(cls, d):
        node = cls(d["id"], d["type"], d.get("params"), d.get("x", 0), d.get("y", 0))
        node.inputs = [Port.from_dict(p) for p in d.get("inputs", [])]
        node.outputs = [Port.from_dict(p) for p in d.get("outputs", [])]
        return node


class Connection:
    """A connection between two ports."""

    def __init__(self, from_node, from_port, to_node, to_port):
        self.from_node = from_node
        self.from_port = from_port  # port name
        self.to_node = to_node
        self.to_port = to_port      # port name

    def to_dict(self):
        return {
            "from": self.from_node,
            "from_port": self.from_port,
            "to": self.to_node,
            "to_port": self.to_port,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["from"], d["from_port"], d["to"], d["to_port"])


class DataGraph:
    """A directed acyclic graph of data nodes."""

    def __init__(self):
        self.nodes = {}       # id -> Node
        self.connections = [] # list of Connection

    def add_node(self, node):
        if node.id in self.nodes:
            raise GraphError(f"Node '{node.id}' already exists.")
        self.nodes[node.id] = node

    def remove_node(self, node_id):
        if node_id not in self.nodes:
            raise GraphError(f"Node '{node_id}' not found.")
        del self.nodes[node_id]
        self.connections = [
            c for c in self.connections
            if c.from_node != node_id and c.to_node != node_id
        ]

    def add_connection(self, conn):
        self.connections.append(conn)

    def remove_connection(self, conn):
        self.connections.remove(conn)

    def get_input_connections(self, node_id):
        """Return connections where to_node == node_id."""
        return [c for c in self.connections if c.to_node == node_id]

    def get_output_connections(self, node_id):
        """Return connections where from_node == node_id."""
        return [c for c in self.connections if c.from_node == node_id]

    def validate(self, *, allow_cycles=False):
        """Validate the graph structure. Raises GraphError."""
        if not self.nodes:
            raise GraphError("Graph has no nodes.")

        for conn in self.connections:
            if conn.from_node not in self.nodes:
                raise GraphError(f"Connection source node '{conn.from_node}' not found.")
            if conn.to_node not in self.nodes:
                raise GraphError(f"Connection target node '{conn.to_node}' not found.")

            src_node = self.nodes[conn.from_node]
            dst_node = self.nodes[conn.to_node]

            if not src_node._permissive:
                if not any(p.name == conn.from_port and p.direction == "output" for p in src_node.outputs):
                    raise PortError(
                        f"Output port '{conn.from_port}' not found on node '{conn.from_node}' ({src_node.type})."
                    )
            if not dst_node._permissive:
                if not any(p.name == conn.to_port and p.direction == "input" for p in dst_node.inputs):
                    raise PortError(
                        f"Input port '{conn.to_port}' not found on node '{conn.to_node}' ({dst_node.type})."
                    )

        seen = set()
        for conn in self.connections:
            key = (conn.to_node, conn.to_port)
            if key in seen:
                raise PortError(
                    f"Input port '{conn.to_port}' of node '{conn.to_node}' has multiple connections."
                )
            seen.add(key)

        if not allow_cycles:
            self._detect_cycles()

    def _detect_cycles(self):
        """Detect cycles using DFS. Raises CycleError."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        stack = []

        def dfs(u):
            color[u] = GRAY
            stack.append(u)
            for conn in self.connections:
                if conn.from_node == u:
                    v = conn.to_node
                    if color[v] == GRAY:
                        idx = stack.index(v)
                        raise CycleError(stack[idx:])
                    if color[v] == WHITE:
                        dfs(v)
            stack.pop()
            color[u] = BLACK

        for nid in self.nodes:
            if color[nid] == WHITE:
                dfs(nid)

    def topological_order(self):
        """Return nodes in topological order (Kahn's algorithm)."""
        indeg = {nid: 0 for nid in self.nodes}
        adj = {nid: [] for nid in self.nodes}
        for conn in self.connections:
            adj[conn.from_node].append(conn.to_node)
            indeg[conn.to_node] += 1

        queue = deque(nid for nid in self.nodes if indeg[nid] == 0)
        order = []
        while queue:
            u = queue.popleft()
            order.append(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)

        if len(order) != len(self.nodes):
            stuck = [nid for nid in self.nodes if indeg[nid] > 0]
            raise CycleError(stuck)

        return order

    def to_dict(self):
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "connections": [c.to_dict() for c in self.connections],
        }

    @classmethod
    def from_dict(cls, d):
        graph = cls()
        for nd in d.get("nodes", []):
            graph.add_node(Node.from_dict(nd))
        for cd in d.get("connections", []):
            graph.add_connection(Connection.from_dict(cd))
        return graph
