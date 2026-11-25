# motion.py - naive motion detector. Diffs consecutive downsampled frames; on
# a big enough change it logs an event and can save the frame and/or push it to
# the Pico display (turn your two gadgets into a motion-triggered photo alert).
#
#   POST /api/motion/start?threshold=6&save=1&push=0
#   POST /api/motion/stop
#   GET  /api/motion/status
#   GET  /api/motion/events
import os, time, threading
import numpy as np
from flask import Blueprint, request, jsonify

from camera import cam
from config import CFG
from modules.pico import push_frame_to_pico

bp = Blueprint("motion", __name__)

_state = {"running": False, "threshold": CFG.motion_threshold, "events": 0,
          "last_event": None, "last_score": 0.0, "save": True, "push": False,
          "thread": None}


def _gray_small(arr):
    return arr[::8, ::8].mean(axis=2)     # cheap downsample + grayscale


def _worker():
    prev = None
    while _state["running"]:
        arr = cam.get_frame()
        if arr is not None and arr.ndim == 3:
            g = _gray_small(arr)
            if prev is not None and prev.shape == g.shape:
                score = float(np.abs(g - prev).mean())
                _state["last_score"] = round(score, 2)
                if score > _state["threshold"]:
                    _state["events"] += 1
                    _state["last_event"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    if _state["save"]:
                        data = cam.get_jpeg()
                        if data:
                            name = time.strftime("mo_%Y%m%d_%H%M%S.jpg")
                            with open(os.path.join(CFG.motion_dir, name), "wb") as f:
                                f.write(data)
                    if _state["push"]:
                        try:
                            push_frame_to_pico()
                        except Exception as e:
                            print("motion: pico push failed:", e)
                    time.sleep(1.0)       # debounce so one event isn't 20 frames
            prev = g
        time.sleep(0.15)


def _public():
    return {k: _state[k] for k in ("running", "threshold", "events",
                                   "last_event", "last_score", "save", "push")}


@bp.route("/api/motion/start", methods=["POST", "GET"])
def start():
    if _state["running"]:
        return jsonify(error="already running", **_public()), 409
    _state["threshold"] = request.args.get("threshold", CFG.motion_threshold, type=float)
    _state["save"] = request.args.get("save", "1") == "1"
    _state["push"] = request.args.get("push", "0") == "1"
    _state.update(running=True, events=0, last_event=None)
    t = threading.Thread(target=_worker, daemon=True)
    _state["thread"] = t
    t.start()
    return jsonify(**_public())


@bp.route("/api/motion/stop", methods=["POST", "GET"])
def stop():
    _state["running"] = False
    return jsonify(**_public())


@bp.route("/api/motion/status")
def status():
    return jsonify(**_public())


@bp.route("/api/motion/events")
def events():
    files = sorted(os.listdir(CFG.motion_dir))
    return jsonify(count=len(files), files=files)
