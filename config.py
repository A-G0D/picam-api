# config.py - central settings for the picam API.
# Everything reads from here so behaviour is tweakable in one place.
# Drop a config.json next to this file to override any field at runtime.
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))


class Config:
    def __init__(self):
        # ---- camera ----
        self.stream_size = (640, 480)     # live/stream/derived-frame resolution
        self.capture_fps = 10             # producer loop rate (frames/sec)
        self.jpeg_quality = 85
        self.swap_rb = True               # Picamera2 "RGB888" is really BGR; flip it.
                                          # If colours look wrong, set this false.
        # ---- storage ----
        self.data_dir      = os.path.join(_HERE, "data")
        self.capture_dir   = os.path.join(self.data_dir, "captures")
        self.timelapse_dir = os.path.join(self.data_dir, "timelapse")
        self.motion_dir    = os.path.join(self.data_dir, "motion")
        # ---- pico image frame (see image_show.py on the Pico) ----
        self.pico_ip   = None                 # None = auto-find by MAC over arp
        self.pico_mac  = "28-cd-c1-0d-58-2e"
        self.pico_port = 4242
        self.pico_screen = (320, 240)
        self.pico_max_bytes = 90000
        # ---- motion ----
        self.motion_threshold = 6.0       # mean abs grayscale diff to trip an event
        # ---- server ----
        self.host = "0.0.0.0"
        self.port = 8080

        self._load_overrides()
        for d in (self.data_dir, self.capture_dir, self.timelapse_dir, self.motion_dir):
            os.makedirs(d, exist_ok=True)

    def _load_overrides(self):
        p = os.path.join(_HERE, "config.json")
        if not os.path.exists(p):
            return
        try:
            with open(p) as f:
                data = json.load(f)
            for k, v in data.items():
                if not hasattr(self, k):
                    continue
                cur = getattr(self, k)
                if isinstance(cur, tuple) and isinstance(v, list):
                    v = tuple(v)            # json has no tuples
                setattr(self, k, v)
        except Exception as e:
            print("config override failed:", e)

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


CFG = Config()
