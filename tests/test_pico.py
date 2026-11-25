"""Proves the picam -> Pico frame integration actually pushes bytes over HTTP.

No real Pico needed: a tiny stand-in HTTP server plays the Pico's role
(image_show.py's POST / handler) and we assert the picam side produces a
JPEG letterboxed to the Pico's screen size that a receiver can decode.
"""
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

from app import app as flask_app
from camera import cam
from config import CFG
from modules import pico


received = {"body": None, "path": None}


class _FakePicoHandler(BaseHTTPRequestHandler):
    """Minimal stand-in for the Pico's image_show.py POST handler."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received["body"] = body
        received["path"] = self.path
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fake_pico():
    server = HTTPServer(("127.0.0.1", 0), _FakePicoHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()


@pytest.fixture(scope="module")
def client():
    for _ in range(50):
        if cam.get_frame() is not None:
            break
        time.sleep(0.1)
    return flask_app.test_client()


def test_push_frame_reaches_pico_letterboxed(client, fake_pico, monkeypatch):
    # point the picam side at the fake Pico instead of doing arp discovery
    monkeypatch.setattr(pico, "find_pico_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(CFG, "pico_port", fake_pico.server_port)
    received["body"] = None

    r = client.post("/api/pico/push")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ip"] == "127.0.0.1"
    assert body["status"] == 200

    # the fake Pico actually received bytes, and they decode to exactly the
    # Pico screen resolution (proves resize/letterbox, not just a POST)
    assert received["path"] == "/"
    assert received["body"] is not None
    img = Image.open(io.BytesIO(received["body"]))
    assert img.format == "JPEG"
    assert img.size == tuple(CFG.pico_screen)
    assert len(received["body"]) <= CFG.pico_max_bytes


def test_push_store_hits_store_path(client, fake_pico, monkeypatch):
    monkeypatch.setattr(pico, "find_pico_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(CFG, "pico_port", fake_pico.server_port)
    received["body"] = None

    r = client.post("/api/pico/push?store=1")
    assert r.status_code == 200
    assert received["path"] == "/store"
    assert received["body"] is not None


def test_push_degrades_gracefully_without_pico(client, monkeypatch):
    # integration must be optional: no Pico on the network -> clean 502,
    # not a crash, and the rest of the API keeps working
    monkeypatch.setattr(pico, "find_pico_ip", lambda: None)

    r = client.post("/api/pico/push")
    assert r.status_code == 502
    assert "error" in r.get_json()

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json()["ok"] is True
