"""Core simulation engine for xcos_mini.

Pure Python, standard library only. Fully testable headlessly.

Concepts
--------
Block      : base class; declares inputs/outputs/parameters and a state kind.
Model      : a set of block instances + connections + positions.
Engine     : validates the model (algebraic-loop policy) and runs the
             fixed-step simulation (RK4 or Euler for integrated state,
             per-step update for memory state), recording outputs.
Library    : filesystem-driven registry of block types; discovers all
             blocks recursively from a blocks/ directory (one file per
             block, categories from directory names).

State kinds
-----------
"none"       : pure function of (t, inputs, params). No state.
"integrated" : state evolves via derivative(); integrated with the selected
               method (RK4 default, Euler optional).
"memory"     : state updated discretely once per step via update_memory().

Algebraic-loop policy
---------------------
A feedback loop is valid only if it contains at least one stateful block
(integrated or memory). A cycle among purely non-stateful blocks is an
algebraic loop and is explicitly rejected with a clear diagnostic.
"""

from __future__ import annotations

import importlib.util
import math
import os
from collections import deque


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class BlockError(Exception):
    """Base error for block/model problems."""


class AlgebraicLoopError(BlockError):
    """A cycle among non-stateful blocks (no integrator/delay) was found."""

    def __init__(self, block_ids, names):
        self.block_ids = list(block_ids)
        self.names = list(names)
        super().__init__(
            "Algebraic loop detected among non-stateful blocks: "
            + " -> ".join(self.names)
            + ". A feedback loop must contain at least one integrator or delay "
            "block. Add an integrator or delay to break the loop, or "
            "restructure the diagram. This model is not simulated."
        )


# --------------------------------------------------------------------------- #
# Block base class
# --------------------------------------------------------------------------- #
class Block:
    """Base class for all blocks.

    Subclasses set the class attributes ``name``, ``n_inputs``, ``n_outputs``,
    ``parameters`` (defaults) and ``state_kind`` ("none"/"integrated"/"memory"),
    and implement ``compute``. Stateful blocks additionally implement
    ``state_size``/``initial_state`` and either ``derivative`` (integrated)
    or ``update_memory`` (memory).

    Each port carries a scalar real value. Multi-output blocks may return a list/tuple with one value per output; legacy scalar outputs are broadcast.
    """

    name = "block"
    n_inputs = 1
    n_outputs = 1
    parameters = {}          # name -> default value
    state_kind = "none"      # "none" | "integrated" | "memory"
    direct_feedthrough = False  # stateful output may also depend on current inputs
    description = ""         # human-readable description (shown in GUI)

    def __init__(self):
        self.params = dict(self.parameters)
        self.state = self.initial_state(self.params)

    # -- state ------------------------------------------------------------- #
    def state_size(self, params):
        return 0

    def initial_state(self, params):
        return [0.0] * self.state_size(params)

    # -- computation ------------------------------------------------------- #
    def compute(self, t, inputs, params, state):
        """Return the scalar output given time, inputs, params, state."""
        raise NotImplementedError

    def derivative(self, t, inputs, params, state):
        """Integrated blocks: return dstate (list of floats)."""
        raise NotImplementedError

    def update_memory(self, t, inputs, params, state):
        """Memory blocks: return new_state (list of floats)."""
        raise NotImplementedError

    # -- (de)serialization helpers ---------------------------------------- #
    def to_dict(self):
        return {
            "type": self.name,
            "params": dict(self.params),
        }


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class Model:
    """A set of block instances, connections, and positions.

    connections: list of (src_id, src_port, dst_id, dst_port)
    positions:   dict of block_id -> (x, y)
    """

    def __init__(self):
        self.blocks = {}
        self.connections = []
        self.positions = {}

    def add_block(self, block, block_id, x=0, y=0):
        self.blocks[block_id] = block
        self.positions[block_id] = (x, y)

    def add_connection(self, src_id, src_port, dst_id, dst_port):
        self.connections.append((src_id, src_port, dst_id, dst_port))

    # -- validation -------------------------------------------------------- #
    def validate(self):
        """Validate structure and the algebraic-loop policy. Raises BlockError."""
        if not self.blocks:
            raise BlockError("Model has no blocks.")
        for (src_id, src_port, dst_id, dst_port) in self.connections:
            if src_id not in self.blocks:
                raise BlockError(f"Connection source block '{src_id}' not found.")
            if dst_id not in self.blocks:
                raise BlockError(f"Connection destination block '{dst_id}' not found.")
            src_block = self.blocks[src_id]
            dst_block = self.blocks[dst_id]
            if src_port < 0 or src_port >= src_block.n_outputs:
                raise BlockError(
                    f"Source port {src_port} out of range for block '{src_id}' "
                    f"({src_block.name}, {src_block.n_outputs} output(s))."
                )
            if dst_port < 0 or dst_port >= dst_block.n_inputs:
                raise BlockError(
                    f"Destination port {dst_port} out of range for block '{dst_id}' "
                    f"({dst_block.name}, {dst_block.n_inputs} input(s))."
                )
        seen = set()
        for (src_id, src_port, dst_id, dst_port) in self.connections:
            key = (dst_id, dst_port)
            if key in seen:
                raise BlockError(
                    f"Input port {dst_port} of block '{dst_id}' has multiple "
                    f"connections; only one source per input is supported."
                )
            seen.add(key)
        for bid, block in self.blocks.items():
            for port in getattr(block, 'required_inputs', ()):
                if (bid, port) not in seen:
                    raise BlockError(f"Block '{bid}' ({block.name}) requires input port {port} to be connected.")
        self._detect_algebraic_loops()

    def _detect_algebraic_loops(self):
        stateful = {
            bid for bid, b in self.blocks.items()
            if b.state_kind != "none" and not b.direct_feedthrough
        }
        adj = {bid: set() for bid in self.blocks if bid not in stateful}
        for (src_id, _sp, dst_id, _dp) in self.connections:
            if src_id in adj and dst_id in adj:
                adj[src_id].add(dst_id)
        cycle = self._find_cycle(adj)
        if cycle:
            names = [self.blocks[bid].name for bid in cycle]
            raise AlgebraicLoopError(cycle, names)

    @staticmethod
    def _find_cycle(adj):
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {bid: WHITE for bid in adj}
        stack = []

        def dfs(u):
            color[u] = GRAY
            stack.append(u)
            for v in adj[u]:
                if color[v] == GRAY:
                    idx = stack.index(v)
                    return stack[idx:]
                if color[v] == WHITE:
                    res = dfs(v)
                    if res:
                        return res
            stack.pop()
            color[u] = BLACK
            return None

        for u in adj:
            if color[u] == WHITE:
                res = dfs(u)
                if res:
                    return res
        return None

    # -- (de)serialization ------------------------------------------------- #
    def to_dict(self):
        return {
            "blocks": [
                {
                    "id": bid,
                    "type": b.name,
                    "x": self.positions.get(bid, (0, 0))[0],
                    "y": self.positions.get(bid, (0, 0))[1],
                    "params": dict(b.params),
                }
                for bid, b in self.blocks.items()
            ],
            "connections": [
                {"from": s, "from_port": sp, "to": d, "to_port": dp}
                for (s, sp, d, dp) in self.connections
            ],
        }


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class Engine:
    """Runs the fixed-step simulation for a validated Model.

    Parameters
    ----------
    model : Model
    t_end : float   simulation end time
    h     : float   fixed step size
    method: str     "rk4" (default) or "euler"
    """

    METHODS = ("rk4", "euler")

    def __init__(self, model, t_end, h, method="rk4"):
        if method not in self.METHODS:
            raise BlockError(f"Unknown integration method '{method}'.")
        try:
            if isinstance(t_end, bool) or isinstance(h, bool):
                raise ValueError("boolean is not a time parameter")
            t_end, h = float(t_end), float(h)
        except (TypeError, ValueError, OverflowError) as exc:
            raise BlockError("t_end and h must be finite numbers.") from exc
        if not math.isfinite(t_end) or not math.isfinite(h):
            raise BlockError("t_end and h must be finite numbers.")
        if h <= 0:
            raise BlockError("Step size h must be positive.")
        if t_end < 0:
            raise BlockError("t_end must be non-negative.")
        if not math.isfinite(t_end / h):
            raise BlockError("t_end/h is too large.")
        self.model = model
        self.t_end = float(t_end)
        self.h = float(h)
        self.method = method
        self._setup()

    def _setup(self):
        model = self.model
        for bid, block in model.blocks.items():
            block.step_size = self.h
            prepare = getattr(block, "prepare", None)
            if prepare is not None:
                try:
                    prepare(self.h)
                except Exception as exc:
                    raise BlockError(f"Block '{bid}' ({block.name}) parameters: {exc}") from exc
        model.validate()
        self.integrated = [
            bid for bid, b in model.blocks.items() if b.state_kind == "integrated"
        ]
        self.memory = [
            bid for bid, b in model.blocks.items() if b.state_kind == "memory"
        ]
        self._build_order()
        # Always derive the initial state from the current params (not from a
        # possibly stale b.state), so parameter changes take effect.
        self.state = []
        for bid in self.integrated:
            b = model.blocks[bid]
            self.state.extend(b.initial_state(b.params))
        for bid in self.memory:
            b = model.blocks[bid]
            b.state = b.initial_state(b.params)

    def _build_order(self):
        model = self.model
        stateful = [bid for bid, b in model.blocks.items()
                    if b.state_kind != "none" and not b.direct_feedthrough]
        non_stateful = [bid for bid in model.blocks if bid not in stateful]
        adj = {bid: set() for bid in non_stateful}
        indeg = {bid: 0 for bid in non_stateful}
        for (src_id, _sp, dst_id, _dp) in model.connections:
            if src_id in adj and dst_id in adj:
                if dst_id not in adj[src_id]:
                    adj[src_id].add(dst_id)
                    indeg[dst_id] += 1
        queue = deque(bid for bid in non_stateful if indeg[bid] == 0)
        topo = []
        while queue:
            u = queue.popleft()
            topo.append(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
        if len(topo) != len(non_stateful):
            stuck = [bid for bid in non_stateful if indeg[bid] > 0]
            raise AlgebraicLoopError(stuck, [model.blocks[bid].name for bid in stuck])
        self.order = stateful + topo

    def _gather_inputs(self, bid, outputs):
        model = self.model
        b = model.blocks[bid]
        inputs = [0.0] * b.n_inputs
        for (src_id, src_port, dst_id, dst_port) in model.connections:
            if dst_id == bid:
                value = outputs[src_id]
                inputs[dst_port] = value[src_port] if isinstance(value, tuple) else value
        return inputs

    def _evaluate(self, t, state):
        """Evaluate the network at time t with integrated state.

        State-only outputs are pre-filled first. Pure functions and stateful
        blocks with direct feedthrough are then evaluated in dependency order.
        Finally all integrated derivatives use the same global RK4 stage.

        Returns (outputs: dict block_id->float, derivs: list of floats).
        """
        model = self.model
        outputs = {}

        def _compute(bid, inputs):
            b = model.blocks[bid]
            try:
                out = b.compute(t, inputs, b.params, b.state)
            except BlockError:
                raise
            except Exception as exc:  # custom block failure -> clear diagnostic
                raise BlockError(
                    f"Block '{bid}' ({b.name}) failed at t={t}: {exc!r}"
                ) from exc
            values = out if isinstance(out, (list, tuple)) else [out]
            if isinstance(out, (list, tuple)) and (b.n_outputs <= 1 or len(values) != b.n_outputs):
                raise BlockError(f"Block '{bid}' ({b.name}) returned non-scalar output or wrong output count {out!r}.")
            if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values):
                raise BlockError(f"Block '{bid}' ({b.name}) returned non-scalar output {out!r}.")
            if any(not math.isfinite(float(v)) for v in values):
                raise BlockError(f"Block '{bid}' ({b.name}) returned a non-finite value at t={t}.")
            return tuple(float(v) for v in values) if isinstance(out, (list, tuple)) else float(out)

        # 1) pre-fill stateful blocks' outputs (state-based)
        offset = 0
        for bid in self.integrated:
            b = model.blocks[bid]
            size = b.state_size(b.params)
            b.state = state[offset:offset + size]
            offset += size
            if not b.direct_feedthrough:
                outputs[bid] = _compute(bid, [0.0] * b.n_inputs)
        for bid in self.memory:
            b = model.blocks[bid]
            if not b.direct_feedthrough:
                outputs[bid] = _compute(bid, [0.0] * b.n_inputs)

        # 2) evaluate non-stateful blocks in topological order
        for bid in self.order:
            if bid in outputs:
                continue
            outputs[bid] = _compute(bid, self._gather_inputs(bid, outputs))

        # 3) compute derivatives for integrated blocks (inputs now known)
        derivs = []
        for bid in self.integrated:
            b = model.blocks[bid]
            inputs = self._gather_inputs(bid, outputs)
            try:
                d = b.derivative(t, inputs, b.params, b.state)
            except Exception as exc:
                raise BlockError(
                    f"Block '{bid}' ({b.name}) derivative failed at t={t}: {exc!r}"
                ) from exc
            derivs.extend(float(x) for x in d)
        return outputs, derivs

    def _integrate(self, t, state, h):
        n = len(state)
        if n == 0:
            return state
        if self.method == "euler":
            _, k1 = self._evaluate(t, state)
            return [state[i] + h * k1[i] for i in range(n)]
        # RK4
        _, k1 = self._evaluate(t, state)
        s2 = [state[i] + 0.5 * h * k1[i] for i in range(n)]
        _, k2 = self._evaluate(t + 0.5 * h, s2)
        s3 = [state[i] + 0.5 * h * k2[i] for i in range(n)]
        _, k3 = self._evaluate(t + 0.5 * h, s3)
        s4 = [state[i] + h * k3[i] for i in range(n)]
        _, k4 = self._evaluate(t + h, s4)
        return [
            state[i] + (h / 6.0) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i])
            for i in range(n)
        ]

    def run(self):
        """Run the simulation. Returns a dict block_id -> list of (t, value)."""
        model = self.model
        ratio = self.t_end / self.h
        nearest = round(ratio)
        # Avoid an extra microscopic step for floating-point representations
        # of exact multiples. All other runs finish with a shortened last step.
        n_steps = nearest if (nearest > 0 or self.t_end == 0) and math.isclose(
            ratio, nearest, rel_tol=0, abs_tol=1e-12) else math.ceil(ratio)
        if self.t_end > 0:
            n_steps = max(1, n_steps)
        results = {bid: [] for bid in model.blocks}
        previous_t = 0.0
        for step in range(n_steps + 1):
            t = self.t_end if step == n_steps else step * self.h
            if step > 0 and self.integrated:
                self.state = self._integrate(previous_t, self.state, t - previous_t)
            outputs, _ = self._evaluate(t, self.state)
            # update memory blocks once per step
            for bid in self.memory:
                b = model.blocks[bid]
                inputs = self._gather_inputs(bid, outputs)
                try:
                    b.state = b.update_memory(t, inputs, b.params, b.state)
                except Exception as exc:
                    raise BlockError(
                        f"Block '{bid}' ({b.name}) memory update failed at t={t}: {exc!r}"
                    ) from exc
            for bid in model.blocks:
                results[bid].append((t, outputs[bid]))
            previous_t = t
        return results


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #
class Library:
    """Filesystem-driven registry of block types.

    The single source of truth for the block library is a directory tree
    (``blocks/``). Each ``.py`` file defines one or more ``Block`` subclasses;
    the immediate parent directory of a file is its category. Discovery is
    recursive, so adding a valid block file to a category directory makes it
    available after a refresh, and removing a file removes it. There is no
    separate built-in vs. custom registry and no manual per-block registration.

    Load errors are captured and reported (not raised), so one bad file does
    not prevent the app from starting or unrelated valid blocks from loading.
    """

    def __init__(self, blocks_dir=None):
        self._types = {}
        self.load_errors = []      # list of (relpath, message)
        self.file_blocks = {}      # abspath -> [block names] (UI metadata)
        self.block_category = {}   # block name -> category name
        self._blocks_dir = None
        if blocks_dir:
            self.load_blocks_dir(blocks_dir)

    def register(self, cls, category=None, source=None):
        """Register a single Block subclass.

        A duplicate identifier (same ``name`` already registered) produces an
        explicit diagnostic and keeps the first definition; it does not raise.
        """
        if not (isinstance(cls, type) and issubclass(cls, Block) and cls is not Block):
            raise BlockError(f"{cls!r} is not a Block subclass.")
        if not cls.name or cls.name == "block":
            raise BlockError(f"Block class {cls.__name__} must set a unique 'name'.")
        if cls.name in self._types:
            prev_src = getattr(self._types[cls.name], "_source_file", "built-in")
            self.load_errors.append((
                source or "unknown",
                f"duplicate block identifier '{cls.name}' "
                f"(already defined by {prev_src}); keeping the first",
            ))
            return cls
        self._types[cls.name] = cls
        if category is not None:
            self.block_category[cls.name] = category
        return cls

    def names(self):
        return sorted(self._types.keys())

    def get(self, name):
        if name not in self._types:
            raise BlockError(f"Unknown block type '{name}'.")
        return self._types[name]

    def instantiate(self, name):
        return self.get(name)()

    def describe(self):
        out = []
        for name in self.names():
            cls = self._types[name]
            out.append({
                "name": name,
                "class": cls.__name__,
                "category": self.block_category.get(name, ""),
                "n_inputs": cls.n_inputs,
                "n_outputs": cls.n_outputs,
                "state_kind": cls.state_kind,
                "parameters": dict(cls.parameters),
                "description": cls.description,
                "parameter_labels": dict(getattr(cls, "parameter_labels", {})),
                "parameter_choices": dict(getattr(cls, "parameter_choices", {})),
                "display_name": getattr(cls, 'display_name', name),
                "input_labels": list(getattr(cls, 'input_labels',
                    ['u'] if cls.n_inputs == 1 else [f'u{i+1}' for i in range(cls.n_inputs)])),
                "output_labels": list(getattr(cls, 'output_labels',
                    ['y'] if cls.n_outputs == 1 else [f'y{i+1}' for i in range(cls.n_outputs)])),
            })
        return out

    def categories(self):
        """Ordered mapping of category name -> sorted list of block names.

        Categories are derived from directory names (the immediate parent of a
        block file). Blocks placed directly in the root directory fall under a
        category named after that root directory.
        """
        cats = {}
        for name in self.names():
            cat = self.block_category.get(name, "Blocks")
            cats.setdefault(cat, []).append(name)
        return {k: sorted(v) for k, v in sorted(cats.items())}

    def load_blocks_dir(self, directory):
        """Recursively load all blocks from ``directory`` (the unified loader).

        The file system is the single source of truth: any ``.py`` file under
        the directory (including sub-folders) that defines ``Block`` subclasses
        is registered. The immediate parent directory of a file is its category.
        Files starting with ``_`` and ``__pycache__`` are skipped. Load errors
        are recorded (not raised) so one bad file does not prevent the app from
        starting or unrelated valid blocks from loading.
        """
        if not os.path.isdir(directory):
            return
        self._blocks_dir = os.path.abspath(directory)
        for dirpath, dirnames, filenames in os.walk(directory):
            # Do not descend into hidden / cache directories.
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("_"))
            for fname in sorted(filenames):
                if not fname.endswith(".py") or fname.startswith("_"):
                    continue
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, directory)
                parts = rel.split(os.sep)
                category = (parts[0] if len(parts) > 1
                            else os.path.basename(os.path.normpath(directory)))
                modname = "xcos_mini_block_" + rel.replace(os.sep, "_").replace(".", "_")
                names = []
                try:
                    spec = importlib.util.spec_from_file_location(modname, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    found = 0
                    for attr in vars(module).values():
                        if isinstance(attr, type) and issubclass(attr, Block) and attr is not Block:
                            attr._source_file = rel
                            self.register(attr, category=category, source=rel)
                            names.append(attr.name)
                            found += 1
                    if found == 0:
                        self.load_errors.append((rel, "no Block subclass defined"))
                except Exception as exc:
                    self.load_errors.append((rel, f"{exc!r}"))
                self.file_blocks[os.path.abspath(path)] = names

    def reload_blocks_dir(self, directory):
        """Re-scan the blocks directory, replacing all previously loaded blocks.

        This lets the UI pick up newly added, moved, or removed block files
        without a full server restart. It clears the registry first so there are
        no stale registrations or duplicate entries, then re-discovers from disk.
        It only touches the registry metadata, not the simulation engine.
        """
        self._types = {}
        self.file_blocks = {}
        self.block_category = {}
        self.load_errors = []
        self.load_blocks_dir(directory)
