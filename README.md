# PavSim

**English** | [Русский](README.ru.md)

PavSim is a local visual application for modeling dynamic systems and tuning parameters. The outer diagram passes structured data between blocks; the dynamic system inside an Experiment uses scalar signals.

## Start

Python 3.12 and a modern browser are required. The Python application uses the standard library.

```bash
python3 -m venv .venv
.venv/bin/python -m shell.server --host 127.0.0.1 --port 8881
```

Open http://127.0.0.1:8881/. The server is intended for local use and has no authentication. Use EN/RU to change the interface language.

## Getting started

1. Place a Starter, Constant (structures), and Result Display on the outer canvas.
2. Connect Starter to Constant, then Constant to Result Display. Select a block and use F2 or Parameters to edit its settings, including the value and flow number.
3. Click Run. Numbered badges show flows at blocks. Use the toolbar to save or load diagrams.

For tuning, connect the Optimizer's p1/p2/p3 outputs to the corresponding Experiment inputs and connect the Experiment's J output to the Optimizer's J input. Connect a Starter to the Optimizer's start input. Double-click the Experiment to edit its internal dynamic system; set its time and solver parameters in the block settings. Double-click the Optimizer to open its log, or select it and press F2 for settings.

**Wire order matters:** outputs are delivered in connection order, depth first. For a live optimization graph, connect the graph before the branch that continues computation: p1 and p2 first to the graph, then to the Experiment; J first to the graph, then to the Optimizer; start first to graph reset, then to the Optimizer.

A Starter assigns a flow number. Use distinct numbers and separate Experiments for independent Optimizers. An Experiment does not combine inputs from different flows. Stop ends the session and releases its resources.

## Tests

The complete suite also requires Node.js:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests -v
```

## Limitations

- Numerical simulation uses fixed-step RK4 or Euler, configured in the Experiment.
- Diagrams with old calculation blocks are not supported by the new version; open them with an older PavSim release.
- Saving a diagram stores its JSON model, not run results or temporary session objects.
- User-defined Python numerical blocks run as trusted code.

The [block interface](docs/block-interface.md) and [session process](docs/session-process.md) documents describe the implementation in Russian.

[MIT license](LICENSE).
