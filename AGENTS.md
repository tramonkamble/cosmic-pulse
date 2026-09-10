# Cosmic Pulse — notes for coding agents

This is **Cosmic Pulse**, a local Python dashboard for Linux gaming performance.
There is **no** `app.py`, Flask, or Django.

Use this file if you are Claude, Gemini, Codex, Cursor, Grok, or any other assistant
working in this repo. Keep diffs small. Run tests. Do not rewrite the dashboard from scratch.

## Layout

| What | Path |
|------|------|
| App package | `cosmic_pulse/` |
| Launcher | `server.py` (`python3 server.py` or `python3 -m cosmic_pulse`) |
| HTTP + sampler | `cosmic_pulse/server.py` |
| Dashboard UI | `index.html` + `assets/dashboard.css` + `assets/dashboard-theme.js` + `assets/dashboard-charts.js` + `assets/dashboard.js` |
| Hitch / stutter proxy | `cosmic_pulse/stutter.py` |
| SQLite history | `cosmic_pulse/store.py` |
| Steam / Proton | `cosmic_pulse/games.py`, `game_performance.py` |
| GPU sysfs / NVIDIA | `cosmic_pulse/gpu_metrics.py`, `gpu_thermal.py`, `hardware_probe.py` |
| Guidance rules | `cosmic_pulse/rule_packs.py`, `rules/builtin/` — authoring: [docs/RULES.md](docs/RULES.md) |
| Config / data dirs | `cosmic_pulse/pulse_config.py`, `paths.py` |
| Tests | `tests/harness.py` plus `tests/test_*.py` |

Run locally:

```bash
python3 server.py          # http://127.0.0.1:8765
python3 tests/harness.py   # product smoke (spawns :18765, no pytest required)
```

`PULSE_TEST_EXISTING=1 python3 tests/harness.py` hits an already-running Pulse.

## Product

- **Local-only.** Default bind is `127.0.0.1`. `--lan` / `PULSE_LAN=1` has **no auth** — trusted LAN only.
- Companion for a second monitor. Not a MangoHud or frametime replacement.
- Stutter number is a **kernel-signal proxy** (PSI, faults, swap, disk), not in-game FPS.
- Builtin Guidance is a **small scaffold** (`pulse-core` + `popos-core`). Richer tips belong in community packs under `~/.config/pulse/rules/`. How to write packs: [docs/RULES.md](docs/RULES.md). Annotated copy-this pack: `rules/examples/hello-swappiness/` (not loaded automatically).
- AMD sysfs is the dense GPU path; NVIDIA uses `nvidia-smi` when present. Do not fake AMD DRM nodes.

Live lab tabs (keep them the same height): **Snapshot**, **Pulse Index**, **Stutter**.

## Working rules

1. Prefer small iterative changes. Match surrounding style.
2. Do not commit runtime state: `pulse.db*`, `.pulse_config.json`, `.tuning_log.json`, logs.
3. After Python edits, restart `server.py` (or `systemctl --user restart cosmic-pulse`).
4. After `index.html` / `assets/dashboard.css` / `assets/dashboard*.js` changes, hard-refresh the dashboard. If you touch Snapshot vitals, also open Pulse Index and Stutter — they share lab height. Keep the three JS files in that script order (theme, charts, app).
5. Do not add cloud APIs, accounts, or telemetry.
6. Do not vendor extra JS CDNs; Chart.js is already in `assets/vendor/`.
7. SPDX on new files: `GPL-3.0-only`.

## Investigation order (bugs / perf)

1. `ls *.py tests/`
2. `cosmic_pulse/server.py` — handler map and sampler
3. `cosmic_pulse/store.py` / `stutter.py` for hot paths
4. `python3 tests/harness.py` (or a single `tests/test_*.py`)
5. Cite `file:line` in findings

## Out of scope unless asked

- Mass rewrite of the dashboard (`index.html` / `assets/dashboard.css` / `assets/dashboard.js`)
- Deleting `pulse.db`
- Expanding builtin rule packs past the two scaffolds
- Packaging Cosmic Pulse as a rewrite in Rust / libcosmic
