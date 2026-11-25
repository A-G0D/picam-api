"""PICAM_BACKEND=fake forces synthetic frames; get_jpeg reuses the last encode per frame."""
import importlib, time

import camera as camera_module


def test_env_forces_fake(monkeypatch):
    monkeypatch.setenv("PICAM_BACKEND", "fake")
    try:
        m = importlib.reload(camera_module)
        assert m._HAVE_PICAMERA is False and m.CameraManager().mock is True
    finally:
        monkeypatch.delenv("PICAM_BACKEND")
        importlib.reload(camera_module)


def test_jpeg_cached_per_frame_and_invalidated_by_params():
    from camera import CameraManager
    m = CameraManager()
    m.mock = True
    m._frame = m._mock_frame(0)
    m._seq = 1
    a = m.get_jpeg()
    assert a[:2] == b"\xff\xd8" and m.get_jpeg() is a          # same frame: same object
    assert m.get_jpeg(quality=30) is not a                     # other quality: re-encode
    m._seq = 2
    m._frame = m._mock_frame(5)
    assert m.get_jpeg(quality=30) != a
