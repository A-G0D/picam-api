"""Smoke tests: the API must start and serve in mock mode without a Pi camera.

No Picamera2 is installed in CI/dev, so these run against camera.py's mock
fallback -- the same path used to validate the app before it ever touches
real hardware.
"""
import time

import pytest

from app import app as flask_app
from camera import cam


@pytest.fixture(scope="module")
def client():
    # give the mock camera producer thread a moment to grab its first frame
    for _ in range(50):
        if cam.get_frame() is not None:
            break
        time.sleep(0.1)
    return flask_app.test_client()


def test_app_runs_in_mock_mode(client):
    assert cam.mock is True
    assert cam.running is True


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["mock"] is True


def test_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.get_json()
    assert "pico_ip" in body
    assert "stream_size" in body


def test_capture_returns_jpeg(client):
    r = client.get("/api/capture")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
    assert len(r.data) > 0


def test_capture_list(client):
    r = client.get("/api/capture/list")
    assert r.status_code == 200
    assert "files" in r.get_json()


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200
