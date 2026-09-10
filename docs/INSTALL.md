# Installing Cosmic Pulse

Three supported ways to run Pulse. All are **local-only** — no cloud, no account.

| Method | Who it’s for |
|--------|----------------|
| **`./install.sh --service`** | Most people (Pop!_OS, Ubuntu, Fedora, Arch, …) |
| **`python3 server.py`** | Development |
| **`.deb`** | Optional apt install on Debian/Pop/Ubuntu |

There is **no RPM** in 0.1. Fedora / Nobara / Bazzite: use `install.sh` (see below). An untested distro package would be worse than a script that works.

## Requirements

- Linux with `/proc` and `/sys`
- **Python 3.11+**
- `psutil` and `PyYAML` (distro packages or pip)
- `rsync` (for `install.sh` / the .deb builder)
- `systemd --user` if you want the background service

### Pop!_OS / Ubuntu / Debian

```bash
sudo apt install python3-psutil python3-yaml python3-venv python3-pip rsync
```

### Fedora / Nobara

```bash
sudo dnf install python3-psutil python3-pyyaml python3-pip rsync
```

Temps and fans come from `/sys/class/hwmon`. `lm-sensors` is not required. Steam is optional (game-aware Guidance).

## Option 1 — Install script (recommended)

```bash
git clone https://github.com/tramonkamble/cosmic-pulse.git
cd cosmic-pulse
chmod +x install.sh
./install.sh --service
cosmic-pulse --open
```

This copies the app to `~/.local/share/cosmic-pulse`, creates a venv when it can, installs `~/.local/bin/cosmic-pulse`, a `.desktop` launcher, and a **systemd user** unit.

| Flag | Meaning |
|------|---------|
| `--service` | `systemctl --user enable --now cosmic-pulse` |
| `--dir PATH` | Custom install directory |
| `--port 8765` | HTTP port (`PULSE_PORT`) |
| `--system-python` | Skip venv; use distro/pip packages |
| `--uninstall` | Remove app + service; **keep** `pulse.db` / config |
| `--purge` | Uninstall and delete history/config too |

Ensure `~/.local/bin` is on your `PATH`.

## Option 2 — Manual / development

```bash
git clone https://github.com/tramonkamble/cosmic-pulse.git
cd cosmic-pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
# python3 server.py --help
# python3 server.py --open
# python3 server.py --lan --port 8765
```

State files (`pulse.db`, `.pulse_config.json`, …) are created in the repo directory unless `PULSE_DATA_DIR` is set.

## Option 3 — Debian package (.deb)

Build on the target machine:

```bash
./deploy/build-deb.sh
sudo apt install ./build/deb/cosmic-pulse_0.1.0_all.deb
systemctl --user enable --now cosmic-pulse
cosmic-pulse --open
```

Read-only files go under `/usr/lib/cosmic-pulse/`. Writable state is **`~/.local/share/cosmic-pulse`**.

## systemd user service

This is the supported always-on mode. The unit:

- does **not** wait on `network-online` (Pulse is localhost)
- restarts on crash (`Restart=on-failure`)
- stops in ≤20s and reaps the sample-worker child (`KillMode=mixed` + SIGTERM handler)

```bash
systemctl --user status cosmic-pulse
journalctl --user -u cosmic-pulse -f
systemctl --user restart cosmic-pulse
```

Starts at login. To start at boot without a login:

```bash
loginctl enable-linger "$USER"
```

LAN bind (no auth) via a drop-in, not a rebuild:

```bash
systemctl --user edit cosmic-pulse
# [Service]
# Environment=PULSE_LAN=1
```

## CLI

```
cosmic-pulse            # foreground if the service is not running
cosmic-pulse --open     # start (or reuse) and open a browser
cosmic-pulse --lan      # bind 0.0.0.0 — trusted LAN only
cosmic-pulse --port 9090
cosmic-pulse --help
```

## Uninstall

**Install script:**

```bash
./install.sh --uninstall          # keep DB
./install.sh --purge              # also delete history
```

**Deb:**

```bash
systemctl --user disable --now cosmic-pulse
sudo apt remove cosmic-pulse
rm -rf ~/.local/share/cosmic-pulse   # optional — your DB/history
```

## Troubleshooting

| Problem | Check |
|---------|--------|
| `cosmic-pulse: command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| Service fails immediately | `journalctl --user -u cosmic-pulse -n 40` |
| Port already in use | another Pulse; `cosmic-pulse --open` reuses it |
| Missing GPU sensors | AMD sysfs under `/sys/class/drm/`; NVIDIA needs `nvidia-smi` |
| Empty Guidance | Wait a few sampler ticks; run **Scan** on the Guidance tab |
| Service starts but UI is dead after `systemctl stop` | Upgrade — 0.1 reaps the sample worker on SIGTERM |

See [ARCHITECTURE.md](ARCHITECTURE.md) for data directories.
