"""Regression tests: atomic file publication in /api/save.

Exercises the real production server code (Handler.do_POST) via a live HTTP
server with a temporary models directory. Tests:
- Save, reload, and compare all blocks, parameters, connection endpoints and manual routes
- Overwrite an existing diagram successfully and verify the complete new JSON
- Inject failures before publication; the previous file must remain byte-for-byte intact
- Verify successful publication survives a fresh-process reload
- Verify incomplete temporary files are absent from the saved-model list
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_model_dict():
    """Create a realistic model dict with blocks, params, connections, and routes."""
    return {
        "blocks": [
            {"id": "b1", "type": "constant", "params": {"value": 3.14}, "x": 100, "y": 200},
            {"id": "b2", "type": "gain", "params": {"k": 2.5}, "x": 400, "y": 300},
            {"id": "b3", "type": "graph_display", "params": {}, "x": 700, "y": 150},
        ],
        "connections": [
            {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0},
            {"from": "b2", "from_port": 0, "to": "b3", "to_port": 0,
             "route": [{"x": 532, "y": 300}, {"x": 532, "y": 150}, {"x": 700, "y": 150}]},
        ],
    }


class TestAtomicSave(unittest.TestCase):
    """Test atomic save via live HTTP server with temp models dir."""

    @classmethod
    def setUpClass(cls):
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import xcos_mini.server as srv
        cls.srv = srv
        # Create a temporary models directory
        cls.tmpdir = tempfile.mkdtemp(prefix="xcos_test_models_")
        # Patch MODELS_DIR
        cls._orig_models_dir = srv.MODELS_DIR
        srv.MODELS_DIR = cls.tmpdir
        os.makedirs(cls.tmpdir, exist_ok=True)
        # Start server on a random port
        from http.server import ThreadingHTTPServer
        srv.lib = srv.Library(blocks_dir=os.path.join(ROOT, "blocks"))
        srv.Handler.lib = srv.lib
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.srv.MODELS_DIR = cls._orig_models_dir
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_save_and_reload_roundtrip(self):
        """Save, reload, and compare all blocks, parameters, connection endpoints and manual routes."""
        model = _make_model_dict()
        result = self._post("/api/save", {"name": "test_roundtrip", "model": model})
        self.assertEqual(result["saved"], "test_roundtrip")

        loaded = self._get("/api/load?name=test_roundtrip")
        self.assertEqual(loaded["name"], "test_roundtrip")
        self.assertEqual(loaded["model"], model)

    def test_overwrite_existing_diagram(self):
        """Overwrite an existing diagram successfully and verify the complete new JSON."""
        model_v1 = {"blocks": [{"id": "b1", "type": "constant", "params": {"value": 1}, "x": 0, "y": 0}],
                    "connections": []}
        model_v2 = {"blocks": [{"id": "b1", "type": "constant", "params": {"value": 99}, "x": 10, "y": 20},
                              {"id": "b2", "type": "gain", "params": {"k": 3}, "x": 300, "y": 400}],
                    "connections": [{"from": "b1", "from_port": 0, "to": "b2", "to_port": 0}]}

        self._post("/api/save", {"name": "test_overwrite", "model": model_v1})
        self._post("/api/save", {"name": "test_overwrite", "model": model_v2})

        loaded = self._get("/api/load?name=test_overwrite")
        self.assertEqual(loaded["model"], model_v2)

    def test_failure_before_publication_preserves_old_file(self):
        """Inject a failure during fsync; the previous file must remain byte-for-byte intact."""
        import xcos_mini.server as srv
        # First save a valid file
        model = _make_model_dict()
        self._post("/api/save", {"name": "test_fail", "model": model})
        # Read the original bytes
        path = os.path.join(self.tmpdir, "test_fail.json")
        with open(path, "rb") as f:
            original_bytes = f.read()

        # Monkeypatch os.fsync to raise an exception (simulates disk failure)
        orig_fsync = os.fsync
        def failing_fsync(fd):
            raise OSError("simulated disk failure")
        os.fsync = failing_fsync
        try:
            # Attempt save - should fail
            try:
                self._post("/api/save", {"name": "test_fail", "model": {"blocks": [], "connections": []}})
                self.fail("Expected save to fail")
            except urllib.error.HTTPError:
                pass  # expected
        finally:
            os.fsync = orig_fsync

        # The original file must be byte-for-byte intact
        with open(path, "rb") as f:
            current_bytes = f.read()
        self.assertEqual(current_bytes, original_bytes,
                         "Previous file must be byte-for-byte intact after failed save")
        # And it must still be valid JSON
        data = json.loads(current_bytes)
        self.assertEqual(data, model)

    def test_failure_during_replace_preserves_old_file(self):
        """Inject a failure during os.replace; the previous file must remain intact."""
        import xcos_mini.server as srv
        model = _make_model_dict()
        self._post("/api/save", {"name": "test_replace_fail", "model": model})
        path = os.path.join(self.tmpdir, "test_replace_fail.json")
        with open(path, "rb") as f:
            original_bytes = f.read()

        orig_replace = os.replace
        def failing_replace(src, dst):
            raise OSError("simulated replace failure")
        os.replace = failing_replace
        try:
            try:
                self._post("/api/save", {"name": "test_replace_fail", "model": {"blocks": [], "connections": []}})
                self.fail("Expected save to fail")
            except urllib.error.HTTPError:
                pass
        finally:
            os.replace = orig_replace

        with open(path, "rb") as f:
            current_bytes = f.read()
        self.assertEqual(current_bytes, original_bytes,
                         "Previous file must be intact after failed replace")

    def test_successful_publication_survives_reload(self):
        """Verify successful publication survives a fresh-process reload (file is valid JSON)."""
        model = _make_model_dict()
        self._post("/api/save", {"name": "test_persist", "model": model})
        # Simulate fresh-process reload: read the file directly
        path = os.path.join(self.tmpdir, "test_persist.json")
        with open(path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
        self.assertEqual(reloaded, model)

    def test_temp_files_not_in_model_list(self):
        """Verify incomplete temporary files are absent from the saved-model list."""
        # Create a fake temp file that looks like what our save would create
        fake_tmp = os.path.join(self.tmpdir, ".tmp_save_test123.json")
        with open(fake_tmp, "w") as f:
            f.write("{partial")
        # Also save a real model
        self._post("/api/save", {"name": "test_visible", "model": {"blocks": [], "connections": []}})

        models = self._get("/api/models")
        names = models["models"]
        self.assertIn("test_visible", names)
        self.assertNotIn(".tmp_save_test123", names,
                         "Temp files must not appear in model list")
        # Clean up fake temp
        os.unlink(fake_tmp)

    def test_no_partial_json_after_failure(self):
        """After a failed save, the file must be a complete old or new image, never partial."""
        model = _make_model_dict()
        self._post("/api/save", {"name": "test_partial", "model": model})
        path = os.path.join(self.tmpdir, "test_partial.json")

        # Inject failure during json.dump (serialization)
        import json as json_mod
        orig_dump = json_mod.dump
        def failing_dump(obj, fp, **kwargs):
            fp.write('{"blocks": [')  # write partial JSON
            raise OSError("simulated serialization failure")
        json_mod.dump = failing_dump
        try:
            try:
                self._post("/api/save", {"name": "test_partial", "model": {"blocks": [], "connections": []}})
                self.fail("Expected save to fail")
            except urllib.error.HTTPError:
                pass
        finally:
            json_mod.dump = orig_dump

        # The file must still be valid, complete JSON (the old image)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        data = json.loads(content)  # must not raise
        self.assertEqual(data, model, "File must contain the complete old image")


if __name__ == "__main__":
    unittest.main()
