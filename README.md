# Pulse

**A second-monitor performance coach for Linux gaming.**

Pulse is a local web dashboard that helps you understand *why* a game stutters — not just CPU/GPU graphs. It ties together hardware context, bandwidth pressure, kernel stall signals, and actionable fix scripts. Built for [Pop!_OS](https://pop.system76.com/) / COSMIC, tested on an AMD Ryzen + RX 7900 XTX rig.

![Pulse dashboard](docs/screenshots/dashboard.png)

> **Status:** Pre-release — polishing for code review before publishing to GitHub/GitLab.

## What it does

- **Live overview** — CPU, RAM, GPU, VRAM, temps, bandwidth, and per-core load with smooth meters
- **Hardware league** — session index and tier comparison vs reference builds
- **Stutter proxy** — hitch score from page faults, PSI, swap, and I/O (frametime companion, not replacement)
- **Tuning insights** — copy-paste commands and downloadable `.sh` fix scripts per issue
- **Troubleshooting scanner** — journal, Steam logs, Vulkan, missing libraries
- **Game-aware** — Cities: Skylines II and CS2 process trees (extensible registry in `games.py`)

## Requirements

- Linux with `/proc`, `/sys`, and optional `lm-sensors` (`sensors`)
- Python **3.10+**
- [`psutil`](https://pypi.org/project/psutil/) (only pip dependency)
- AMD GPU metrics work best with amdgpu sysfs (`card1` discrete GPU assumed — see `server.py`)
- Optional: `dmidecode`, `smartctl`, `corectrl`, `nvtop` (listed in the tools panel)

## Quick start

```bash
git clone <repo-url> pulse   # or copy the project directory
cd pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

Open **http://localhost:8765** on a second monitor while gaming.

## Run as a service (optional)

```bash
# Edit paths: replace USER with your username
cp deploy/pulse.service ~/.config/systemd/user/pulse.service
$EDITOR ~/.config/systemd/user/pulse.service

systemctl --user daemon-reload
systemctl --user enable --now pulse
```

## Project layout

| Path | Role |
|------|------|
| `server.py` | HTTP server, 1 Hz sampler, metrics API |
| `index.html` | Dashboard UI (single-file HTML/CSS/JS + Chart.js CDN) |
| `benchmarks.py` | Hardware tier tables and league comparison |
| `stutter.py` | Hitch / stutter proxy scoring |
| `tuning_actions.py` | Insight generation and recommended actions |
| `fix_scripts.py` | Per-issue bash fix script templates |
| `diagnostics.py` | System troubleshooting scanner |
| `games.py` | Steam game registry and process detection |
| `store.py` | SQLite history, retention, correlation APIs |
| `probe_memory.py` | RAM speed probe (optional, may need sudo) |

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard |
| `GET /api/metrics` | Latest sample + rolling history + static rig info |
| `GET /api/diagnostics` | Troubleshooting scan results |
| `GET /api/store/stats` | SQLite retention stats |

## Code review

If you're reviewing this project (thanks!), start with **[docs/REVIEW.md](docs/REVIEW.md)** — architecture notes, security considerations, and suggested review focus areas.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for git workflow and [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

[MIT](LICENSE)