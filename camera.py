# camera.py - one shared camera producer for the whole API.
#
# A single background thread grabs frames into a latest-frame buffer; every
# module (capture, stream, motion, qr, pico) reads from that one buffer. This
# sidesteps the "camera can only be opened once" problem: one producer, many
# consumers.
#
# On a machine without Picamera2 (e.g. a laptop) it falls back to MOCK mode and
# generates synthetic frames, so the whole API is runnable and testable off-Pi.
import io, os, threading, time

import numpy as np
from PIL import Image, ImageDraw

from config import CFG

# PICAM_BACKEND=fake forces the synthetic-frame backend even on a Pi.
_FORCE_FAKE = os.environ.get("PICAM_BACKEND", "").lower() == "fake"
try:
    if _FORCE_FAKE:
        raise ImportError("PICAM_BACKEND=fake")
    from picamera2 import Picamera2
    _HAVE_PICAMERA = True
except Exception:
    _HAVE_PICAMERA = False


class CameraManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None          # latest RGB ndarray (H, W, 3)
        self._seq = 0
        self._ts = 0.0
        self._running = False
        self._thread = None
        self.mock = not _HAVE_PICAMERA
        self.picam2 = None
        self.camera_error = None    # last init error if real camera fell back to mock
        self._jpeg = (None, None)   # ((seq, quality, size), bytes): last encode, shared by all consumers

    # ---- lifecycle ----
    def start(self, retries=3, retry_delay=2.0):
        if self._running:
            return
        self._running = True
        if not self.mock:
            for attempt in range(1, retries + 1):
                try:
                    self.picam2 = Picamera2()
                    w, h = CFG.stream_size
                    cfg = self.picam2.create_video_configuration(
                        main={"size": (w, h), "format": "RGB888"})
                    self.picam2.configure(cfg)
                    self.picam2.start()
                    time.sleep(0.5)     # let auto-exposure settle
                    self.camera_error = None
                    break
                except Exception as e:
                    print("camera init attempt %d/%d failed: %s" % (attempt, retries, e))
                    try:
                        if self.picam2 is not None:
                            self.picam2.close()
                    except Exception:
                        pass
                    self.picam2 = None
                    if attempt < retries:
                        time.sleep(retry_delay)
                    else:
                        # Real camera never came up (loose ribbon, not yet
                        # enumerated at boot, held by a stale process, ...).
                        # Fall back to mock instead of crashing the process --
                        # a dead API on first boot is worse than a mock one.
                        self.camera_error = str(e)
                        self.mock = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        interval = 1.0 / max(1, CFG.capture_fps)
        i = 0
        while self._running:
            try:
                if self.mock:
                    arr = self._mock_frame(i)
                else:
                    arr = self.picam2.capture_array("main")
                    if CFG.swap_rb and arr.ndim == 3 and arr.shape[2] >= 3:
                        arr = np.ascontiguousarray(arr[:, :, 2::-1])   # BGR(x) -> RGB
                with self._lock:
                    self._frame = arr
                    self._seq += 1
                    self._ts = time.time()
            except Exception as e:
                print("camera loop error:", e)
                time.sleep(0.5)
            i += 1
            time.sleep(interval)

    def _mock_frame(self, i):
        w, h = CFG.stream_size
        img = Image.new("RGB", (w, h), (18, 20, 28))
        d = ImageDraw.Draw(img)
        x = (i * 7) % w
        d.ellipse([x - 30, h // 2 - 30, x + 30, h // 2 + 30], fill=(255, 205, 60))
        d.text((10, 10), "PICAM MOCK  frame %d" % i, fill=(140, 200, 255))
        d.text((10, h - 20), time.strftime("%H:%M:%S"), fill=(120, 220, 160))
        return np.asarray(img)

    # ---- consumers ----
    def get_frame(self):
        with self._lock:
            return self._frame

    def get_jpeg(self, quality=None, size=None):
        with self._lock:
            arr, seq = self._frame, self._seq
            key = (seq, quality or CFG.jpeg_quality, size)
            if self._jpeg[0] == key:
                return self._jpeg[1]
        if arr is None:
            return None
        img = Image.fromarray(arr)
        if img.mode != "RGB":
            img = img.convert("RGB")
        if size:
            img = img.resize(size)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=key[1])
        data = buf.getvalue()
        with self._lock:
            self._jpeg = (key, data)    # shortcut: one slot, so alternating sizes/qualities thrash it
        return data

    @property
    def running(self):
        return self._running

    @property
    def seq(self):
        return self._seq


cam = CameraManager()
