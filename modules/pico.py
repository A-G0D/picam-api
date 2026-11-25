# pico.py - talk to the Pico Display 2.0 image frame on the hotspot.
#
# Grabs a camera frame, letterboxes it to the Pico's 320x240 screen, and POSTs
# the JPEG to the Pico's tiny web server (image_show.py accepts raw JPEG on
# POST / for live and POST /store for the gallery, capped at 90000 bytes).
#
#   GET  /api/pico/find              -> discover the Pico's IP via arp
#   POST /api/pico/push[?store=1]    -> send the current frame to the Pico
#   POST /api/pico/clear             -> wipe the Pico gallery
#   GET  /api/pico/list              -> proxy the Pico's /list
#   POST /api/pico/mirror/start?fps=2  -> live-mirror the camera onto the Pico
#   POST /api/pico/mirror/stop
import io, time, threading, subprocess, urllib.request
from flask import Blueprint, request, jsonify
from PIL import Image

from camera import cam
from config import CFG

bp = Blueprint("pico", __name__)

_mirror = {"running": False, "fps": 2, "thread": None, "pushed": 0}


# ---------------------------------------------------------------- discovery
def find_pico_ip():
    if CFG.pico_ip:
        return CFG.pico_ip
    out = ""
    for cmd in (["arp", "-n"], ["arp", "-a"]):
        try:
            out = subprocess.check_output(cmd, text=True, errors="ignore")
            break
        except Exception:
            continue
    mac_variants = (CFG.pico_mac.lower(), CFG.pico_mac.lower().replace("-", ":"))
    for line in out.splitlines():
        low = line.lower()
        if any(m in low for m in mac_variants):
            for tok in line.replace("(", " ").replace(")", " ").split():
                if tok.count(".") == 3 and tok.replace(".", "").isdigit():
                    return tok
    return None


# ---------------------------------------------------------------- encode/post
def _letterbox_jpeg(arr, quality):
    W, H = CFG.pico_screen
    img = Image.fromarray(arr).convert("RGB")
    img.thumbnail((W, H))
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    q = quality
    while True:
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=q)
        data = buf.getvalue()
        if len(data) <= CFG.pico_max_bytes or q <= 30:
            return data
        q -= 10                       # too big for the Pico, drop quality


def _post(ip, path, data):
    url = "http://%s:%d%s" % (ip, CFG.pico_port, path)
    headers = ({"Content-Type": "image/jpeg", "Content-Length": str(len(data))}
               if data else {})
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8", "replace")


def push_frame_to_pico(store=False, quality=None):
    ip = find_pico_ip()
    if not ip:
        raise RuntimeError("pico not found (power it on, or set pico_ip in config.json)")
    arr = cam.get_frame()
    if arr is None:
        raise RuntimeError("no camera frame yet")
    data = _letterbox_jpeg(arr, quality or CFG.jpeg_quality)
    st, body = _post(ip, "/store" if store else "/", data)
    return ip, st, body


# ---------------------------------------------------------------- routes
@bp.route("/api/pico/find")
def pfind():
    ip = find_pico_ip()
    return (jsonify(ip=ip) if ip else (jsonify(error="pico not found"), 404))


@bp.route("/api/pico/push", methods=["POST", "GET"])
def ppush():
    store = request.args.get("store") == "1"
    try:
        ip, st, body = push_frame_to_pico(store=store)
        return jsonify(ip=ip, status=st, pico=body.strip())
    except Exception as e:
        return jsonify(error=str(e)), 502


@bp.route("/api/pico/clear", methods=["POST", "GET"])
def pclear():
    ip = find_pico_ip()
    if not ip:
        return jsonify(error="pico not found"), 404
    st, body = _post(ip, "/clear", None)
    return jsonify(ip=ip, status=st, pico=body.strip())


@bp.route("/api/pico/list")
def plist():
    import json as _j
    ip = find_pico_ip()
    if not ip:
        return jsonify(error="pico not found"), 404
    with urllib.request.urlopen("http://%s:%d/list" % (ip, CFG.pico_port), timeout=10) as r:
        return jsonify(ip=ip, **_j.loads(r.read().decode()))


# ---------------------------------------------------------------- live mirror
def _mirror_worker():
    ip = find_pico_ip()
    while _mirror["running"]:
        interval = 1.0 / max(1, _mirror["fps"])
        try:
            arr = cam.get_frame()
            if arr is not None and ip:
                _post(ip, "/", _letterbox_jpeg(arr, 70))
                _mirror["pushed"] += 1
            elif not ip:
                ip = find_pico_ip()
        except Exception:
            ip = find_pico_ip()       # link blipped, re-discover
        time.sleep(interval)


def _mpublic():
    return {"running": _mirror["running"], "fps": _mirror["fps"],
            "pushed": _mirror["pushed"]}


@bp.route("/api/pico/mirror/start", methods=["POST", "GET"])
def mstart():
    if _mirror["running"]:
        return jsonify(error="already running", **_mpublic()), 409
    _mirror["fps"] = request.args.get("fps", 2, type=float)
    _mirror["running"] = True
    _mirror["pushed"] = 0
    t = threading.Thread(target=_mirror_worker, daemon=True)
    _mirror["thread"] = t
    t.start()
    return jsonify(**_mpublic())


@bp.route("/api/pico/mirror/stop", methods=["POST", "GET"])
def mstop():
    _mirror["running"] = False
    return jsonify(**_mpublic())
