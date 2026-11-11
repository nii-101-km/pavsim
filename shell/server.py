"""HTTP server for the data graph shell — adapted legacy interface.

Serves the xcos_mini/web/ legacy UI and provides the full legacy JSON API.
Engine-specific operations are routed through the NumericalEngineAdapter in
engines/numerical.py. The server itself does NOT import xcos_mini.

Endpoints:
- GET    /api/health
- GET    /api/blocks
- GET    /api/library
- GET    /api/models
- GET    /api/load?name=X
- GET    /api/plot?run=X&block=Y
- GET    /api/ownership?name=X
- POST   /api/simulate
- POST   /api/save
- POST   /api/optimize
- POST   /api/invoke
- DELETE /api/models?name=X

Ownership rule:
  A model with in1_terminal or out1_terminal blocks is EXTERNALLY CONTROLLED.
  It cannot be run via /api/simulate. Use /api/invoke with all required inputs.
  A model with NO declared external ports is STANDALONE and can run.

Generic dataflow execution (shell built-in nodes) works without the numerical
engine. The shell delivers structured signals to blocks through their interfaces.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

# Project root (parent of shell/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "shell" / "web"
BLOCKS_DIR = PROJECT_ROOT / "blocks"
MODELS_DIR = PROJECT_ROOT / "models"

# Ensure project root is on path for imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Engine adapter (optional)
# ---------------------------------------------------------------------------
# Check for --no-engines in sys.argv BEFORE importing the engine module.
# This ensures the flag works even though it's parsed in __main__ below.
_no_engines_flag = (
    os.environ.get("PAVSIM_NO_ENGINES") == "1"
    or "--no-engines" in sys.argv
)

_numerical_adapter = None
if not _no_engines_flag:
    try:
        from engines.numerical import NumericalEngineAdapter
        _numerical_adapter = NumericalEngineAdapter(blocks_dir=str(BLOCKS_DIR))
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Shared executor registry (populated with available executors)
# ---------------------------------------------------------------------------
from shell.registry import ExecutorRegistry
from shell.heap import InvalidReference
from shell.cancellation import SessionCancelled
from shell.session_process import SessionProcess, SessionProcesses
from shell.graph import GraphError
from shell.outer_graphs import OUTER_GRAPHS
from shell.live_results import LiveResults
from shell.plot_results import _collect_plots

SESSION_HEAPS = SessionProcesses()

# ---------------------------------------------------------------------------
# Shell built-in dataflow nodes (always available, no engine required)
# ---------------------------------------------------------------------------
BUILTIN_TYPES = {"starter", "input_value", "param_assembler", "param_splitter", "result_display", "graph_outer", "in1_terminal", "out1_terminal"}
BUILTIN_TYPES.update(OUTER_GRAPHS)


def _shell_builtin_blocks():
    """Collect the palette descriptions owned by the blocks."""
    from shell.blocks.catalog import BLOCK_TYPES
    from shell.blocks.graph import GraphBlock

    graphs = [GraphBlock.descriptor(name) for name in OUTER_GRAPHS if name != 'graph_outer']
    names = ('starter', 'graph_outer', 'input_value', 'param_assembler', 'param_splitter', 'result_display')
    common = [GraphBlock.descriptor(name) if name == 'graph_outer' else BLOCK_TYPES[name].descriptor()
              for name in names]
    terminals = [{'name': 'in1_terminal',
      'class': 'In1Terminal',
      'category': 'Interface',
      'n_inputs': 0,
      'n_outputs': 1,
      'state_kind': 'none',
      'parameters': {'name': 'input_1', 'mapping': ''},
      'description': 'External input port. Declares this model as externally controlled.',
      'parameter_labels': {'name': 'Port Name', 'mapping': 'Maps to (block_id.param)'},
      'parameter_choices': {},
      'display_name': 'In1 (External Input)',
      'input_labels': [],
      'output_labels': ['value']},
     {'name': 'out1_terminal',
      'class': 'Out1Terminal',
      'category': 'Interface',
      'n_inputs': 1,
      'n_outputs': 0,
      'state_kind': 'none',
      'parameters': {'name': 'output_1', 'mapping': ''},
      'description': 'External output port. Declares this model as externally controlled.',
      'parameter_labels': {'name': 'Port Name', 'mapping': 'Maps to (block_id)'},
      'parameter_choices': {},
      'display_name': 'Out1 (External Output)',
      'input_labels': ['value'],
      'output_labels': []}]
    return graphs + common + terminals


def _typed_experiment_block():
    from engines.typed_experiment import TypedExperimentExecutor
    return TypedExperimentExecutor.descriptor()


def _optimizer_block():
    from shell.blocks.optimizer import OptimizerBlock
    return OptimizerBlock.descriptor()




# ---------------------------------------------------------------------------
# Unified library (shell + engine sections, context metadata)
# ---------------------------------------------------------------------------
_LIB_LOCK = threading.Lock()
_unified_cache = None

# Context rules: which blocks are placeable in which context.
# "outer" = common canvas (top-level), "numerical" = inside a numerical block.
_BLOCK_CONTEXTS = {
    # Shell builtins (outer only)
    "input_value": ["outer"],
    "starter": ["outer"],
    "param_assembler": ["outer"],
    "param_splitter": ["outer"],
    "result_display": ["outer"],
    "graph_outer": ["outer"],
    "typed_experiment": ["outer"],
    # Optimization blocks (outer only)
    "optimizer": ["outer"],
    "objective": ["numerical"],
    # Subsystems belong to the dynamic-system engine.
    "subsystem": ["numerical"],
    # Terminals (numerical only)
    "in1_terminal": ["numerical"],
    "out1_terminal": ["numerical"],
}
_BLOCK_CONTEXTS.update({name: ['outer'] for name in OUTER_GRAPHS})

def _unified_library(force_reload=False):
    """Build (or return cached) unified library tree with context metadata.

    Returns:
        {
            "tree": [ {name, type, blocks, section, contexts}, ... ],
            "block_contexts": {block_name: [contexts], ...},
            "engine_available": bool,
            "load_errors": [ [file, message], ... ],
        }
    """
    global _unified_cache
    with _LIB_LOCK:
        if _unified_cache is not None and not force_reload:
            return _unified_cache

        tree = []
        block_contexts = dict(_BLOCK_CONTEXTS)
        engine_available = False
        load_errors = []

        # Shell section (outer context)
        tree.append({
            "name": "Shell",
            "type": "category",
            "blocks": ["starter", "input_value", "param_assembler", "param_splitter", "result_display", *OUTER_GRAPHS],
            "section": "shell",
            "contexts": ["outer"],
        })
        tree.append({
            "name": "Computation",
            "type": "category",
            "blocks": ["typed_experiment"],
            "section": "shell",
            "contexts": ["outer"],
        })
        tree.append({
            "name": "Optimization",
            "type": "category",
            "blocks": ["optimizer"],
            "section": "shell",
            "contexts": ["outer"],
        })

        # Numerical section (engine blocks)
        if _numerical_adapter and _numerical_adapter.available:
            engine_available = True
            if force_reload:
                _numerical_adapter.reload_blocks()
            engine_tree = _numerical_adapter.get_library_tree()
            load_errors = _numerical_adapter.get_load_errors()

            # Interface (terminals) first
            tree.append({
                "name": "Interface",
                "type": "category",
                "blocks": ["in1_terminal", "out1_terminal"],
                "section": "numerical",
                "contexts": ["numerical"],
            })

            # The optimizer belongs to the shell; the scalar objective stays inside.
            for node in engine_tree:
                if node["name"] == "Optimization":
                    tree.append({"name": "Optimization", "type": "category",
                                 "blocks": ["objective"], "section": "numerical",
                                 "contexts": ["numerical"]})
                    continue
                node_blocks = [name for name in node['blocks'] if name != 'experiment']
                if not node_blocks:
                    continue
                tree.append({
                    "name": node["name"],
                    "type": "category",
                    "blocks": node_blocks,
                    "section": "numerical",
                    "contexts": ["numerical"],
                })
                # Mark all engine blocks as numerical context (unless already set)
                for b in node_blocks:
                    if b not in block_contexts:
                        block_contexts[b] = ["numerical"]

        result = {
            "tree": tree,
            "block_contexts": block_contexts,
            "engine_available": engine_available,
            "load_errors": load_errors,
        }
        _unified_cache = result
        return result







# ---------------------------------------------------------------------------
# Ownership rule helpers
# ---------------------------------------------------------------------------
IN1_TYPE = "in1_terminal"
OUT1_TYPE = "out1_terminal"


def _find_external_ports(blocks):
    """Find in1_terminal/out1_terminal blocks in a list of blocks."""
    inputs = [b for b in blocks if b.get("type") == IN1_TYPE]
    outputs = [b for b in blocks if b.get("type") == OUT1_TYPE]
    return inputs, outputs


def _model_has_external_ports(model_dict):
    """Check if a model dict declares external ports at its top level."""
    blocks = model_dict.get("blocks", [])
    inputs, outputs = _find_external_ports(blocks)
    return len(inputs) > 0 or len(outputs) > 0


def _get_external_interface(model_dict):
    """Get the external interface of a model."""
    blocks = model_dict.get("blocks", [])
    inputs, outputs = _find_external_ports(blocks)

    if not inputs and not outputs:
        return {
            "mode": "standalone",
            "inputs": [],
            "outputs": [],
            "explanation": "No external ports declared. This model can run internally.",
        }

    in_list = [{"id": str(b["id"]), "name": b.get("params", {}).get("name", f"input_{i+1}")} for i, b in enumerate(inputs)]
    out_list = [{"id": str(b["id"]), "name": b.get("params", {}).get("name", f"output_{i+1}")} for i, b in enumerate(outputs)]

    return {
        "mode": "externally_controlled",
        "inputs": in_list,
        "outputs": out_list,
        "explanation": (
            f"This model declares {len(in_list)} external input(s) and "
            f"{len(out_list)} external output(s). It is externally controlled: "
            f"internal execution is prohibited. Use /api/invoke with all required inputs."
        ),
    }


# ---------------------------------------------------------------------------
# Generic dataflow execution (shell built-in nodes only)
# ---------------------------------------------------------------------------
# Port name mapping for shell built-in nodes (legacy UI uses numeric indices)
from shell.session_runtime import (
    _port_name, _build_generic_graph,
    _execute_generic_dataflow, _model_is_generic, _shared_registry, _optimizer_factory,
)


def _execute_session_dataflow(model, session, on_plot, on_flow=None):
    """Execute via the session worker; anonymous API calls get a temporary worker."""
    if session is not None:
        return session.run(model, on_plot, on_flow)
    temporary = SessionProcess()
    try:
        if temporary.receive(10).get('event') != 'ready':
            raise RuntimeError('Процесс сессии не готов.')
        return temporary.run(model, on_plot, on_flow)
    finally:
        temporary.close()








# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
LIB_LOCK = threading.Lock()
LIVE_RESULTS = LiveResults(_collect_plots)


class Handler(BaseHTTPRequestHandler):
    server_version = "PavSimShell/1.0"

    # -- helpers ----------------------------------------------------------- #
    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype):
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt, *args):
        sys.stderr.write("[PavSimShell] " + (fmt % args) + "\n")

    # -- routing ----------------------------------------------------------- #
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/":
                path = "/index.html"
            if not path.startswith("/api/"):
                # static file from xcos_mini/web/
                rel = unquote(path).lstrip("/")
                allowed = os.path.realpath(str(WEB_DIR))
                full = os.path.realpath(os.path.join(allowed, rel))
                if os.path.commonpath([allowed, full]) != allowed:
                    return self._send_json({"error": "forbidden"}, 403)
                ctype = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".json": "application/json",
                    ".svg": "image/svg+xml",
                }.get(os.path.splitext(full)[1], "application/octet-stream")
                return self._send_file(Path(full), ctype)

            if path == "/api/health":
                engine_available = bool(_numerical_adapter and _numerical_adapter.available)
                blocks = []
                if _numerical_adapter and _numerical_adapter.available:
                    blocks = [b["name"] for b in _numerical_adapter.get_blocks()]
                return self._send_json({
                    "status": "ok",
                    "engine_available": engine_available,
                    "blocks": blocks,
                    "load_errors": _numerical_adapter.get_load_errors() if _numerical_adapter and _numerical_adapter.available else [],
                })

            if path == "/api/blocks":
                blocks = list(_shell_builtin_blocks())
                if _numerical_adapter and _numerical_adapter.available:
                    blocks.append(_typed_experiment_block())
                    blocks.append(_optimizer_block())
                    blocks.extend(b for b in _numerical_adapter.get_blocks()
                                  if b['name'] not in ('optimizer', 'experiment'))
                return self._send_json({"blocks": blocks})

            if path == "/api/models":
                names = []
                if MODELS_DIR.is_dir():
                    names = sorted(
                        f.name[:-5] for f in MODELS_DIR.iterdir()
                        if f.name.endswith(".json") and not f.name.startswith(".")
                    )
                return self._send_json({"models": names})

            if path == "/api/load":
                name = qs.get("name", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    return self._send_json({"error": "invalid name"}, 400)
                full = MODELS_DIR / (name + ".json")
                if not full.is_file():
                    return self._send_json({"error": "not found"}, 404)
                model = json.loads(full.read_text("utf-8"))
                return self._send_json({"name": name, "model": model})

            if path == "/api/library":
                data = _unified_library()
                return self._send_json(data)

            if path == "/api/numerical/library":
                if not (_numerical_adapter and _numerical_adapter.available):
                    return self._send_json({"error": "Numerical engine not available"}, 503)
                with LIB_LOCK:
                    _numerical_adapter.reload_blocks()
                    tree = _numerical_adapter.get_library_tree()
                    load_errors = _numerical_adapter.get_load_errors()
                return self._send_json({"tree": tree, "load_errors": load_errors})

            if path == "/api/plot":
                packet = LIVE_RESULTS.get(qs.get('run', [''])[0], 'plots', qs.get('block', [''])[0])
                if packet is None:
                    return self._send_json({"error": "Plot data unavailable. Run the simulation again."}, 404)
                return self._send_json(packet)

            if path == '/api/flow-events':
                run_id = qs.get('run', [''])[0]
                if not re.fullmatch(r'[0-9a-f]{32}', run_id):
                    return self._send_json({'error': 'Invalid run identifier.'}, 400)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-transform')
                self.send_header('X-Accel-Buffering', 'no')
                self.end_headers()
                last = -1
                try:
                    while True:
                        packet = LIVE_RESULTS.wait_flows(run_id, last)
                        if packet is None:
                            self.wfile.write(b': waiting for run\n\n')
                        elif packet['seq'] != last:
                            last = packet['seq']
                            self.wfile.write(('data: ' + json.dumps(packet) + '\n\n').encode())
                            if packet['complete']:
                                self.wfile.flush()
                                break
                        else:
                            self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            if path == '/api/flows':
                packet = LIVE_RESULTS.get(qs.get('run', [''])[0], 'flows')
                if packet is None:
                    return self._send_json({'error': 'Данные потока недоступны.'}, 404)
                return self._send_json(packet)

            if path == '/api/output':
                packet = LIVE_RESULTS.get(qs.get('run', [''])[0], 'outputs', qs.get('block', [''])[0])
                if packet is None:
                    return self._send_json({'error': 'Вывод блока недоступен.'}, 404)
                return self._send_json(packet)

            if path == "/api/ownership":
                name = qs.get("name", [""])[0]
                if name:
                    full = MODELS_DIR / (name + ".json")
                    if not full.is_file():
                        return self._send_json({"error": "not found"}, 404)
                    model = json.loads(full.read_text("utf-8"))
                else:
                    return self._send_json({"error": "name required"}, 400)
                return self._send_json(_get_external_interface(model))

            return self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self._send_json({"error": repr(exc)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_body()

            if path == '/api/session':
                return self._send_json({'session_id': SESSION_HEAPS.create().session_id})

            if path == '/api/session/touch':
                try:
                    SESSION_HEAPS.touch(body.get('session_id'))
                except InvalidReference as exc:
                    return self._send_json({'error': str(exc)}, 404)
                return self._send_json({'ok': True})

            if path == '/api/session/stop':
                status = SESSION_HEAPS.close(body.get('session_id'))
                if status is None:
                    return self._send_json({'error': 'Session is missing or has expired.'}, 404)
                return self._send_json({'ok': True, 'status': status})

            if path == "/api/execute":
                # Legacy generic execution endpoint (alias for simulate with dataflow)
                return self._handle_simulate(body)

            if path == "/api/simulate":
                return self._handle_simulate(body)

            if path == "/api/invoke":
                return self._handle_invoke(body)

            if path == "/api/save":
                name = body.get("name", "")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    return self._send_json({"error": "invalid name"}, 400)
                MODELS_DIR.mkdir(parents=True, exist_ok=True)
                full = MODELS_DIR / (name + ".json")
                import tempfile
                fd, tmp_path = tempfile.mkstemp(dir=str(MODELS_DIR), prefix=".tmp_save_", suffix=".json")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(body.get("model", {}), f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, str(full))
                except BaseException:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
                return self._send_json({"saved": name})

            if path == "/api/library/refresh":
                data = _unified_library(force_reload=True)
                return self._send_json(data)

            if path == "/api/optimize":
                if not (_numerical_adapter and _numerical_adapter.available):
                    return self._send_json({"error": "Numerical engine not available"}, 503)
                try:
                    result = _numerical_adapter.optimize(body.get("model", {}), body.get("settings", {}))
                    return self._send_json({"ok": True, **result})
                except (ValueError, TypeError, KeyError) as exc:
                    return self._send_json({"error": str(exc)}, 400)

            return self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self._send_json({"ok": False, "error": repr(exc)}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        name = qs.get("name", [""])[0]
        try:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                return self._send_json({"error": "invalid name"}, 400)
            full = MODELS_DIR / (name + ".json")
            if not full.is_file():
                return self._send_json({"error": "not found"}, 404)
            full.unlink()
            return self._send_json({"deleted": name})
        except Exception as exc:
            return self._send_json({"error": repr(exc)}, 500)

    # -- simulate with ownership check ------------------------------------- #
    def _handle_simulate(self, body):
        model_dict = body.get("model", {})
        session_heap = None
        if body.get('session_id'):
            try:
                session_heap = SESSION_HEAPS.touch(body['session_id'])
            except InvalidReference as exc:
                return self._send_json({'ok': False, 'error': str(exc)}, 400)

        if any(block.get('type') in ('numerical', 'experiment') for block in model_dict.get('blocks', [])):
            return self._send_json({'ok': False, 'error':
                'Схема использует старый блок расчёта. Откройте её в прежней версии ПавСима или создайте новый Эксперимент.'}, 400)

        # Ownership rule: reject if model has external ports
        if _model_has_external_ports(model_dict):
            iface = _get_external_interface(model_dict)
            return self._send_json({
                "ok": False,
                "error": "Model is externally controlled and cannot be run internally.",
                "ownership": iface,
                "hint": "Use /api/invoke with all required inputs supplied.",
            }, 403)

        run_id = body.get('run_id') or uuid.uuid4().hex
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
            return self._send_json({'ok': False, 'error': 'Invalid run identifier.'}, 400)
        LIVE_RESULTS.prepare(model_dict, run_id)

        def publish_plot(node_id, data):
            LIVE_RESULTS.publish_output(run_id, node_id, data)

        def publish_flows(blocks):
            LIVE_RESULTS.publish_flows(run_id, blocks)

        try:
            result = _execute_session_dataflow(model_dict, session_heap, publish_plot, publish_flows)
        except (ValueError, RuntimeError, GraphError, SessionCancelled) as exc:
            LIVE_RESULTS.finish(model_dict, run_id)
            return self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            LIVE_RESULTS.finish(model_dict, run_id)
            return self._send_json({"ok": False, "error": repr(exc)}, 500)
        LIVE_RESULTS.finish(model_dict, run_id, result['results'], result.get('raw_results'))
        return self._send_json({
            "ok": True, "run_id": run_id, "results": result["results"],
            "n_steps": result["n_steps"], "optimization": result['optimization'],
        })

    # -- invoke (external invocation) -------------------------------------- #
    def _handle_invoke(self, body):
        """Handle external invocation of an externally controlled model."""
        model_dict = body.get("model", {})

        # Must be externally controlled
        if not _model_has_external_ports(model_dict):
            return self._send_json({
                "ok": False,
                "error": "Model has no external ports. Use /api/simulate for standalone models.",
            }, 400)

        if not (_numerical_adapter and _numerical_adapter.available):
            return self._send_json({"error": "Numerical engine not available"}, 503)

        iface = _get_external_interface(model_dict)
        required_inputs = iface["inputs"]

        # Validate: all required inputs must be supplied
        supplied = body.get("inputs", {})
        missing = []
        for inp in required_inputs:
            if inp["name"] not in supplied and inp["id"] not in supplied:
                missing.append(inp["name"])
        if missing:
            return self._send_json({
                "ok": False,
                "error": f"Missing required input(s): {', '.join(missing)}",
                "required_inputs": required_inputs,
                "supplied": list(supplied.keys()),
            }, 400)

        t_end = body.get("t_end", 1.0)
        h = body.get("h", 0.01)
        method = body.get("method", "rk4")

        try:
            result = _numerical_adapter.invoke(model_dict, supplied, t_end, h, method)
        except (ValueError, RuntimeError) as exc:
            return self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            return self._send_json({"ok": False, "error": repr(exc)}, 500)

        return self._send_json({
            "ok": True,
            "outputs": result["outputs"],
            "results": result["results"],
        })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(host="127.0.0.1", port=8881):
    engine_available = bool(_numerical_adapter and _numerical_adapter.available)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"PavSim Shell running at http://{host}:{port}")
    print(f"  Engine available: {engine_available}")
    if engine_available:
        blocks = _numerical_adapter.get_blocks()
        print(f"  blocks: {len(blocks)} types loaded")
        errors = _numerical_adapter.get_load_errors()
        if errors:
            print("  custom block load errors:")
            for fname, msg in errors:
                print(f"    - {fname}: {msg}")
    stop_reaper = threading.Event()
    def reap_sessions():
        while not stop_reaper.wait(60):
            SESSION_HEAPS.expire()
    threading.Thread(target=reap_sessions, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_reaper.set()
        SESSION_HEAPS.close_all()
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="PavSim Shell server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8881)
    ap.add_argument("--no-engines", action="store_true", help="Start without numerical engines")
    args = ap.parse_args()
    main(args.host, args.port)
