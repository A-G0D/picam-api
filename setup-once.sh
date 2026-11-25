#!/usr/bin/env bash
# setup-once.sh - runs ONCE on the first networked boot, as root, via the
# picam-setup.service that firstrun.sh installs. Installs system deps + the
# venv, wires up the picam service, then disables itself.
set -e
U=agoda
APP=/home/$U/picam-api
LOG=/home/$U/picam-setup.log
exec >>"$LOG" 2>&1
echo "=== picam setup start $(date) ==="

# wait for real internet (through the Windows hotspot's shared connection)
for i in $(seq 1 40); do
    if getent hosts deb.debian.org >/dev/null 2>&1 || ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; then
        echo "net up after ${i} tries"; break
    fi
    echo "waiting for net ($i)"; sleep 5
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3-picamera2 python3-libcamera python3-venv python3-pip \
    libzbar0 ffmpeg

sudo -u "$U" python3 -m venv --system-site-packages "$APP/venv"
sudo -u "$U" "$APP/venv/bin/pip" install --upgrade pip
sudo -u "$U" "$APP/venv/bin/pip" install flask pillow numpy pyzbar

sed "s|__APPDIR__|$APP|g; s|__USER__|$U|g" "$APP/picam.service" \
    > /etc/systemd/system/picam.service
systemctl daemon-reload
systemctl enable picam
systemctl restart picam

systemctl disable picam-setup.service
echo "=== picam setup done $(date) ==="
