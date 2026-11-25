# picam SD auto-connect kit

Drops the whole auto-connect setup onto a Raspberry Pi OS card so a fresh Pi
boots, joins this PC's hotspot, turns on SSH, and installs the camera API on its
own. Provision it **locally on this PC** (never SMB) and always run the
**persistence test** below, that's what caught the dead card last time.

## What's baked in
- user `agoda` / password from `PICAM_USER_PASSWORD` in `.env`, passwordless sudo
- SSH on, authorized key = `~/.ssh/picam_ed25519` (`picam-control`)
- WiFi auto-joins the hotspot named in `PICAM_SSID`/`PICAM_PSK` in `.env` (NetworkManager keyfile + wpa_supplicant fallback)
- hostname `picam` (so `picam.local` works via mDNS)

Copy `.env.example` to `.env` in this directory and fill in real values before
running `provision.ps1` / `provision_local.ps1` — they substitute these into
`firstrun.sh` before it's written to the SD card. `.env` is gitignored; never
commit it.
- app staged to `/home/agoda/picam-api`, `picam-setup.service` installs deps + starts it on first networked boot
- API on `http://<pi>:8080`, pushes to the Pico frame on `:4242`

## Prereqs
1. The card already has **Raspberry Pi OS (Bookworm)** flashed (it has `cmdline.txt` + `config.txt` on the small FAT `bootfs` partition). If blank, flash RPi OS first with Raspberry Pi Imager.
2. **Hotspot is ON** on this PC (`hotspot_on.cmd`), so the Pi has something to join.
3. A USB microSD reader on THIS PC.

## Do it (one command)
1. Insert the card. Note the drive letter of the small FAT partition (labeled `bootfs`), e.g. `E:`.
2. In PowerShell:
   ```
   cd C:\Users\agodavarthy\Claude\projects\picam-api\sdcard-provision
   .\provision.ps1 -BootDrive E:
   ```
   For a **Pi Zero over USB** (ethernet-over-USB straight to this PC), add `-UsbGadget`:
   ```
   .\provision.ps1 -BootDrive E: -UsbGadget
   ```

## Persistence test (do NOT skip)
The old reader faked writes by keeping the card powered. Real test:
1. Safely eject the card in Windows.
2. **Physically unplug the reader from USB.**
3. Replug, open `E:` again.
4. Confirm `firstrun.sh` is there and `cmdline.txt` still ends with `systemd.run=...`.
   If they vanished, the card/reader is bad. Get a Samsung EVO / SanDisk Ultra.

## Boot + connect
1. Card into the Pi, power on. First boot: runs `firstrun.sh`, reboots itself, joins the hotspot. Give it ~2-3 min (plus a few for the one-time apt install).
2. From this PC:
   ```
   ssh -i $HOME\.ssh\picam_ed25519 agoda@picam.local
   ```
   If `.local` doesn't resolve, find the IP in the hotspot leases: `arp -a | findstr 192.168.137`
3. API check: `http://<pi-ip>:8080`. Setup log on the Pi: `/home/agoda/picam-setup.log`.

## "Wire directly to this computer"
- **Pi 3 A+**: no. It has no ethernet and its USB port can't do gadget mode. WiFi hotspot only.
- **Pi Zero W / Zero 2 W**: yes, use `-UsbGadget`. Plug the Zero's **data** micro-USB (the inner one, not PWR) into this PC. It appears as a USB network device; reach it at `picam.local`. Windows loads the RNDIS driver automatically on most builds.

## Which Zero do you have? (matters)
- **Zero 2 W** (quad-core): runs 64-bit or 32-bit Bookworm. Same as the 3A+.
- **Zero W / Zero** (single-core ARMv6): needs the **32-bit (armhf)** Raspberry Pi OS image. A 64-bit card will NOT boot on it. Check the board or `cat /proc/cpuinfo` on a working boot.

## Troubleshooting
- Won't join wifi: hotspot must be on + 2.4GHz; check `firstrun.log` on the boot FAT after a boot.
- apt install fails (no internet on Pi): the Windows hotspot shares the corp ethernet; corp may block it. SSH in, check `picam-setup.log`, rerun `/home/agoda/setup-once.sh`.
- Colors swapped in images: set `swap_rb` false in `picam-api/config.json`.
- Pico not found: set `pico_ip` in config.
