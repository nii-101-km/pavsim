# PavSim 0.1.1

**English** | [Русский](README.ru.md)

**Parametric Analysis & Visual Simulation**

PavSim is a local application for visual modeling of dynamic systems,
transient response analysis, and parameter tuning. The interface runs in
a web browser, while a Python server performs the simulations.

## Features

- 61 block types: sources, arithmetic, continuous and discrete dynamics,
  logic, delays, controllers, visualization, and optimization.
- Fixed-step numerical simulation with RK4 and Euler.
- Scalar ports, signal branching, and independent block outputs.
- Proportional control through a Gain block; PI, PD, and PID controllers with
  separate coefficient inputs. The PID derivative is filtered;
  `filter_tau` must be positive.
- Subsystems with In1/Out1 terminals and independent Experiments with local
  `t_end`, `h`, and `method` settings.
- Tuning of up to three parameters using coordinate search, Nelder–Mead,
  numerical gradient descent, Hooke–Jeeves, or Polyak's heavy-ball method.
- Objectives: IAE, ISE, settling time, overshoot, and oscillation index.
- Single-signal plots, 2–4 series, XY plots, and XY plots annotated with
  `step | J`.
- JSON persistence for diagrams, block parameters, internal diagrams, and
  connection routes.

## Installation and startup

Tested on Linux x86_64 with CPython 3.12.3. The Python application uses only
the standard library; no third-party Python packages are required.
The minimum supported Python version has not yet been independently verified.
A modern web browser is required.

From the project root:

```bash
python3 -m venv .venv
.venv/bin/python xcos_mini/server.py --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The server is intended for local use and does
not provide authentication. Internal `xcos_mini` module names and block type
identifiers are retained for compatibility.

## Minimal example

The interface starts in English. Use **EN/RU** in the top bar to switch
languages without reloading the page. The choice is stored in localStorage
and restored next time; browser language settings do not change the default.
Plot windows use the same preference. If browser storage is unavailable,
switching still works for the current page. Internal identifiers below stay
the same in either language.

1. Select Constant (Константа, `constant`) in the library and click the
   canvas to place it. Double-click the block and set `value=1`.
2. Place Integrator (Интегратор, `integrator`) and Graph (График,
   `graph_display`) blocks.
3. Connect Constant → Integrator → Graph: press and hold a red output port,
   drag to a green input port, and release.
4. Set `t_end=1`, `h=0.01`, and RK4, then click **Run**.
5. Open the graph by double-clicking its block or following the result
   link. The expected response is `y(t)=t`.

You can also edit a selected block using **Parameters** (Параметры in Russian) or **F2**.
To save, enter a name and click **Save**. To load, select a name and click
**Load**.

The `examples/` directory contains a PI loop, a four-input PID controller,
a transport delay, a block-based optimizer, and an independent experiment
workspace. To open an example through **Load**, copy its JSON file into
`models/` under a new name. Do not overwrite existing user files.

## Experiments and optimization

An Experiment receives `p1/p2/p3`, runs its internal diagram with fresh
initial states, and returns the final objective value `J`. Connect the
Optimizer outputs to these parameter inputs and the Experiment's `J` output
back to the Optimizer input. Use the checkboxes and bounds fields to choose
active variables and their ranges. Inactive parameters retain their values.

Hooke–Jeeves supports `initial_step`, `pattern_step`, `shrink`, and
`tolerance` in the advanced settings string: `key=value; key=value`.
Random initial probes are disabled by default.

When an Experiment is present, the global time controls are hidden on the
outer workspace. Inside the Experiment, they show its local settings.
**Run** on the outer workspace performs parameter tuning; **Run** inside an
Experiment executes only that Experiment.

## Tests

The complete test suite also requires Node.js (tested with v18.19.1).

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/smoke.py
```

237 tests passed without skips in a clean Python environment. The suite
includes numerical tests, HTTP checks, Node.js harnesses, and static checks.
The test count alone does not establish that every browser interaction has
been verified.

## Limitations

- Fixed-step integration only; no adaptive solver or separate algebraic-loop
  solver.
- The time grid ends exactly at `t_end`. The final integration step is
  shortened when necessary. The nominal `h` and configured block sampling
  periods are preserved. A `z⁻¹` delay refers to the previous output sample;
  the last interval may be shorter than `h`. Transport delay remains defined
  in model time.
- No `.xcos` support, arbitrary vector-valued signals, or 3D plots.
  The internal `graph_xyz` type represents an XY plot with an objective
  value, not a 3D plot.
- An ordinary Subsystem has one input and one output; arbitrary nesting is
  not implemented.
- Experiments execute sequentially. Nested Experiments and Optimizers
  inside an Experiment are not supported.
- Plots belong to individual runs. The server keeps the last five result
  sets in memory. **Save** persists the model, not the result history.
  Global settings for an ordinary simulation are not stored in the diagram
  JSON; local Experiment settings are saved.
- Derivatives and delays require an appropriate choice of `h`. RK4 does
  not guarantee fourth-order accuracy for discrete events or discontinuous
  signals.
- Additional Python blocks run as trusted code, without a sandbox.
- Static files are restricted to the resolved `web/` directory, including
  symbolic-link checks. Authentication and a networked multiuser mode are
  not provided.

## Documentation

The following guides are currently in Russian:

- [Experiments and plots](docs/experiments.md).
- [Objectives, optimization methods, and tuning settings](docs/controller-optimization.md).
- [Calculation blocks and controllers](docs/simopt-calculation-blocks.md).
- [Release notes and verification for 0.1.0](docs/release-0.1.0.md).

[Release notes for 0.1.1](docs/release-0.1.1.md) describe the EN/RU update and its limitations.

[DESIGN.md](DESIGN.md) describes the architecture and time-grid semantics in English.

## License

MIT License. Copyright (c) 2026 nii-101. See [LICENSE](LICENSE) for the full text.
