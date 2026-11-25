"""Regression test for the motion detector's pico-push failure handling.

Bug: `modules/motion.py` used to swallow a failed push to the Pico with a bare
`except Exception: pass`, so a Pico that's off or unreachable failed silently
and gave no signal in the logs. The fix logs the exception instead of
discarding it, matching the pattern already used in camera.py's frame loop.
"""
import time

from app import app as flask_app
import modules.motion as motion_mod


def test_pico_push_failure_is_logged_not_swallowed(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("pico unreachable (test)")

    monkeypatch.setattr(motion_mod, "push_frame_to_pico", _boom)

    client = flask_app.test_client()
    try:
        r = client.post("/api/motion/start?threshold=-999&push=1&save=0")
        assert r.status_code == 200

        deadline = time.time() + 3.0
        logged = False
        while time.time() < deadline:
            time.sleep(0.2)
            if "motion: pico push failed" in capsys.readouterr().out:
                logged = True
                break

        status = client.get("/api/motion/status").get_json()
        assert status["running"] is True  # worker thread survived the exception
        assert logged, "expected the pico push failure to be printed, not swallowed"
    finally:
        client.post("/api/motion/stop")
