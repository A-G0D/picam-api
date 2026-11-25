# stream.py - MJPEG live stream. Point a browser or an <img> at it.
#
#   GET /api/stream            -> multipart MJPEG (never ends)
#   GET /api/stream?fps=5      -> cap the push rate
import time
from flask import Blueprint, Response, request

from camera import cam

bp = Blueprint("stream", __name__)


def _mjpeg(fps):
    interval = 1.0 / max(1, fps)
    while True:
        data = cam.get_jpeg()
        if data:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                   + data + b"\r\n")
        time.sleep(interval)


@bp.route("/api/stream")
def stream():
    fps = request.args.get("fps", 12, type=int)
    return Response(_mjpeg(fps),
                    mimetype="multipart/x-mixed-replace; boundary=frame")
