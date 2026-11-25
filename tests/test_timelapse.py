"""Coverage for the timelapse worker (modules/timelapse.py), previously untested.

The worker is real background-thread logic: it writes a frame every interval,
auto-stops once it hits a requested frame count, and rejects a second start
while one is already running. None of that was exercised anywhere.
"""
import os
import time

import pytest

from app import app as flask_app
from camera import cam
from config import CFG


@pytest.fixture(scope="module")
def client():
    for _ in range(50):
        if cam.get_frame() is not None:
            break
        time.sleep(0.1)
    return flask_app.test_client()


def _files():
    return set(os.listdir(CFG.timelapse_dir))


def test_timelapse_runs_and_autostops_at_target_count(client):
    """count=2 with a short interval should capture exactly 2 frames and stop
    itself, without ever needing a /stop call."""
    before = _files()

    # interval must clear a full second: filenames are second-resolution
    # (tl_%Y%m%d_%H%M%S.jpg), so two captures inside the same second collide.
    r = client.post("/api/timelapse/start?interval=1.1&count=2")
    assert r.status_code == 200
    body = r.get_json()
    assert body["running"] is True
    assert body["target"] == 2

    deadline = time.time() + 8.0
    status = None
    while time.time() < deadline:
        status = client.get("/api/timelapse/status").get_json()
        if not status["running"]:
            break
        time.sleep(0.1)

    assert status is not None
    assert status["running"] is False, "worker should auto-stop once count target is hit"
    assert status["count"] == 2

    after = _files()
    new_files = after - before
    assert len(new_files) == 2
    for name in new_files:
        assert name.startswith("tl_") and name.endswith(".jpg")


def test_timelapse_rejects_start_while_already_running(client):
    r1 = client.post("/api/timelapse/start?interval=0.1&count=0")
    assert r1.status_code == 200
    try:
        r2 = client.post("/api/timelapse/start?interval=0.1&count=0")
        assert r2.status_code == 409
        assert r2.get_json()["error"] == "already running"
    finally:
        client.post("/api/timelapse/stop")
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if not client.get("/api/timelapse/status").get_json()["running"]:
                break
            time.sleep(0.1)


def test_timelapse_stop_halts_the_worker_promptly(client):
    client.post("/api/timelapse/start?interval=10&count=0")
    status = client.get("/api/timelapse/status").get_json()
    assert status["running"] is True

    r = client.post("/api/timelapse/stop")
    assert r.status_code == 200
    assert r.get_json()["running"] is False

    # worker sleeps in 0.2s steps, so it must notice the stop quickly even
    # though the requested interval is 10s
    deadline = time.time() + 2.0
    running = True
    while time.time() < deadline:
        running = client.get("/api/timelapse/status").get_json()["running"]
        if not running:
            break
        time.sleep(0.1)
    assert running is False
