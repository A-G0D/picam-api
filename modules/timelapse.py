# timelapse.py - snap a frame every N seconds into data/timelapse.
#
#   POST /api/timelapse/start?interval=5&count=0   (count=0 = run forever)
#   POST /api/timelapse/stop
#   GET  /api/timelapse/status
#   GET  /api/timelapse/list
#
# Render the frames to a video afterwards on the Pi with:
#   ffmpeg -framerate 24 -pattern_type glob -i 'data/timelapse/tl_*.jpg' out.mp4
import os, time, threading
from flask import Blueprint, request, jsonify

from camera import cam
from config import CFG

bp = Blueprint("timelapse", __name__)

_state = {"running": False, "interval": 5, "count": 0, "target": 0,
          "started": None, "last": None, "thread": None}
_lock = threading.Lock()


def _worker(interval, target):
    while _state["running"]:
        data = cam.get_jpeg()
        if data:
            name = time.strftime("tl_%Y%m%d_%H%M%S.jpg")
            with open(os.path.join(CFG.timelapse_dir, name), "wb") as f:
                f.write(data)
            _state["count"] += 1
            _state["last"] = name
        if target and _state["count"] >= target:
            _state["running"] = False
            break
        slept = 0.0                       # sleep in steps so stop is responsive
        while _state["running"] and slept < interval:
            time.sleep(0.2)
            slept += 0.2


def _public():
    return {"running": _state["running"], "interval": _state["interval"],
            "count": _state["count"], "target": _state["target"],
            "started": _state["started"], "last": _state["last"]}


@bp.route("/api/timelapse/start", methods=["POST", "GET"])
def start():
    with _lock:
        if _state["running"]:
            return jsonify(error="already running", **_public()), 409
        interval = request.args.get("interval", 5, type=float)
        target = request.args.get("count", 0, type=int)
        _state.update(running=True, interval=interval, count=0, target=target,
                      started=time.strftime("%Y-%m-%d %H:%M:%S"), last=None)
        t = threading.Thread(target=_worker, args=(interval, target), daemon=True)
        _state["thread"] = t
        t.start()
    return jsonify(**_public())


@bp.route("/api/timelapse/stop", methods=["POST", "GET"])
def stop():
    _state["running"] = False
    return jsonify(**_public())


@bp.route("/api/timelapse/status")
def status():
    return jsonify(**_public())


@bp.route("/api/timelapse/list")
def tlist():
    files = sorted(os.listdir(CFG.timelapse_dir))
    return jsonify(count=len(files), files=files)
