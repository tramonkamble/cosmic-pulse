# Cosmic Pulse

**A second-monitor performance coach for Linux gaming.**

Cosmic Pulse is a local web dashboard that helps you understand *why* a game stutters — not just CPU/GPU graphs. It ties together hardware context, bandwidth pressure, kernel stall signals, and actionable fix scripts. Built for [Pop!_OS](https://pop.system76.com/) / COSMIC, tested on an AMD Ryzen + RX 7900 XTX rig.

![Cosmic Pulse dashboard](docs/screenshots/dashboard.png)

> **Status:** v0.1 — initial public release. Feedback welcome via Issues.

## What it does

- **Live overview** — CPU, RAM, GPU, VRAM, temps, bandwidth, and per-core load with smooth meters
- **Hardware league** — session index and tier comparison vs reference builds
- **Stutter proxy** — hitch score from page faults, PSI, swap, and I/O (frametime companion, not replacement)
- **Tuning insights** — copy-paste commands and downloadable `.sh` fix scripts per issue
- **Troubleshooting scanner** — journal, Steam logs, Vulkan, missing libraries
- **Game-aware** — Cities: Skylines II and CS2 process trees (extensible registry in `games.py`)

## Requirements

- Linux with `/proc`, `/sys`, and optional `lm-sensors` (`sensors`)
- Python **3.11+**
- pip: [`psutil`](https://pypi.org/project/psutil/), [`PyYAML`](https://pypi.org/project/PyYAML/) — or distro packages `python3-psutil`, `python3-yaml`
- AMD GPU metrics work best with amdgpu sysfs (`card1` discrete GPU assumed — see `server.py`)
- Optional: `dmidecode`, `smartctl`, `corectrl`, `nvtop` (listed in the tools panel)

## Install

**Easiest** — install script + optional background service:

```bash
git clone <repo-url> cosmic-pulse
cd cosmic-pulse
chmod +x install.sh
./install.sh --service
```

Opens **http://localhost:8765**. Wrapper: `cosmic-pulse`. Full options: **[docs/INSTALL.md](docs/INSTALL.md)**.

**Debian / Pop!_OS .deb** (optional):

```bash
./deploy/build-deb.sh
sudo apt install ./build/deb/cosmic-pulse_0.1.0_all.deb
systemctl --user enable --now cosmic-pulse
```

**Manual / hacking on the code:**

```bash
git clone <repo-url> cosmic-pulse
cd cosmic-pulse
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

### Configuration (optional)

On first run, Pulse creates local state beside the app (not committed to git):

```bash
cp .pulse_config.example.json .pulse_config.json   # optional; defaults work without this
```

Edit retention days or mark insights fixed/ignored — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Project layout

| Path | Role |
|------|------|
| `server.py` | HTTP server, 1 Hz sampler, metrics API |
| `index.html` | Dashboard UI (single-file HTML/CSS/JS + Chart.js CDN) |
| `benchmarks.py` | Hardware tier tables and league comparison |
| `stutter.py` | Hitch / stutter proxy scoring |
| `tuning_actions.py` | Insight generation and recommended actions |
| `rule_packs.py` | YAML rule pack loader |
| `rules/builtin/` | Default insight rules (GPU, Steam, resolutions, …) |
| `issue_aggregate.py` | Guidance priority, per-game issues, stable sort |
| `guidance_auto.py` | Auto-resolve and clear-after-fix timers |
| `fix_scripts.py` | Per-issue bash fix script templates |
| `apply_fix.py` | Safe one-click fixes (user-writable config only) |
| `diagnostics.py` | System troubleshooting scanner |
| `games.py` | Steam game detection, Proton/Wayland helpers |
| `store.py` | SQLite history, retention, correlation APIs |
| `probe_memory.py` | RAM speed probe (optional, may need sudo) |
| `install.sh` | User-local installer (venv + optional systemd) |
| `deploy/build-deb.sh` | Build a `.deb` for apt |
| `docs/INSTALL.md` | Install script, .deb, systemd, uninstall |
| `docs/ARCHITECTURE.md` | Data flow, Guidance contracts, config files |

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard |
| `GET /api/metrics` | Latest sample + rolling history + static rig info |
| `GET /api/diagnostics` | Troubleshooting scan results |
| `GET /api/store/stats` | SQLite retention stats |

## Code review

Start with **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for data flow and module map. Reviewers: **[docs/REVIEW.md](docs/REVIEW.md)** covers security and suggested focus areas.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for git workflow and [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

**GPL-3.0-only** — aligned with [System76 / Pop!_OS application licensing](https://github.com/pop-os/pop/blob/master/LICENSING.md). See [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md).