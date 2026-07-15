# Cosmic Pulse

**A second-monitor performance coach for Linux gaming.**

Cosmic Pulse is a local web dashboard that helps you understand *why* a game stutters — not just CPU/GPU graphs. It ties together hardware context, bandwidth pressure, kernel stall signals (PSI, page faults, swap), and actionable fix scripts. Built for [Pop!_OS](https://pop.system76.com/) / COSMIC; works on other Linux distros with Python 3.11+.

![Cosmic Pulse dashboard](docs/screenshots/dashboard.png)

> **Status:** v0.1 — community project, not an official System76 app. Feedback welcome via [Issues](https://github.com/YOURUSER/cosmic-pulse/issues).

## Why Cosmic Pulse?

| Typical monitor | Cosmic Pulse |
|-----------------|--------------|
| Raw CPU/GPU % | **Stutter proxy** — hitch score from kernel stall signals |
| Static graphs | **Hardware league** — how this session compares to reference tiers |
| “Google the error” | **Guidance** — ranked issues, copy-paste steps, optional one-click fixes |
| Generic | **Game-aware** — detects running Steam titles, Proton/Wayland context |

Cosmic Pulse is a **companion** for a second monitor while gaming — not a replacement for MangoHud, COSMIC System Monitor, or in-game frametime tools.

## Quick start (Pop!_OS / Ubuntu)

```bash
# Dependencies (once)
sudo apt install python3-psutil python3-yaml

# Install
git clone https://github.com/YOURUSER/cosmic-pulse.git
cd cosmic-pulse
chmod +x install.sh
./install.sh --service
```

Open **http://localhost:8765** (or `http://<your-lan-ip>:8765` from a phone on the same network).

Ensure `~/.local/bin` is on your `PATH` so the `cosmic-pulse` command works.

## Features

- **Live overview** — CPU, RAM, GPU, VRAM, temps, bandwidth, per-core load, GPU engine strip (AMD)
- **Stutter estimate** — heuristic hitch score from page faults, PSI, swap, and disk I/O (not in-game frametime)
- **Pulse Index** — session load score vs hardware tier tables
- **Guidance** — outstanding issues with stable list order, live badges, fix scripts, and safe one-click applies
- **System scan** — journal, Steam logs, Vulkan, missing libraries (on-demand, cached ~90s)
- **Steam / Proton** — dynamic game detection, launch-option hints (e.g. Wayland → X11 for Proton)
- **COSMIC theme sync** — reads accent and surfaces from `~/.config/cosmic` when available
- **History** — optional SQLite retention for trends and correlations

## Requirements

| Required | Notes |
|----------|--------|
| Linux + `/proc`, `/sys` | Any modern distro |
| Python **3.11+** | `python3 --version` |
| `psutil`, `PyYAML` | `sudo apt install python3-psutil python3-yaml` or `pip install -r requirements.txt` |

| Recommended | Notes |
|-------------|--------|
| AMD discrete GPU | Best sysfs metrics; NVIDIA/multi-GPU still partial |
| `lm-sensors` | Extra temperature tiles (`sudo apt install lm-sensors`) |
| Steam | Game-aware Guidance and log scans |
| Second monitor or LAN device | Dashboard is meant to run beside your game |

Optional: `dmidecode`, `smartctl`, `corectrl`, `nvtop` — surfaced in the tools panel when present.

## Install options

| Method | Best for | Guide |
|--------|----------|--------|
| **`./install.sh --service`** | Most users | Below + [docs/INSTALL.md](docs/INSTALL.md) |
| **`.deb` package** | apt-based distros | [docs/INSTALL.md](docs/INSTALL.md) § Debian |
| **`python3 server.py`** | Development / hacking | Clone repo, run in tree |

### Install script flags

```bash
./install.sh --service          # background systemd user service
./install.sh --dir ~/.local/share/cosmic-pulse
./install.sh --port 8765        # set PULSE_PORT
./install.sh --system-python    # skip venv (use apt/pip packages)
./install.sh --uninstall        # remove install + service
```

Install location defaults to `~/.local/share/cosmic-pulse`. The `cosmic-pulse` wrapper is placed in `~/.local/bin`.

### Service commands

```bash
systemctl --user status cosmic-pulse
systemctl --user restart cosmic-pulse
journalctl --user -u cosmic-pulse -f
```

User services start at login. For start-at-boot without login: `loginctl enable-linger "$USER"`.

## Configuration

Local state is **per machine** — never committed to git:

| File | Purpose |
|------|---------|
| `pulse.db` | Sample history (SQLite) |
| `.pulse_config.json` | Retention, suppressed/resolved insights |
| `.tuning_log.json` | Guidance history cache |

Copy the template if you want an explicit config:

```bash
cp .pulse_config.example.json .pulse_config.json
```

**Environment variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `PULSE_PORT` | `8765` | HTTP port |
| `PULSE_DATA_DIR` | install dir or `~/.local/share/cosmic-pulse` | Writable state (`.deb` installs) |
| `STEAM_BASE` | auto-detect | Steam root if non-standard |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Security notice

Cosmic Pulse binds to **`0.0.0.0`** (all interfaces) so phones and second machines on your LAN can view the dashboard. There is **no authentication**. Use only on networks you trust. Do not expose port 8765 to the internet without a reverse proxy and auth.

One-click **Fix** actions are limited to safe, user-owned changes (e.g. open folders, Steam launch options). Root/sudo steps are scripts you run yourself.

## Known limitations (v0.1)

- Stutter score is a **kernel-signal proxy**, not real frametime.
- AMD discrete GPU is the happy path; NVIDIA-only rigs may have sparse GPU tiles.
- Chart.js loads from CDN on first visit (needs internet once).
- Some fix scripts reference machine-specific sensor labels — review before running.

See [docs/REVIEW.md](docs/REVIEW.md) for reviewer notes and future work.

## Troubleshooting

| Problem | Try |
|---------|-----|
| `cosmic-pulse: command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| Blank / “Connecting…” | `journalctl --user -u cosmic-pulse -n 30` |
| Install fails on venv | `sudo apt install python3-psutil python3-yaml` — script falls back to system Python |
| No GPU stats | Check `/sys/class/drm/` — see [docs/REVIEW.md](docs/REVIEW.md) |
| Guidance empty at first | Wait a few seconds; run **Scan** on the Guidance tab |

More: [docs/INSTALL.md](docs/INSTALL.md) § Troubleshooting.

## Project layout

| Path | Role |
|------|------|
| `server.py` | HTTP server, 1 Hz sampler, metrics API |
| `index.html` | Dashboard UI (single-file HTML/CSS/JS) |
| `tuning_actions.py` + `rules/builtin/` | YAML-driven Guidance rules |
| `stutter.py` | Hitch / stutter proxy |
| `games.py` | Steam detection, Proton/Wayland helpers |
| `diagnostics.py` | System troubleshooting scanner |
| `fix_scripts.py` + `apply_fix.py` | Bash templates and safe one-click fixes |
| `store.py` | SQLite history and correlations |
| `install.sh` | User-local installer |
| `deploy/build-deb.sh` | Build `.deb` for apt |

## API (selected)

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard |
| `GET /api/metrics` | Latest sample; `?bootstrap=1` for full history + static rig |
| `GET /api/diagnostics` | Troubleshooting scan (`?force=1` to bypass cache) |
| `GET /api/fix-script?insight_id=…` | Lazy-loaded bash fix script |
| `POST /api/apply-fix` | Safe one-click fix (whitelisted insights only) |
| `POST /api/store` | Retention, suppress/resolve insights |
| `GET /api/trends`, `/api/correlation` | Historical series |

Full data flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/INSTALL.md](docs/INSTALL.md) | Install script, `.deb`, systemd, uninstall |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Sampler loop, Guidance contracts, config paths |
| [docs/REVIEW.md](docs/REVIEW.md) | Security focus, review checklist |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow, lint, what not to commit |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

## Contributing

Pull requests welcome. Run `ruff check .` and `python3 tests/test_*.py` before submitting. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

**GPL-3.0-only** — aligned with [Pop!_OS application licensing](https://github.com/pop-os/pop/blob/master/LICENSING.md). See [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md).