"""HTTP server + JSON API for PavSim.

Uses only the Python standard library (http.server). Serves the web frontend
and exposes a small JSON API for the block library, simulation, and save/load.

Endpoints
---------
GET    /api/health            -> {"status": "ok", ...}
GET    /api/blocks            -> list of block type descriptions
POST   /api/optimize          -> {model, settings} -> tuned PI/PID coefficients
POST   /api/simulate          -> {model, t_end, h, method} -> results
GET    /api/models            -> list of saved model names
POST   /api/save              -> {name, model} -> {"saved": name}
GET    /api/load?name=X       -> {"name": X, "model": {...}}
DELETE /api/models?name=X     -> {"deleted": name}

Static files are served from the web/ directory.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

# Make the package importable when run as a script from the project root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from xcos_mini import __version__  # noqa: E402
from xcos_mini.core import Library, Model, Engine, BlockError  # noqa: E402
from xcos_mini.subsystem import expand_subsystems  # noqa: E402
from xcos_mini.optimization import optimize, simulate_with_optimizers, finite  # noqa: E402
from xcos_mini.experiments import execute_workspace  # noqa: E402

WEB_DIR = os.path.join(_HERE, "web")
BLOCKS_DIR = os.path.join(_ROOT, "blocks")
MODELS_DIR = os.path.join(_ROOT, "models")

# Guards the shared Library against concurrent reload/read (ThreadingHTTPServer).
LIB_LOCK = threading.Lock()
PLOT_RUNS=OrderedDict()
PLOT_LOCK=threading.Lock()


def _build_library_tree(lib):
    """Build the library tree from the Library's category metadata.

    Categories (derived from directory names) become parent nodes and blocks
    become child nodes. The file system is the single source of truth: the
    Library discovers blocks recursively from blocks/, and the GUI displays
    categories as bold parent nodes and blocks as ordinary child nodes.
    """
    tree = []
    for category, blocks in lib.categories().items():
        tree.append({
            "name": category,
            "type": "category",
            "blocks": blocks,
        })
    return tree


def _build_model(lib, d):
    """Build an executable Model from a model dict.

    Subsystem blocks are expanded into flat blocks before instantiation.
    The expansion resolves boundary terminal connections (In1/Out1) and
    scopes internal block IDs to avoid collisions.
    """
    # Expand subsystems into a flat model dict
    flat = expand_subsystems(d)
    m = Model()
    for b in flat.get("blocks", []):
        bid = str(b["id"])
        block = lib.instantiate(b["type"])
        for k, v in b.get("params", {}).items():
            block.params[k] = v
        m.add_block(block, bid, b.get("x", 0), b.get("y", 0))
    for c in flat.get("connections", []):
        m.add_connection(
            str(c["from"]), int(c.get("from_port", 0)),
            str(c["to"]), int(c.get("to_port", 0)),
        )
    return m


def _serialize_results(results):
    out = {}
    for bid, series in results.items():
        vector = bool(series and isinstance(series[0][1], tuple))
        out[str(bid)] = {
            "t": [p[0] for p in series],
            "y": [p[1][0] if vector else p[1] for p in series],
        }
        if vector:
            out[str(bid)]["outputs"] = [[v[port] for t, v in series] for port in range(len(series[0][1]))]

    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "PavSim/" + __version__
    lib = None  # set in main()

    # -- helpers ----------------------------------------------------------- #
    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
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
        # quieter logging
        sys.stderr.write("[PavSim] " + (fmt % args) + "\n")

    # -- routing ----------------------------------------------------------- #
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/":
                path = "/index.html"
            if path.startswith("/") and not path.startswith("/api/"):
                # static file
                rel = unquote(path).lstrip("/")
                allowed = os.path.realpath(WEB_DIR)
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
                return self._send_file(full, ctype)
            if path == "/api/plot":
                with PLOT_LOCK:
                    packet=PLOT_RUNS.get(qs.get('run',[''])[0],{}).get(qs.get('block',[''])[0])
                if packet is None:return self._send_json({'error':'Данные графика недоступны. Повторите Run.'},404)
                return self._send_json(packet)
            if path == "/api/health":
                return self._send_json({
                    "status": "ok",
                    "blocks": self.lib.names(),
                    "load_errors": self.lib.load_errors,
                })
            if path == "/api/blocks":
                return self._send_json({"blocks": self.lib.describe()})
            if path == "/api/models":
                names = []
                if os.path.isdir(MODELS_DIR):
                    names = sorted(
                        f[:-5] for f in os.listdir(MODELS_DIR)
                        if f.endswith(".json") and not f.startswith(".")
                    )
                return self._send_json({"models": names})
            if path == "/api/load":
                name = qs.get("name", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    return self._send_json({"error": "invalid name"}, 400)
                full = os.path.normpath(os.path.join(MODELS_DIR, name + ".json"))
                if not full.startswith(MODELS_DIR) or not os.path.isfile(full):
                    return self._send_json({"error": "not found"}, 404)
                with open(full, "r", encoding="utf-8") as f:
                    model = json.load(f)
                return self._send_json({"name": name, "model": model})
            if path == "/api/library":
                # Re-read the file system and reload custom blocks so that
                # created / moved / deleted block files are reflected.
                with LIB_LOCK:
                    self.lib.reload_blocks_dir(BLOCKS_DIR)
                    tree = _build_library_tree(self.lib)
                    load_errors = list(self.lib.load_errors)
                return self._send_json({"tree": tree, "load_errors": load_errors})
            return self._send_json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": repr(exc)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_body()
            if path == "/api/optimize":
                def build_candidate(candidate):
                    with LIB_LOCK:
                        return _build_model(self.lib, candidate)
                try:
                    result = optimize(body.get("model", {}), build_candidate, body.get("settings", {}))
                    return self._send_json({"ok": True, **result})
                except (BlockError, ValueError, TypeError, KeyError) as exc:
                    return self._send_json({"error": str(exc)}, 400)
            if path == "/api/simulate":
                model_dict = body.get("model", {})
                if isinstance(body.get("t_end"), bool) or isinstance(body.get("h"), bool):
                    raise BlockError("t_end and h must be finite numbers, not booleans.")
                t_end = finite(body.get("t_end", 1.0), "t_end")
                h = finite(body.get("h", 0.01), "h")
                if t_end < 0 or h <= 0 or not math.isfinite(t_end / h):
                    raise BlockError("t_end must be non-negative and h positive, with finite t_end/h.")
                method = body.get("method", "rk4")
                def build_candidate(candidate):
                    with LIB_LOCK:
                        return _build_model(self.lib, candidate)
                results, tuning, experiments = execute_workspace(model_dict, build_candidate, t_end, h, method, selected=body.get("experiment"))
                serialized=_serialize_results(results)
                plots={}
                def collect(diagram,prefix=''):
                    for block in diagram.get('blocks',[]):
                        key=prefix+str(block['id']);kind=block['type']
                        if kind.startswith('graph_') and key in serialized:
                            inputs=sorted([c for c in diagram.get('connections',[]) if str(c['to'])==str(block['id'])],key=lambda c:int(c.get('to_port',0)))
                            labels=[str(c['from'])+':'+str(int(c.get('from_port',0))+1) for c in inputs]
                            params=dict(self.lib.get(kind).parameters);params.update(block.get('params',{}))
                            if kind=='graph_xyz' and params.get('label')=='График XYZ':params['label']='XY с оценкой'
                            if kind=='graph_xyz' and params.get('label')=='Маршрут p1/p2, цвет J':params['label']='Маршрут p1/p2: шаг | J'
                            plots[key]={'data':serialized[key],'config':{'kind':'xy_score' if kind=='graph_xyz' else 'xy' if kind=='graph_xy' else 'series','params':params,'labels':labels,'score_connected':any(int(c.get('to_port',0))==2 for c in inputs),'axis':'trial' if experiments and not prefix else 't'}}
                        if block.get('internal'):collect(block['internal'],key+'/')
                collect(model_dict)
                run_id=uuid.uuid4().hex
                with PLOT_LOCK:
                    PLOT_RUNS[run_id]=plots
                    while len(PLOT_RUNS)>5:PLOT_RUNS.popitem(last=False)
                return self._send_json({
                    "ok": True,
                    "run_id":run_id,
                    "results": serialized,
                    "optimization": tuning,
                    "experiments": experiments,
                    "n_steps": max((len(series) - 1 for series in results.values()), default=0) if not experiments else 1,
                })
            if path == "/api/save":
                name = body.get("name", "")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    return self._send_json({"error": "invalid name"}, 400)
                os.makedirs(MODELS_DIR, exist_ok=True)
                full = os.path.normpath(os.path.join(MODELS_DIR, name + ".json"))
                if not full.startswith(MODELS_DIR):
                    return self._send_json({"error": "forbidden"}, 403)
                # Atomic publication: write to a temp file in the same directory,
                # flush + fsync, then os.replace to the final destination.
                # On failure before replace, the previous file is untouched.
                import tempfile
                fd, tmp_path = tempfile.mkstemp(dir=MODELS_DIR, prefix=".tmp_save_", suffix=".json")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(body.get("model", {}), f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, full)
                    # Synchronize the containing directory to persist the rename.
                    dir_fd = os.open(MODELS_DIR, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except BaseException:
                    # Clean up the temp file if it still exists (replace not yet done).
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
                return self._send_json({"saved": name})
            return self._send_json({"error": "not found"}, 404)
        except BlockError as exc:
            return self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"ok": False, "error": repr(exc)}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        name = qs.get("name", [""])[0]
        try:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                return self._send_json({"error": "invalid name"}, 400)
            full = os.path.normpath(os.path.join(MODELS_DIR, name + ".json"))
            if not full.startswith(MODELS_DIR) or not os.path.isfile(full):
                return self._send_json({"error": "not found"}, 404)
            os.remove(full)
            return self._send_json({"deleted": name})
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": repr(exc)}, 500)


def main(host="127.0.0.1", port=8000):
    lib = Library(blocks_dir=BLOCKS_DIR)
    Handler.lib = lib
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"PavSim running at http://{host}:{port}")
    print(f"  blocks: {', '.join(lib.names())}")
    if lib.load_errors:
        print("  custom block load errors:")
        for fname, msg in lib.load_errors:
            print(f"    - {fname}: {msg}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="PavSim server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    main(args.host, args.port)
