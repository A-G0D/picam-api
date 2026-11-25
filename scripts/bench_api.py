#!/usr/bin/env python3
"""Benchmark the picam API with the fake camera backend (no Pi needed).

  python scripts/bench_api.py [--secs 5] [--out results/bench.json]

Measures, over real loopback HTTP against a threaded werkzeug server:
  capture_ms     latency of GET /api/capture (keep-alive, sequential)
  stream         MJPEG frames/s and CPU ms per frame, 1 client and 4 clients
  motion_us      per-frame cost of the motion detector's diff (in-process)
Stream cost is process CPU time per delivered frame (server, 10 fps producer
and clients share one Python process, so it includes all of them). Delivered
fps is also printed but is paced by time.sleep: under `taskpolicy -b` macOS
stretches an 8 ms sleep to ~88 ms, so compare cpu_ms_per_frame, not fps.
"""
import argparse, http.client, json, os, platform, statistics, sys, threading, time

os.environ["PICAM_BACKEND"] = "fake"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from config import CFG
from app import app
from camera import cam
from modules import motion
from werkzeug.serving import make_server


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def capture_latency(port, n=300):
    c = http.client.HTTPConnection("127.0.0.1", port)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        c.request("GET", "/api/capture")
        c.getresponse().read()
        ts.append((time.perf_counter() - t) * 1000)
    return {"p50": round(statistics.median(ts), 2), "p95": round(pct(ts, .95), 2), "n": n}


def stream_fps(port, clients, secs):
    time.sleep(0.5)
    counts = [0] * clients

    def run(i):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/api/stream?fps=12")
        r = c.getresponse()
        end = time.perf_counter() + secs
        tail = b""
        while time.perf_counter() < end:
            chunk = r.read1(65536)
            counts[i] += (tail + chunk).count(b"--frame")
            tail = chunk[-8:]
        c.close()

    ts = [threading.Thread(target=run, args=(i,)) for i in range(clients)]
    t0, c0 = time.perf_counter(), time.process_time()
    [t.start() for t in ts]; [t.join() for t in ts]
    dt = time.perf_counter() - t0
    cpu = time.process_time() - c0
    return {"clients": clients, "total_fps": round(sum(counts) / dt, 1),
            "cpu_ms_per_frame": round(cpu / max(1, sum(counts)) * 1000, 2)}


def encode_cold_ms(n=200):
    """JPEG encode of a fresh frame (what a cache miss costs), bypassing any cache."""
    from PIL import Image
    import io
    arr = cam.get_frame()
    t = time.perf_counter()
    for _ in range(n):
        Image.fromarray(arr).save(io.BytesIO(), format="JPEG", quality=CFG.jpeg_quality)
    return round((time.perf_counter() - t) / n * 1000, 2)


def motion_cost(n=1000):
    import numpy as np
    frames = [cam._mock_frame(i) for i in range(20)]
    best = 1e9
    for _ in range(5):                 # best of 5 batches: filters scheduler noise
        t = time.perf_counter()
        prev = motion._gray_small(frames[0])
        for i in range(n):
            g = motion._gray_small(frames[i % 20])
            float(np.abs(g - prev).mean())
            prev = g
        best = min(best, (time.perf_counter() - t) / n * 1e6)
    return {"per_frame_us": round(best, 1), "n": n}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    port = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    while cam.get_frame() is None:
        time.sleep(0.01)
    capture_latency(port, 30)   # warm up
    res = {"machine": "%s %s, Python %s" % (platform.system(), platform.machine(), platform.python_version()),
           "frame_size": list(CFG.stream_size), "jpeg_quality": CFG.jpeg_quality,
           "capture_ms": capture_latency(port), "jpeg_encode_cold_ms": encode_cold_ms(),
           "stream": [stream_fps(port, 1, a.secs), stream_fps(port, 4, a.secs)],
           "motion": motion_cost()}
    print(json.dumps(res, indent=2))
    if a.out:
        json.dump(res, open(a.out, "w"), indent=2)
    os._exit(0)
