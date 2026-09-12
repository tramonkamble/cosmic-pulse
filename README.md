# Cosmic Pulse

**A second-monitor performance coach for Linux gaming.**

A local dashboard for *why* a game stutters — hardware context, kernel stall signals (PSI, page faults, swap), and Guidance you can act on. Built for [Pop!_OS](https://pop.system76.com/) / COSMIC; works on other Linux distros with Python 3.11+.

If you watched a Windows box with **MSI Afterburner** or **AMD Software: Adrenalin**, this is that world on a second monitor — not an overlay or overclocking suite.

![Cosmic Pulse dashboard](docs/screenshots/dashboard.png)

> **Status:** v0.2.2 (0.x prerelease) — community project, **not** an official System76 app. Issues and PRs welcome.

## If you came from Windows

Not a port of Afterburner, Adrenalin/Crimson, or the NVIDIA overlay. Same neighborhood, different job.

| On Windows | On Linux, Pulse is… |
|------------|---------------------|
| **MSI Afterburner** + RTSS | Live clocks, load, thermals, and hitch signals on a **second screen**. No OSD, no OC/fans. |
| **AMD Adrenalin** (older: Crimson) | The metrics page, a hardware class score, and “what to do next.” Tuning stays in CoreCtrl / LACT. |
| **NVIDIA App** / FrameView | Session recap and `nvidia-smi` meters. Overlay stays MangoHud / Steam. |
| **CapFrameX** / PresentMon | Hitch **proxy** from kernel stalls. Real frametime still wants MangoHud. |
| **HWiNFO** | Live lab plus history on this machine. |

[MangoHud](https://github.com/flightlessmango/MangoHud) is the overlay. CoreCtrl, LACT, or `nvidia-settings` are the tuners. Pulse sits on the other monitor: **what is the box doing, is this session hitching, is this PC in the right league, and what should I change.**

## What you get

- **Live lab** — Snapshot, Pulse Index, and Stutter (1 / 5 / 10 / 60 min)
- **Stutter estimate** — hitch score from PSI, faults, swap, and disk (not frametime)
- **Pulse Index** — this build vs published 1440p GPU / 1080p CPU relatives
- **Game performance** — Steam title, last-session rating, Smooth % / GPU / game CPU
- **Guidance** — ranked issues, copy-paste steps, optional user-owned fixes
- **Local history** — samples and settings stay on this machine (no account, no cloud)

Companion, not a replacement for MangoHud or in-game frametime tools. The stutter number is a kernel-signal **proxy**. AMD meters are the densest; NVIDIA needs `nvidia-smi`.

## Quick start (Pop!_OS / Ubuntu)

```bash
sudo apt install python3-psutil python3-yaml
git clone https://github.com/tramonkamble/cosmic-pulse.git
cd cosmic-pulse
chmod +x install.sh
./install.sh --service
```

Open **http://127.0.0.1:8765**, or `cosmic-pulse --open`. Put `~/.local/bin` on your `PATH`. `.deb`, Fedora/Arch, flags: [docs/INSTALL.md](docs/INSTALL.md).

Needs Linux, Python **3.11+**, and `psutil` / `PyYAML`. Steam and a second monitor are the useful extras.

Binds to **localhost**. `cosmic-pulse --lan` is for a trusted home network only (no login). Fixes never run `sudo` for you. [SECURITY.md](SECURITY.md).

Data lives in the install dir (`~/.local/share/cosmic-pulse`): `pulse.db`, config. Uninstall keeps it; `./install.sh --purge` deletes it.

| Problem | Try |
|---------|-----|
| `cosmic-pulse: command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| Blank / “Connecting…” | `journalctl --user -u cosmic-pulse -n 30` |
| No GPU stats | AMD: `/sys/class/drm/`. NVIDIA: `nvidia-smi` on `PATH`? |

**GPL-3.0-only** — [LICENSE](LICENSE). PRs: [CONTRIBUTING.md](CONTRIBUTING.md). Releases: [CHANGELOG.md](CHANGELOG.md).
