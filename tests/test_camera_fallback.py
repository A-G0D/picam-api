"""Real camera init must never crash the process on first boot.

Simulates a Picamera2 that always throws (loose ribbon, camera not yet
enumerated, held by a stale process, ...) and asserts CameraManager.start()
falls back to mock mode instead of raising, with the error recorded so
/api/health can surface it.
"""
import camera as camera_module
from camera import CameraManager


class _AlwaysFailsPicamera2:
    def __init__(self):
        raise RuntimeError("simulated: camera not detected")


def test_start_falls_back_to_mock_on_repeated_camera_init_failure(monkeypatch):
    monkeypatch.setattr(camera_module, "Picamera2", _AlwaysFailsPicamera2, raising=False)

    mgr = CameraManager()
    mgr.mock = False          # pretend picamera2 is importable on this box
    mgr._HAVE_PICAMERA = True

    # retries=2, no delay so the test stays fast
    mgr.start(retries=2, retry_delay=0)
    try:
        assert mgr.running is True          # process kept going
        assert mgr.mock is True             # fell back instead of crashing
        assert mgr.camera_error is not None
        assert "simulated" in mgr.camera_error
    finally:
        mgr._running = False                # stop the background thread


def test_start_succeeds_first_try_when_camera_is_fine(monkeypatch):
    calls = {"n": 0}

    class _WorksFirstTry:
        def __init__(self):
            calls["n"] += 1

        def create_video_configuration(self, **kw):
            return {}

        def configure(self, cfg):
            pass

        def start(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(camera_module, "Picamera2", _WorksFirstTry, raising=False)

    mgr = CameraManager()
    mgr.mock = False
    mgr.start(retries=3, retry_delay=0)
    try:
        assert mgr.mock is False
        assert mgr.camera_error is None
        assert calls["n"] == 1
    finally:
        mgr._running = False
