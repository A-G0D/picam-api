# qr.py - decode QR codes / barcodes from the current frame (pyzbar).
#
#   GET /api/qr/scan   -> {"count": N, "results": [{type, data, rect}, ...]}
from flask import Blueprint, jsonify
from PIL import Image

from camera import cam

bp = Blueprint("qr", __name__)

try:
    from pyzbar import pyzbar
    _HAVE = True
except Exception:
    _HAVE = False


@bp.route("/api/qr/scan")
def scan():
    if not _HAVE:
        return jsonify(error="pyzbar not installed "
                             "(apt install libzbar0; pip install pyzbar)"), 501
    arr = cam.get_frame()
    if arr is None:
        return jsonify(error="no frame yet"), 503
    img = Image.fromarray(arr).convert("L")   # grayscale decodes most reliably
    results = []
    for d in pyzbar.decode(img):
        results.append({
            "type": d.type,
            "data": d.data.decode("utf-8", "replace"),
            "rect": [d.rect.left, d.rect.top, d.rect.width, d.rect.height],
        })
    return jsonify(count=len(results), results=results)
