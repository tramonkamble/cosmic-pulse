# Cosmic Pulse

**A second-monitor performance coach for Linux gaming.**

Cosmic Pulse is a local web dashboard that helps you understand *why* a game stutters — not just CPU/GPU graphs. It ties together hardware context, kernel stall signals (PSI, page faults, swap), and actionable Guidance steps. Built for [Pop!_OS](https://pop.system76.com/) / COSMIC; works on other Linux distros with Python 3.11+.

If you watched a Windows box with **MSI Afterburner** or **AMD Software: Adrenalin**, this is that same “keep an eye on the rig while I play” world — on a second monitor, not as an overlay or overclocking suite.

![Cosmic Pulse dashboard](docs/screenshots/dashboard.png)

> **Status:** v0.2.2 (0.x prerelease) — community project, **not** an official System76 app. Issues and PRs welcome.

## If you came from Windows

Pulse is not a port of Afterburner, and it is not AMD Crimson/Adrenalin or the NVIDIA overlay. It sits in that *monitoring-while-you-game* neighborhood.

| On Windows you probably used… | For… | On Linux, Pulse is… |
|-------------------------------|------|---------------------|
| **MSI Afterburner** + RivaTuner (RTSS) | On-screen graphs, OSD, optional OC/fans | Live clocks, load, thermals, and hitch signals on a **second screen**. No OSD, no clock/fan sliders. |
| **AMD Software: Adrenalin** (older name: Crimson) | Driver overlay, metrics, tuning | The metrics *page* — plus a hardware class score and “what to do next.” Driver tuning stays in CoreCtrl / LACT / `amdgpu`. |
| **NVIDIA App** overlay / FrameView | FPS overlay, frame capture | Session recap and GPU meters via `nvidia-smi`. Overlay stays MangoHud / Steam. |
| **CapFrameX** / PresentMon | 1% lows, frametime traces | A **hitch proxy** from kernel stalls (PSI, faults, swap, disk). Real frametime still wants MangoHud. |
| **HWiNFO** | Sensor wall and logging | Live lab (clocks / thermals / power / pressure) and optional history on this machine. |

Leave the in-game overlay to [MangoHud](https://github.com/flightlessmango/MangoHud). Leave voltage/clock/fan curves to CoreCtrl, LACT, or `nvidia-settings`. Pulse is the dashboard you park on the other monitor: **what is the box doing, is this session hitching, is this PC in the right league, and what should I change.**

## Why Cosmic Pulse?

| Typical monitor | Cosmic Pulse |
|-----------------|--------------|
| Raw CPU/GPU % | **Stutter proxy** — hitch score from kernel stall signals |
| Static graphs | **Hardware league** — how this PC compares to published CPU/GPU relatives |
| “Google the error” | **Guidance** — ranked issues, copy-paste steps, optional one-click fixes |
| Generic | **Game-aware** — detects running Steam titles, Proton/Wayland context |

It is a **companion**, not a replacement for MangoHud, COSMIC System Monitor, or in-game frametime tools.

## What you get

- **Live lab** — Snapshot (load, clocks, thermals, power), Pulse Index, and Stutter, with 1 / 5 / 10 / 60 minute views
- **Stutter estimate** — hitch score from page faults, PSI, swap, and disk I/O (not in-game frametime)
- **Pulse Index** — how this build ranks vs published 1440p GPU / 1080p CPU relatives, plus live session load
- **Game performance** — Steam title detection, last-session rating, Smooth % / GPU / game CPU trend
- **Guidance** — ranked issues with copy-paste steps and optional one-click user-owned fixes
- **Host identity** — desktop (COSMIC, KDE, GNOME, XFCE, …) and GPU stack (Mesa / NVIDIA)
- **COSMIC theme sync** — accent and surfaces from `~/.config/cosmic` when present
- **History** — samples kept on this machine so you can browse past sessions

## Quick start (Pop!_OS / Ubuntu)

```bash
sudo apt install python3-psutil python3-yaml
git clone https://github.com/tramonkamble/cosmic-pulse.git
cd cosmic-pulse
chmod +x install.sh
./install.sh --service
```

Open **http://127.0.0.1:8765**, or run `cosmic-pulse --open`. For a second machine on the LAN: `cosmic-pulse --lan` (trusted home network only — there is no login).

Put `~/.local/bin` on your `PATH` so the `cosmic-pulse` command works. Full options, `.deb`, Fedora/Arch: [docs/INSTALL.md](docs/INSTALL.md).

```bash
systemctl --user status cosmic-pulse
systemctl --user restart cosmic-pulse
```

## Requirements

| Required | Notes |
|----------|--------|
| Linux + `/proc`, `/sys` | Any modern distro |
| Python **3.11+** | `python3 --version` |
| `psutil`, `PyYAML` | `sudo apt install python3-psutil python3-yaml` |

| Recommended | Notes |
|-------------|--------|
| AMD discrete GPU | Dense GPU meters (busy, VRAM, PPT, fan) |
| NVIDIA | `nvidia-smi` meters when the proprietary driver is present |
| Steam | Game-aware Guidance and session recap |
| Second monitor | Dashboard is meant to sit beside the game |

Optional: `dmidecode` (exact RAM kit), `smartctl`, CoreCtrl, nvtop — Pulse lists them when they are installed.

## On this machine

Pulse does not use an account or the cloud. History and settings stay local:

| File | Purpose |
|------|---------|
| `pulse.db` | Sample and session history |
| `.pulse_config.json` | Retention, theme, suppressed tips |
| `.tuning_log.json` | Guidance history |

Default location is the install directory (`~/.local/share/cosmic-pulse` for the script and the `.deb`). Uninstall keeps that data; `./install.sh --purge` deletes it.

## Privacy

Binds to **`127.0.0.1`** by default. `--lan` / `PULSE_LAN=1` listens on the LAN **with no authentication** — second monitor or phone on a network you trust, not the internet. One-click **Fix** actions only touch user-owned things (folders, Steam launch options). Root steps are commands you run yourself. Details: [SECURITY.md](SECURITY.md).

## Limitations

- Stutter score is a **kernel-signal proxy**, not MangoHud frametime.
- AMD GPUs have the richest meters; NVIDIA uses `nvidia-smi` when it is installed.
- Some Guidance commands are machine-specific — read them before running.

## Troubleshooting

| Problem | Try |
|---------|-----|
| `cosmic-pulse: command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| Blank / “Connecting…” | `journalctl --user -u cosmic-pulse -n 30` |
| Install fails on venv | `sudo apt install python3-psutil python3-yaml` |
| No GPU stats | AMD: `/sys/class/drm/`. NVIDIA: is `nvidia-smi` on `PATH`? |
| Guidance empty at first | Wait a few seconds; run **Scan** on the Guidance tab |

More: [docs/INSTALL.md](docs/INSTALL.md).

## License

**GPL-3.0-only** — see [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md).

Issues and pull requests welcome. How we take changes: [CONTRIBUTING.md](CONTRIBUTING.md). Release notes: [CHANGELOG.md](CHANGELOG.md).
