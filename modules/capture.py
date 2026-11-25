# capture.py - single still capture + browsing saved photos.
#
#   GET /api/capture              -> live frame as JPEG
#   GET /api/capture?save=1       -> save to data/captures, return the name
#   GET /api/capture?w=1024&h=768 -> resize before encoding
#   GET /api/capture?q=60         -> JPEG quality
#   GET /api/capture/list         -> list saved photos
#   GET /api/capture/file/<name>  -> download a saved photo
import os, time
from flask import Blueprint, Response, request, jsonify, send_from_directory

from camera import cam
from config import CFG

bp = Blueprint("capture", __name__)


@bp.route("/api/capture")
def capture():
    q = request.args.get("q", CFG.jpeg_quality, type=int)
    w = request.args.get("w", type=int)
    h = request.args.get("h", type=int)
    size = (w, h) if w and h else None
    data = cam.get_jpeg(quality=q, size=size)
    if data is None:
        return jsonify(error="no frame yet"), 503
    if request.args.get("save") == "1":
        name = time.strftime("cap_%Y%m%d_%H%M%S.jpg")
        with open(os.path.join(CFG.capture_dir, name), "wb") as f:
            f.write(data)
        return jsonify(saved=name, bytes=len(data))
    return Response(data, mimetype="image/jpeg")


@bp.route("/api/capture/list")
def clist():
    files = sorted(os.listdir(CFG.capture_dir))
    return jsonify(count=len(files), files=files)


@bp.route("/api/capture/file/<name>")
def cfile(name):
    return send_from_directory(CFG.capture_dir, name)
