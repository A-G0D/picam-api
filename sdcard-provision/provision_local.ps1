# provision_local.ps1 - RUNS ON abhaylp2 (the laptop holding the SD card).
# Writes the picam auto-connect kit to the SD boot partition with a LOCAL copy
# (SMB write-back to removable media never commits, so this must run on-box).
# Logs everything to C:\picam_stage\provision_out.txt.

$log = 'C:\picam_stage\provision_out.txt'
function L($m){ Add-Content -Path $log -Value $m }
Set-Content -Path $log -Value "=== provision start $(Get-Date) ==="

try {
  $utf8 = New-Object System.Text.UTF8Encoding($false)

  # --- load secrets from a local, gitignored .env (see .env.example) ---
  function Get-DotEnv($path) {
    $vars = @{}
    if (Test-Path $path) {
      Get-Content $path | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
          $vars[$matches[1]] = $matches[2]
        }
      }
    }
    return $vars
  }
  $here = Split-Path -Parent $MyInvocation.MyCommand.Path
  $envVars = Get-DotEnv "$here\.env"
  foreach ($k in @('PICAM_SSID','PICAM_PSK','PICAM_USER_PASSWORD')) {
    if (-not $envVars.ContainsKey($k)) {
      L "WARN: $k not set in sdcard-provision\.env, firstrun.sh will keep its __${k}__ placeholder"
    }
  }

  # --- log all fixed/removable volumes so we can see the card ---
  L "-- volumes --"
  Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
    L ("  {0}: label='{1}' fs={2} size={3}GB drivetype={4}" -f $_.DriveLetter,$_.FileSystemLabel,$_.FileSystem,[math]::Round($_.Size/1GB,2),$_.DriveType)
  }

  # --- find the Pi boot partition (FAT with cmdline.txt + config.txt, not C:) ---
  $boot = $null
  foreach ($v in (Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'C' })) {
    $d = "$($v.DriveLetter):"
    if ((Test-Path "$d\cmdline.txt") -and (Test-Path "$d\config.txt")) { $boot = $d; break }
  }
  if (-not $boot) { L "ERROR: no Raspberry Pi boot partition found (need a FAT drive with cmdline.txt + config.txt). Is the card inserted?"; exit 1 }
  L "boot partition detected: $boot"

  # --- firstrun.sh (headless first-boot provisioning) ---
  $firstrun = @'
#!/bin/bash
# firstrun.sh - headless first-boot provisioning for the picam Pi.
set +e
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

echo "$HOST" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\t$HOST/g" /etc/hosts
hostnamectl set-hostname "$HOST" 2>/dev/null

if ! id "$U" >/dev/null 2>&1; then useradd -m -s /bin/bash "$U"; fi
for g in sudo video gpio i2c spi dialout plugdev netdev render; do usermod -aG "$g" "$U" 2>/dev/null; done
echo "$U:$PW" | chpasswd
echo "$U ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010_${U}-nopasswd
chmod 440 /etc/sudoers.d/010_${U}-nopasswd

systemctl enable ssh 2>/dev/null
touch "$BOOT/ssh"
install -d -m 700 -o "$U" -g "$U" /home/$U/.ssh
echo "$PUBKEY" > /home/$U/.ssh/authorized_keys
chmod 600 /home/$U/.ssh/authorized_keys
chown -R "$U:$U" /home/$U/.ssh

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
fi

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

CMD="$BOOT/cmdline.txt"
cp "$CMD" "$CMD.firstrun.bak"
sed -i 's| systemd.run=[^ ]*||g; s| systemd.run_success_action=[^ ]*||g; s| systemd.run_failure_action=[^ ]*||g; s| systemd.unit=[^ ]*||g' "$CMD"
echo "=== firstrun done $(date), rebooting ==="
sync
sleep 2
reboot
'@

  # --- setup-once.sh (installs deps + starts the API on first networked boot) ---
  $setup = @'
#!/usr/bin/env bash
set -e
U=agoda
APP=/home/$U/picam-api
LOG=/home/$U/picam-setup.log
exec >>"$LOG" 2>&1
echo "=== picam setup start $(date) ==="
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
'@

  $firstrunOut = ($firstrun -replace "`r`n","`n" -replace "`r","`n")
  $firstrunOut = $firstrunOut.Replace('__PICAM_SSID__', $envVars['PICAM_SSID'])
  $firstrunOut = $firstrunOut.Replace('__PICAM_PSK__', $envVars['PICAM_PSK'])
  $firstrunOut = $firstrunOut.Replace('__PICAM_USER_PASSWORD__', $envVars['PICAM_USER_PASSWORD'])
  [IO.File]::WriteAllText("$boot\firstrun.sh",    $firstrunOut, $utf8)
  [IO.File]::WriteAllText("$boot\setup-once.sh",  ($setup    -replace "`r`n","`n" -replace "`r","`n"), $utf8)
  New-Item -ItemType File -Path "$boot\ssh" -Force | Out-Null
  L "wrote firstrun.sh, setup-once.sh, ssh"

  # --- stage the app from C:\picam_stage\picam-api ---
  if (Test-Path 'C:\picam_stage\picam-api') {
    robocopy 'C:\picam_stage\picam-api' "$boot\picam-api" /MIR /XD venv __pycache__ data .git sdcard-provision /XF *.pyc *.log | Out-Null
    L "staged app -> $boot\picam-api"
  } else {
    L "WARN: C:\picam_stage\picam-api not found, app not staged (firstrun still sets up wifi/ssh)"
  }

  # --- patch cmdline.txt ---
  $cmdPath = "$boot\cmdline.txt"
  $cmd = ([IO.File]::ReadAllText($cmdPath)).TrimEnd("`r","`n"," ")
  if (-not (Test-Path "$cmdPath.bak")) { [IO.File]::WriteAllText("$cmdPath.bak", $cmd) }
  if ($cmd -notmatch "systemd\.run=") {
    $cmd += " systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.run_failure_action=reboot systemd.unit=kernel-command-line.target"
    L "added systemd.run hook to cmdline.txt"
  } else { L "cmdline.txt already had systemd.run, left as-is" }
  [IO.File]::WriteAllText($cmdPath, $cmd, $utf8)

  L ("cmdline now: " + $cmd)
  L ("boot listing: " + ((Get-ChildItem $boot | Select-Object -Expand Name) -join ', '))
  L "=== provision DONE $(Get-Date) ==="
}
catch {
  L ("EXCEPTION: " + $_.Exception.Message)
  exit 1
}
