#!/usr/bin/env bash
# install.sh - set up the picam API on a Raspberry Pi (Bookworm, Lite or Full).
# Installs system deps (picamera2, zbar), a venv with the Python deps, and a
# systemd service so the API starts on boot.
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"
echo "picam install in $APP_DIR as $USER_NAME"

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3-picamera2 python3-libcamera python3-venv python3-pip \
    libzbar0 ffmpeg

# venv that can see the system picamera2 / libcamera packages
python3 -m venv --system-site-packages "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install flask pillow numpy pyzbar

# systemd service (fill in this dir + user)
SVC=/etc/systemd/system/picam.service
sudo bash -c "sed 's|__APPDIR__|$APP_DIR|g; s|__USER__|$USER_NAME|g' \
    '$APP_DIR/picam.service' > $SVC"
sudo systemctl daemon-reload
sudo systemctl enable picam
sudo systemctl restart picam

echo
echo "done. API is on http://<pi-ip>:8080"
echo "  status : sudo systemctl status picam"
echo "  logs   : journalctl -u picam -f"
