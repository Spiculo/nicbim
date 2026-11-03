# SPDX-License-Identifier: GPL-3.0-or-later
"""D225: the AI visualiser sends a sketch to a configured image model and saves the result."""
import base64
import http.server
import json
import threading

import pytest

from kimbim import app_bridge as B
from kimbim import visualiser as V
from kimbim.testing import build_model

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n3sAAAAASUVORK5CYII=")


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


class Stub(http.server.BaseHTTPRequestHandler):
    received: dict = {}
    status = 200
    payload: dict = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        Stub.received = {"body": self.rfile.read(length),
                         "auth": self.headers.get("Authorization", ""),
                         "type": self.headers.get("Content-Type", "")}
        data = json.dumps(Stub.payload or {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        body = data.encode("utf-8")
        self.send_response(Stub.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stub(monkeypatch):
    Stub.received, Stub.status, Stub.payload = {}, 200, {}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/images/edits"
    monkeypatch.setenv("KIMBIM_IMAGE_ENDPOINT", url)
    monkeypatch.setenv("KIMBIM_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("KIMBIM_IMAGE_MODEL", "test-model")
    yield server
    server.shutdown()


@pytest.fixture
def opened():
    B._model = build_model(schema="IFC4", walls=0)
    B._reset_history("")
    return B._model


def test_a_sketch_is_rendered_and_saved(tmp_path, stub, opened):
    sketch = tmp_path / "sketch.png"
    sketch.write_bytes(PNG)
    output = tmp_path / "render.png"
    cfg = call(V.visualiser_config)
    assert cfg["configured"] and cfg["model"] == "test-model"
    assert "key" not in cfg
    r = call(V.render_sketch, str(sketch), "warm interior at dusk", str(output), "1536x1024")
    assert r["ok"] and r["bytes"] > 0 and r["model"] == "test-model"
    assert output.read_bytes() == PNG
    body = Stub.received["body"]
    assert b"warm interior at dusk" in body and b"test-model" in body and b"1536x1024" in body
    assert Stub.received["auth"] == "Bearer test-key"
    assert Stub.received["type"].startswith("multipart/form-data; boundary=")
    # The default output sits next to the sketch.
    assert call(V.render_sketch, str(sketch), "a second option")["ok"]
    assert (tmp_path / "sketch-ai.png").is_file()


def test_bad_inputs_and_model_errors_are_reported(tmp_path, stub, opened):
    sketch = tmp_path / "sketch.png"
    sketch.write_bytes(PNG)
    assert not call(V.render_sketch, str(sketch), "")["ok"]
    assert not call(V.render_sketch, str(tmp_path / "absent.png"), "x")["ok"]
    wrong = tmp_path / "sketch.gif"
    wrong.write_bytes(b"GIF89a")
    assert not call(V.render_sketch, str(wrong), "x")["ok"]
    assert not call(V.render_sketch, str(sketch), "x", "", "123x456")["ok"]
    Stub.status = 500
    r = call(V.render_sketch, str(sketch), "x", str(tmp_path / "out.png"))
    assert not r["ok"] and "HTTP 500" in r["error"]
    # A missing key is a configuration error, not an empty image.
    import os
    os.environ.pop("KIMBIM_IMAGE_API_KEY", None)
    r = call(V.render_sketch, str(sketch), "x")
    assert not r["ok"] and "KIMBIM_IMAGE_API_KEY" in r["error"]
    assert call(V.visualiser_config)["configured"] is False
