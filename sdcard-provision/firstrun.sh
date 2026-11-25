#!/bin/bash
# firstrun.sh - headless first-boot provisioning for the picam Pi.
# Invoked once from cmdline.txt (systemd.run=). Creates the control user, turns
# on SSH with the control key, joins the PC hotspot, stages the app, arms the
# one-time setup service, then removes itself from cmdline and reboots.
#
# Safe to run on Bookworm (NetworkManager) or Bullseye (wpa_supplicant) images.
#
# __PICAM_USER_PASSWORD__ / __PICAM_SSID__ / __PICAM_PSK__ below are placeholders.
# provision.ps1 / provision_local.ps1 substitute them from a local .env (see
# .env.example) before this file is copied to the SD card. If you see the
# literal placeholders on a booted Pi, provisioning did not substitute them.
set +e

# boot FAT is /boot/firmware on Bookworm, /boot on Bullseye
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot

LOG="$BOOT/firstrun.log"
exec >>"$LOG" 2>&1
echo "=== firstrun $(date) boot=$BOOT ==="

U=agoda
PW='__PICAM_USER_PASSWORD__'
HOST=picam
PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIbBmlokSqh/18mkBHlt6BiDobMIBKZqyXntT4cFEb3P picam-control'
SSID='__PICAM_SSID__'
PSK='__PICAM_PSK__'

# --- hostname -------------------------------------------------------------
echo "$HOST" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\t$HOST/g" /etc/hosts
hostnamectl set-hostname "$HOST" 2>/dev/null

# --- control user ---------------------------------------------------------
if ! id "$U" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$U"
fi
for g in sudo video gpio i2c spi dialout plugdev netdev render; do
    usermod -aG "$g" "$U" 2>/dev/null
done
echo "$U:$PW" | chpasswd
echo "$U ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010_${U}-nopasswd
chmod 440 /etc/sudoers.d/010_${U}-nopasswd

# --- ssh + control key ----------------------------------------------------
systemctl enable ssh 2>/dev/null
touch "$BOOT/ssh"
install -d -m 700 -o "$U" -g "$U" /home/$U/.ssh
echo "$PUBKEY" > /home/$U/.ssh/authorized_keys
chmod 600 /home/$U/.ssh/authorized_keys
chown -R "$U:$U" /home/$U/.ssh

# --- wifi: NetworkManager keyfile (Bookworm) ------------------------------
NMDIR=/etc/NetworkManager/system-connections
if [ -d /etc/NetworkManager ]; then
    mkdir -p "$NMDIR"
    cat > "$NMDIR/hotspot.nmconnection" <<EOF
[connection]
id=hotspot
type=wifi
autoconnect=true
autoconnect-priority=100

[wifi]
mode=infrastructure
ssid=$SSID

[wifi-security]
key-mgmt=wpa-psk
psk=$PSK

[ipv4]
method=auto

[ipv6]
method=auto
EOF
    chmod 600 "$NMDIR/hotspot.nmconnection"
    chown root:root "$NMDIR/hotspot.nmconnection"
fi

# --- wifi: wpa_supplicant fallback (Bullseye / belt-and-suspenders) --------
if [ -d /etc/wpa_supplicant ]; then
    cat > /etc/wpa_supplicant/wpa_supplicant.conf <<EOF
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
network={
    ssid="$SSID"
    psk="$PSK"
    key_mgmt=WPA-PSK
    priority=100
}
EOF
    chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
fi
raspi-config nonint do_wifi_country US 2>/dev/null
rfkill unblock wifi 2>/dev/null

# --- stage the app + setup-once -------------------------------------------
if [ -d "$BOOT/picam-api" ]; then
    rm -rf /home/$U/picam-api
    cp -r "$BOOT/picam-api" /home/$U/picam-api
    chown -R "$U:$U" /home/$U/picam-api
fi
if [ -f "$BOOT/setup-once.sh" ]; then
    cp "$BOOT/setup-once.sh" /home/$U/setup-once.sh
    chmod +x /home/$U/setup-once.sh
    chown "$U:$U" /home/$U/setup-once.sh
fi

# --- arm the one-time setup service (installs deps on first networked boot) -
cat > /etc/systemd/system/picam-setup.service <<EOF
[Unit]
Description=picam one-time setup
After=network-online.target
Wants=network-online.target
ConditionPathExists=/home/$U/setup-once.sh

[Service]
Type=oneshot
ExecStart=/home/$U/setup-once.sh
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF
systemctl enable picam-setup.service 2>/dev/null

# --- remove ourselves from cmdline and reboot -----------------------------
CMD="$BOOT/cmdline.txt"
cp "$CMD" "$CMD.firstrun.bak"
sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=[^ ]*||g' "$CMD"

echo "=== firstrun done $(date), rebooting ==="
sync
sleep 2
reboot
