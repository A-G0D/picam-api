<#
provision.ps1 - drop the picam auto-connect kit onto a Raspberry Pi OS boot
partition, LOCALLY on this PC (never over SMB), and patch cmdline.txt so it
self-provisions on first boot.

Usage (run in Windows PowerShell or pwsh):
    .\provision.ps1 -BootDrive E:
    .\provision.ps1 -BootDrive E: -UsbGadget      # Pi Zero only: adds USB ethernet-over-USB

Then: safely eject, PHYSICALLY UNPLUG the reader, replug, and confirm the files
are still there (the dead-card test). Only then boot the Pi.
#>
param(
    [Parameter(Mandatory=$true)][string]$BootDrive,
    [switch]$UsbGadget
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$app  = Split-Path -Parent $here    # ...\picam-api

$BootDrive = $BootDrive.TrimEnd('\')
if ($BootDrive -notmatch ':$') { $BootDrive = "${BootDrive}:" }

# --- validate it's really a Pi boot partition ---
if (-not (Test-Path "$BootDrive\cmdline.txt") -or -not (Test-Path "$BootDrive\config.txt")) {
    throw "$BootDrive doesn't look like a Raspberry Pi OS boot partition (no cmdline.txt/config.txt). Flash Raspberry Pi OS first, or point at the small FAT 'bootfs' partition."
}
Write-Host "Target boot partition: $BootDrive" -ForegroundColor Cyan

function Copy-AsLF($src, $dst) {
    $text = [IO.File]::ReadAllText($src) -replace "`r`n","`n" -replace "`r","`n"
    [IO.File]::WriteAllText($dst, $text, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "  wrote $dst (LF)"
}

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
$envVars = Get-DotEnv "$here\.env"
foreach ($k in @('PICAM_SSID','PICAM_PSK','PICAM_USER_PASSWORD')) {
    if (-not $envVars.ContainsKey($k)) {
        Write-Host "  WARN: $k not set in sdcard-provision\.env, firstrun.sh will keep its __${k}__ placeholder" -ForegroundColor Yellow
    }
}

# --- 1. scripts to boot root, forced LF line endings, secrets substituted in ---
$firstrunText = ([IO.File]::ReadAllText("$here\firstrun.sh") -replace "`r`n","`n" -replace "`r","`n")
$firstrunText = $firstrunText.Replace('__PICAM_SSID__', $envVars['PICAM_SSID'])
$firstrunText = $firstrunText.Replace('__PICAM_PSK__', $envVars['PICAM_PSK'])
$firstrunText = $firstrunText.Replace('__PICAM_USER_PASSWORD__', $envVars['PICAM_USER_PASSWORD'])
[IO.File]::WriteAllText("$BootDrive\firstrun.sh", $firstrunText, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  wrote $BootDrive\firstrun.sh (LF, secrets substituted from .env)"
Copy-AsLF "$app\setup-once.sh"  "$BootDrive\setup-once.sh"

# --- 2. classic headless enablers (harmless belt-and-suspenders) ---
New-Item -ItemType File -Path "$BootDrive\ssh" -Force | Out-Null
Write-Host "  touched $BootDrive\ssh"

# --- 3. stage the app into boot\picam-api (excludes venv/cache/data/git) ---
$dest = "$BootDrive\picam-api"
robocopy $app $dest /MIR /XD venv __pycache__ data .git sdcard-provision /XF *.pyc *.log | Out-Null
Write-Host "  staged app -> $dest"

# --- 4. patch cmdline.txt to run firstrun.sh once on first boot ---
$cmdPath = "$BootDrive\cmdline.txt"
$cmd = ([IO.File]::ReadAllText($cmdPath)).TrimEnd("`r","`n"," ")
if (-not (Test-Path "$cmdPath.bak")) { [IO.File]::WriteAllText("$cmdPath.bak", $cmd) }
if ($cmd -notmatch "systemd\.run=") {
    # Bookworm mounts the FAT at /boot/firmware; that's where firstrun.sh lands
    $cmd += " systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.run_failure_action=reboot systemd.unit=kernel-command-line.target"
    Write-Host "  added systemd.run first-boot hook to cmdline.txt" -ForegroundColor Green
} else {
    Write-Host "  cmdline.txt already has a systemd.run hook, left as-is" -ForegroundColor Yellow
}

# --- 5. optional: USB ethernet-over-USB gadget (Pi Zero ONLY) ---
if ($UsbGadget) {
    $cfgPath = "$BootDrive\config.txt"
    $cfg = [IO.File]::ReadAllText($cfgPath)
    if ($cfg -notmatch "dtoverlay=dwc2") {
        $cfg = $cfg.TrimEnd() + "`n`n[all]`ndtoverlay=dwc2,dr_mode=peripheral`n"
        [IO.File]::WriteAllText($cfgPath, ($cfg -replace "`r`n","`n"), (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "  config.txt: enabled dwc2 (USB gadget)" -ForegroundColor Green
    }
    if ($cmd -notmatch "modules-load=dwc2,g_ether") {
        $cmd = $cmd -replace "(rootwait)", "`$1 modules-load=dwc2,g_ether"
        Write-Host "  cmdline.txt: added modules-load=dwc2,g_ether" -ForegroundColor Green
    }
    Write-Host "  USB gadget on: plug the Zero's DATA usb port into this PC. Reach it at picam.local (link-local)." -ForegroundColor Cyan
    Write-Host "  WARNING: do NOT use -UsbGadget for the Pi 3 A+ (breaks its USB port)." -ForegroundColor Red
}

[IO.File]::WriteAllText($cmdPath, $cmd, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "Now: 1) safely eject the card, 2) PHYSICALLY UNPLUG the reader, 3) replug and re-open $BootDrive" -ForegroundColor Cyan
Write-Host "     4) confirm firstrun.sh is still there and cmdline.txt still has systemd.run  (the dead-card test)" -ForegroundColor Cyan
Write-Host "     5) only then put the card in the Pi and power it on. It boots, provisions, reboots, joins the hotspot." -ForegroundColor Cyan
Write-Host "     6) from this PC: ssh -i `$HOME\.ssh\picam_ed25519 agoda@picam.local   (or agoda@<ip> from the hotspot leases)" -ForegroundColor Cyan
