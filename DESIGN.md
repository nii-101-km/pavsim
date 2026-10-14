# PavSim — Design Document

A minimal, standalone visual modeling environment for constructing and
executing block diagrams of dynamic systems, inspired by Scilab Xcos.

## 1. Goals and scope

**Goal.** A *functional simulator*, not just a drawing tool: the supported
blocks must execute with correct semantics, including states, feedback loops,
and numerical integration. Unsupported cases must be *explicitly identified*
rather than silently producing a (wrong) result.

**In scope (v1).**
- Scalar real-valued signals only.
- Fixed simulation step `h`.
- A single selectable integration method (RK4 default, Euler optional).
- Feedback loops that contain at least one stateful block (integrator or delay).
- Save/load of diagrams (JSON).
- A unified, extensible block library: every block is one Python file under
  `blocks/` (one block per file; the file's directory is its category). Users
  add blocks by dropping a file into a category directory — no core changes,
  no rebuild, no registration.

**Out of scope (v1).**
- Vector / multi-dimensional signals.
- Adaptive step sizing.
- Xcos (`.xcos`) file compatibility.
- Multiple simultaneous integration methods within one Engine run. Independent experiments may use different methods.

## 2. Technology choice

- **Python 3, standard library only.** No third-party dependencies, so the
  application is standalone and portable. The simulation core is pure Python
  and fully testable headlessly.
- **Frontend:** a single-page web app (HTML5 canvas) served by a small
  Python `http.server` JSON API. HTML5 canvas is well suited to drawing
  blocks, connections, and plots, and the whole stack uses only the standard
  library. (The original plan was a `tkinter` editor; `tkinter` is not
  available in the target environment, so a local web UI was chosen instead —
  see deviation V001. It is still a standalone local application with no
  external services.)

## 3. Architecture

```
blocks/          the unified block library (one block per file; directory = category)
  Sources/         constant.py, signal_generator.py
  Math/            addition.py, multiplication.py, gain.py
  Dynamics/        integrator.py, delay.py, first_order.py, second_order.py
  Nonlinear/       saturator.py
  Visualization/   graph_display.py
xcos_mini/
  core.py      Block base, Model, Engine, Library  (pure Python, testable)
  server.py    stdlib HTTP server + JSON API (list/simulate/save/load)
  web/         index.html, app.js, style.css  (canvas editor + plot)
models/          saved diagrams (JSON)
tests/           smoke.py, test_core.py (automated checks)
```

Separation of concerns:
- **core.py** owns all simulation semantics (block interface, model
  validation, execution order, integration, algebraic-loop policy, library
  loading). It has no UI dependency and is the single source of truth for
  correctness.
- **blocks/** defines every block as a `Block` subclass, one block per file,
  discovered recursively from disk by `Library` (the file's directory is its
  category). There is no separate built-in/custom registry.
- **server.py** is a thin adapter: it builds a `Model` from JSON, runs the
  `Engine`, and serializes results. It also serves the static web files and
  implements save/load.
- **web/** is a thin client: it edits the diagram, calls the API, and plots
  results. It contains no simulation logic.

## 4. Block interface

A block is a `Block` subclass that declares:

| attribute      | meaning                                            |
|----------------|----------------------------------------------------|
| `name`         | unique type name (used in save/load + palette)     |
| `n_inputs`     | number of input ports                              |
| `n_outputs`    | number of output ports                             |
| `parameters`   | dict of parameter name -> default value            |
| `state_kind`   | `"none"` / `"integrated"` / `"memory"`             |
| `description`  | human-readable text (shown in the GUI)             |

and implements:

- `compute(t, inputs, params, state) -> float` — the scalar output.
- For `state_kind == "integrated"`: `state_size(params)`,
  `initial_state(params)`, `derivative(t, inputs, params, state) -> [float]`.
- For `state_kind == "memory"`: `state_size(params)`,
  `initial_state(params)`, `update_memory(t, inputs, params, state) -> [float]`.

Each port carries a scalar real value. Multi-output blocks may return a list/tuple
with one independent scalar per output; a scalar output remains compatible with broadcast-style blocks. The engine wraps any exception a
block raises into a `BlockError` with the block id/name and time, so a faulty
block produces a clear diagnostic instead of a crash.

### The block library

All 61 blocks live in the unified filesystem library (`blocks/`), one block
per file, discovered from disk at startup and on every Refresh. There is no
built-in/custom distinction and no manual registration; the file's directory
is the block's category.

The table below lists representative basic blocks; see the guides in docs/ for
controllers, discrete elements, optimization, experiments and multi-input plots.

| name             | category      | in/out | state      | behaviour |
|------------------|---------------|--------|------------|-----------|
| `constant`       | Sources       | 0/1    | none       | outputs `value` |
| `signal_generator` | Sources     | 0/1    | none       | sine / square / ramp / step from time |
| `addition`       | Math          | 2/1    | none       | sum of two inputs |
| `multiplication` | Math          | 2/1    | none       | product of two inputs |
| `gain`           | Math          | 1/1    | none       | `gain * input` |
| `integrator`     | Dynamics      | 1/1    | integrated | `dx/dt = input`, output = state |
| `delay`          | Dynamics      | 1/1    | memory     | one-step (z^-1) delay |
| `first_order`    | Dynamics      | 1/1    | integrated | `dy/dt = (u - y)/tau` |
| `second_order`   | Dynamics      | 1/1    | integrated | `y''+2*zeta*omega0*y'+omega0^2*y = K*omega0^2*u` |
| `saturator`      | Nonlinear     | 1/1    | none       | clamps input to `[-limit, +limit]` |
| `graph_display`  | Visualization | 1/0    | none       | records its input for plotting |

## 5. Execution model

- **Fixed step.** The simulation advances in steps of `h` from `t=0` to
  exactly `t_end`, with a shortened final integration interval when necessary.
  Nominal `h` remains the discrete block configuration step.
- **Evaluation order per step.**
  1. Stateful blocks without direct feedthrough have their state-only outputs
     pre-filled first.
  2. Pure blocks and stateful blocks with direct feedthrough are evaluated in
     topological order (Kahn's algorithm over instantaneous dependencies).
  3. Integrated blocks' derivatives are computed (their inputs are now known).
- **Integration.** The integrated state vector is advanced with the selected
  method (RK4 by default, Euler optional). Memory blocks are updated once per
  step via `update_memory`.
- **Recording.** Every block's output is recorded at each step, producing a
  series per block for plotting.

## 6. Algebraic-loop policy

A feedback loop must break its instantaneous dependency through a state-only
output (for example, an integrator or one-sample delay). Statefulness alone
does not break a cycle when a block has direct feedthrough. An instantaneous cycle is an
*algebraic loop* and is **explicitly rejected** with an `AlgebraicLoopError`
that names the blocks in the cycle and explains how to fix it (add an
integrator or delay, or restructure). The model is not simulated in that case.

This is the core "identify unsupported cases rather than fake a result"
requirement: the engine detects the cycle during validation (before any
simulation) and raises a clear, actionable error.

## 7. Unified block library (discovery, identity, refresh)

The file system is the single source of truth for the block library. There is
one loader and no separate built-in/custom registries:

- **One block per file.** Each `.py` file under `blocks/` defines a `Block`
  subclass (e.g. `blocks/Nonlinear/saturator.py` for a non-stateful block,
  `blocks/Dynamics/integrator.py` for a stateful one). Files starting with
  `_` and `__pycache__` are skipped.
- **Recursive discovery.** `Library.load_blocks_dir` walks `blocks/`
  recursively; every `Block` subclass found is registered. The immediate
  parent directory of a file is its category (a file directly in the root
  falls under a category named after that root). Adding a valid block file to
  a category directory makes it discoverable after a refresh; removing a file
  removes it; nothing is ever recreated automatically.
- **Identity is independent of path.** A block's identifier is its `name`
  attribute, not its file path or category. Moving a block between categories
  changes only its category, never its identity, so saved diagrams keep
  loading and executing without migration.
- **Refresh.** `Library.reload_blocks_dir` clears the registry and re-scans
  disk, so added, moved, and removed files are all reflected with no stale
  registrations or duplicate entries. The editor's **Refresh** control calls
  this via `GET /api/library`; the open diagram is untouched.
- **Diagnostics.** A file that fails to import, or that defines no block, is
  recorded in `Library.load_errors` as `(relpath, message)` and reported in
  the status bar — one bad file does not prevent the app from starting or
  unrelated valid blocks from loading. A duplicate block identifier produces
  an explicit diagnostic (the first definition is kept). Missing blocks
  referenced by a saved diagram raise a clear `BlockError` naming the block.

Every block — including `constant`, `signal_generator`, and `graph_display` —
uses the same block contract and the same engine execution path; there are no
special numerical integration branches for ordinary block types. Experiment and
optimizer containers are scheduled outside Engine by experiments.py/optimization.py.

## 8. Save/load format

Diagrams are saved as JSON:

```json
{
  "blocks": [
    {"id": "b1", "type": "constant", "x": 0, "y": 0, "params": {"value": 1.0}}
  ],
  "connections": [
    {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0}
  ]
}
```

Human-readable, dependency-free, and sufficient for v1. `Model.to_dict()`
produces this shape; the server's `_build_model` reconstructs a `Model` from
it. A round-trip (save -> load -> save) is stable and covered by tests.

## 9. HTTP API (server.py)

| method | path                 | description |
|--------|----------------------|-------------|
| GET    | `/api/health`        | status + block count |
| GET    | `/api/blocks`        | list of block type descriptions |
| POST   | `/api/simulate`      | `{model, t_end, h, method}` -> results |
| GET    | `/api/models`        | list saved model names |
| POST   | `/api/save`          | `{name, model}` -> saved |
| GET    | `/api/load?name=X`   | `{name, model}` |
| DELETE | `/api/models?name=X` | delete a saved model |

Static files (the web app) are served from `web/`.

## 10. Verification

- `tests/smoke.py` — quick end-to-end sanity checks.
- `tests/test_core.py` — automated tests covering numerical correctness
  (integrator, feedback decay vs analytic, Euler vs RK4, delay, delay-feedback
  convergence, 2nd-order oscillator, signal generators, arithmetic, saturator,
  first-order low-pass incl. a stateful block inside a feedback loop,
  second-order step response vs analytic), the
  algebraic-loop policy (rejected vs accepted), save/load round-trip (incl.
  stateful blocks), error diagnostics (bad method/step/t_end, empty model,
  port range, multiple sources to one input, unknown type, non-scalar output,
  wrapped block exceptions, bad block-file reporting), and the unified block
  library (discovery of all 61 blocks, exactly one implementation per
  identifier, recursive category discovery, adding a new category + block
  without core changes, removing a block + refresh, relocating a block without
  changing its identifier, duplicate-identifier diagnostics, broken-file
  isolation, saved-diagram compatibility, and the GUI category hierarchy).

Run: `python3 -m unittest discover -s tests` (all pass).

## 11. PavSim 0.1.0 containers and endpoint policy

A Subsystem is expanded into the parent model with scoped IDs and preserved ports.
An Experiment instead runs a fresh internal Model/Engine with its own t_end/h/method,
three parameter terminals and a scalar completion J. Experiments are sequential;
optimizer trials are orchestrated outside block compute, not nested numerical runs.
See docs/experiments.md and docs/controller-optimization.md.

The output grid is 0, h, 2h, ... and exactly t_end. If necessary, only the final
integration interval is shortened. Every RK4 stage uses that interval's actual size.
Nominal block.step_size and prepare(h) stay unchanged. Memory commits once per
output sample, never at intermediate RK4 stages. z^-1 is a previous-sample delay;
Sample Hold keeps its configured period, and Transport Delay keeps its time-based
interpolation. Exact multiples do not produce a duplicate endpoint sample.

Static paths are URL-decoded and resolved through realpath, then checked with
commonpath against the resolved web directory. This also covers the index entry
point and symlinks. Invalid/non-finite temporal API parameters are client errors.
Compatibility data lives in tests/fixtures, independently of user models/.
