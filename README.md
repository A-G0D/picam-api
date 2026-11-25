# picam-api

A Flask HTTP API for a Raspberry Pi camera (still capture, MJPEG stream, timelapse, motion detection, QR scan, push to a Pico display) that also runs on any machine through a fake camera backend.

## Demo

```
$ PICAM_BACKEND=fake python app.py &
$ curl -s localhost:8080/api/health
{"camera_error":null,"frames":28,"mock":true,"ok":true,"running":true,"size":[640,480]}
$ curl -s -o c.jpg -w "%{http_code} %{size_download} bytes %{time_total}s\n" localhost:8080/api/capture
200 8139 bytes 0.010327s
```

## Quickstart

```bash
pip install -r requirements.txt
PICAM_BACKEND=fake python app.py      # synthetic 640x480 frames, no Pi needed
# open http://localhost:8080
python -m pytest -q                   # 17 tests, mock backend
python scripts/bench_api.py --out results/run.json
```

On a Pi, drop `PICAM_BACKEND` and the picamera2 path is used. Without picamera2 installed, or if the camera fails to start after 3 tries, the API falls back to the fake backend and `/api/health` reports `camera_error`.

## How it works

1. One producer thread (`camera.py`) grabs a frame every 1/`capture_fps` s into a latest-frame buffer. Real source: Picamera2. Fake source: a Pillow-drawn frame with a moving circle.
2. Every module (capture, stream, motion, qr, pico, timelapse) reads that buffer, so the camera is opened once.
3. `get_jpeg` keeps the last encode keyed by (frame number, quality, size). Viewers of the same frame share one JPEG encode.
4. `/api/stream` is multipart MJPEG, one `get_jpeg` per tick per client.
5. Motion takes every 8th pixel, averages to gray, and compares the mean absolute difference between consecutive frames to a threshold.

## Results

Measured on an Apple M5 Pro (Darwin, Python 3.9.6) with the fake backend, 640x480, JPEG quality 85, under `nice -n 10 taskpolicy -b`. Median of 5 runs each of `scripts/bench_api.py`; raw files are `results/before_N.json`, `results/after_N.json`, medians in `results/summary.json`. "Before" is the code without the JPEG cache.

| Metric | Before | After | Market standard | Goal |
|---|---|---|---|---|
| Server CPU per streamed frame, 4 viewers | 1.74 ms | 1.07 ms (-38%) | none published for picamera2 [1][2] | n/a |
| Server CPU per streamed frame, 1 viewer | 3.05 ms | 3.27 ms (no change) | same | n/a |
| `/api/capture` latency p50 (loopback) | 2.14 ms | 2.02 ms (no change) | same | n/a |
| Motion diff per frame | 121 us | not improved | same | n/a |

Market reference points, none of them the same measurement:

- mjpg-streamer software JPEG at 640x480 on a Pi: 60-80% CPU, 15-20% at 320x240 (OctoPrint forum report) [3].
- motionEyeOS "Fast Network Camera": about 4 MB/s throughput at normal clock, 7 MB/s turbo [4].
- A 2017 blog reports about 28 fps MJPEG from a Pi 3 over Wi-Fi with the old picamera library (not rechecked) [5].
- The picamera2 manual documents MJPEG encoding but gives no fps or latency figure at 640x480 [1]. MediaMTX and uStreamer publish no usable Pi numbers [2][6].

I found no published picamera2 MJPEG fps or capture latency at this size, so there is no number to set a 1.5x goal against, and I am not setting one. A Mac running a fake camera also says nothing about Pi speed: the useful result is that the API layer costs about 1 to 3 ms of CPU per frame here, so on a Pi it should be limited by the sensor and the JPEG encoder, not the Flask code. That last part is a prediction, not a measurement.

Caveats on the numbers:

- Motion timings varied 90 to 750 us between runs with identical code, because the machine was loaded. The spread is larger than any effect I could measure, so I left motion unchanged. The diff itself costs about 45 us per frame in a quiet `timeit`.
- `taskpolicy -b` stretches `time.sleep` about 10x, so delivered fps (5-6 for one viewer, 23 for four) is throttled by the OS, not by the code. CPU per frame is the number to compare.
- Capture p95 ranges from 4 to 18 ms across runs and is not a stable result.
- Gain from the cache needs more than one viewer on the same frame. One viewer sees no change.

Sources:
[1] https://pip-assets.raspberrypi.com/categories/1044-raspberry-pi-ai-camera/documents/RP-008156-DS-3-picamera2-manual.pdf
[2] https://github.com/bluenviron/mediamtx
[3] https://community.octoprint.org/t/i-see-high-cpu-usage-when-mjpg-streamer-is-running/202
[4] https://github.com/motioneye-project/motioneyeos/wiki/Fast-Network-Camera
[5] https://jmlb.github.io/robotics/2017/11/22/picamera_streaming_video
[6] https://github.com/pikvm/ustreamer

## Tested on real hardware

- Tested: a Pi 3 A+ with a v1.3 camera ran the API on port 8080 under systemd and returned real captures (as of 2026-07-14, from my notes and the repo history). The picamera2 capture path and the RGB/BGR swap come from that run.
- Not tested on a Pi: the timelapse worker, QR scan, motion on real frames, long-running MJPEG, and the Pico push (the Pico push is tested end to end only against a stub in `tests/test_pico.py`).
- Not tested at all: any speed number on Pi hardware, and a comparison against MediaMTX or motion.
- The automated tests cover only the fake backend.

## Layout

```
app.py            Flask app, wires every module in, serves the dashboard
camera.py         one shared camera producer (1 thread -> latest-frame buffer)
config.py         all settings; override with a config.json next to it
static/index.html dashboard (live view + buttons for every endpoint)
modules/
  capture.py      still photos
  stream.py       MJPEG live stream
  timelapse.py    snap every N seconds
  motion.py       frame-diff motion detector (can save + push to Pico)
  qr.py           QR / barcode decode (pyzbar)
  pico.py         send frames to the Pico Display frame + live-mirror
sdcard-provision/ headless SD card setup (firstrun.sh, provision.ps1, .env.example)
install.sh        apt deps + venv + systemd service (run once on the Pi)
picam.service     systemd unit template
```

## Endpoints

| method | path | what |
|--------|------|------|
| GET  | `/`                       | dashboard |
| GET  | `/api/health`             | camera + server status |
| GET  | `/api/config`             | effective config |
| GET  | `/api/capture`            | live frame as JPEG |
| GET  | `/api/capture?save=1`     | save photo, return name |
| GET  | `/api/capture?w=1024&h=768&q=70` | resize / quality |
| GET  | `/api/capture/list`       | saved photos |
| GET  | `/api/capture/file/<name>`| download a photo |
| GET  | `/api/stream?fps=12`      | MJPEG live stream |
| POST | `/api/timelapse/start?interval=5&count=0` | start (count 0 = forever) |
| POST | `/api/timelapse/stop`     | stop |
| GET  | `/api/timelapse/status`   | status |
| GET  | `/api/timelapse/list`     | frames captured |
| POST | `/api/motion/start?threshold=6&save=1&push=0` | start detector |
| POST | `/api/motion/stop`        | stop |
| GET  | `/api/motion/status`      | running + event count + last score |
| GET  | `/api/motion/events`      | saved event frames |
| GET  | `/api/qr/scan`            | decode QR / barcodes in view |
| GET  | `/api/pico/find`          | find the Pico's IP (arp by MAC) |
| POST | `/api/pico/push`          | send current frame to the Pico (live) |
| POST | `/api/pico/push?store=1`  | send to the Pico gallery |
| POST | `/api/pico/clear`         | wipe the Pico gallery |
| GET  | `/api/pico/list`          | proxy the Pico's `/list` |
| POST | `/api/pico/mirror/start?fps=2` | live-mirror the camera onto the Pico |
| POST | `/api/pico/mirror/stop`   | stop mirroring |

Every POST route also answers GET, so you can test everything from a browser
address bar or `curl`.

## Config overrides

Drop a `config.json` next to `config.py` (gitignored, local only):

```json
{
  "stream_size": [1280, 720],
  "jpeg_quality": 80,
  "pico_ip": "192.168.137.251",
  "motion_threshold": 8.0,
  "swap_rb": true
}
```

- `pico_ip` — set it if arp discovery misses; otherwise leave null to auto-find
  by the Pico's MAC.
- `swap_rb` — Picamera2's `RGB888` is really BGR. Left true so colours are
  correct. If reds and blues look swapped, flip it.

## The Pico integration

The Pico Display frame (`image_show.py`, a separate project) runs a tiny web
server on `:4242` and accepts raw JPEG on `POST /` (live) and `POST /store`
(gallery), max 90000 bytes, letterboxed to 320x240. `modules/pico.py` does
exactly that:

- `push` — one frame from the Pi camera onto the Pico screen
- `mirror` — a low-fps loop that turns the Pico into a live viewfinder of the
  Pi camera (keep fps low, ~2; the Pico decodes each JPEG single-threaded)
- `motion?push=1` — the Pico shows whatever tripped the motion detector

## Render a timelapse to video (on the Pi)

```bash
ffmpeg -framerate 24 -pattern_type glob -i 'data/timelapse/tl_*.jpg' timelapse.mp4
```

## Reliability

`camera.py`'s `start()` retries real-camera init (Picamera2 construct/configure/start)
up to 3 times with a short delay, then falls back to mock mode instead of
crashing the process. On first boot a camera that isn't fully enumerated yet,
or a ribbon that's marginally seated, used to kill the whole API and leave
systemd restart-looping with nothing to hit; now the API stays up, mock
frames flow, and `/api/health` reports `camera_error` so you can see what
failed without SSHing in blind.
## Tests

```bash
python -m pytest -q
```

Runs the Flask app on the fake backend: health, config, capture, dashboard, motion, timelapse, Pico push, the camera fallback, `PICAM_BACKEND=fake`, and the JPEG cache. CI runs the same command on ubuntu.

## Limits

- The JPEG cache has one slot. Two viewers asking for different sizes or qualities of the same frame evict each other and each pays the encode.
- No real-Pi numbers (see above).
- `pico_ip` discovery uses ARP, so the Pico must be on the same subnet. Otherwise set it in `config.json`.
- Provisioning scripts assume a Windows PC hosting the hotspot.
- The Pi login password and hotspot PSK used to live in plaintext on disk (never committed) and were replaced with `.env` placeholders. If a Pi was flashed with the old values, rotate them on the device and router by hand.
- No authentication on the HTTP API. Keep it on a trusted network.

## License

MIT. See `LICENSE`.
