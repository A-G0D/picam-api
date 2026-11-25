# app.py - picam API. One Flask app that wires every camera capability into
# HTTP endpoints so you can test each thing with a simple query.
#
#   GET  /                       dashboard (buttons + live view)
#   GET  /api/health             camera + server status
#   GET  /api/config             effective config
#
#   GET  /api/capture[?save=1&w=&h=&q=]      still photo
#   GET  /api/capture/list  /api/capture/file/<name>
#   GET  /api/stream[?fps=]                  MJPEG live stream
#   POST /api/timelapse/start?interval=5&count=0   /stop /status /list
#   POST /api/motion/start?threshold=6&save=1&push=0   /stop /status /events
#   GET  /api/qr/scan                        decode QR/barcodes
#   GET  /api/pico/find                      find the Pico frame
#   POST /api/pico/push[?store=1]  /clear    GET /api/pico/list
#   POST /api/pico/mirror/start?fps=2  /stop  live-mirror cam onto the Pico
import os
from flask import Flask, jsonify, send_from_directory

from config import CFG
from camera import cam


def create_app():
    app = Flask(__name__, static_folder="static")

    from modules import capture, stream, timelapse, motion, qr, pico
    for m in (capture, stream, timelapse, motion, qr, pico):
        app.register_blueprint(m.bp)

    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.route("/api/health")
    def health():
        return jsonify(ok=True, mock=cam.mock, running=cam.running,
                       frames=cam.seq, size=list(CFG.stream_size),
                       camera_error=cam.camera_error)

    @app.route("/api/config")
    def config():
        return jsonify(CFG.as_dict())

    cam.start()      # idempotent; safe under any WSGI launcher
    return app


app = create_app()


if __name__ == "__main__":
    print("picam API on http://%s:%d  (mock=%s)" % (CFG.host, CFG.port, cam.mock))
    app.run(host=CFG.host, port=CFG.port, threaded=True)
