# Code review guide

Thanks for reviewing Cosmic Pulse. This doc is written for a technical reviewer (e.g. a sibling or colleague) before the project is published publicly.

## What you're looking at

Cosmic Pulse is a **single-user, local-only** Python HTTP server that samples system metrics at 1 Hz and serves a single-page dashboard. There is no auth layer — it binds to `0.0.0.0:8765` so a phone or second machine on the LAN can view it. That is intentional for a second-monitor setup but worth scrutinizing.

**Stack:** Python 3 stdlib + `psutil` + one HTML file. Chart.js loaded from CDN. SQLite for optional history.

## How to run

```bash
cd pulse
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
# → http://localhost:8765
```

No build step. UI changes are in `index.html`; restart the server after Python edits.

## Architecture (5-minute map)

```
server.py (sampler thread + HTTP)
    ├── benchmarks.py    → hardware tiers, session index
    ├── stutter.py       → hitch proxy from PSI/faults/swap
    ├── tuning_actions.py→ insights + action commands
    ├── fix_scripts.py   → bash script strings embedded in hints
    ├── diagnostics.py   → journal/steam/vulkan scans
    ├── games.py         → Steam process detection
    └── store.py         → SQLite pulse.db (gitignored)

index.html
    └── fetch /api/metrics every 1s, render in-place (meters smoothed in JS)
```

Data flow: `collect_metrics()` → ring buffer `_history` → `/api/metrics` → UI. Tuning hints are rebuilt each tick from latest snapshot.

## Suggested review focus

### High priority

1. **Security / exposure** — `ThreadingHTTPServer(("0.0.0.0", PORT), …)` exposes metrics on all interfaces. Should this default to `127.0.0.1` with an opt-in LAN flag?
2. **Command injection** — `fix_scripts.py` and `tuning_actions.py` embed shell commands. Are any inputs insufficiently sanitized?
3. **Thread safety** — `_history` and caches updated under `_lock`; verify handler reads are safe.
4. **GPU path assumptions** — `GPU_DISCRETE = card1`, hardcoded amdgpu paths in fix scripts. Will break on NVIDIA-only or different DRM ordering.
5. **Game paths** — Cities II compatdata path is Proton-specific; CS2/Cities app IDs are in `games.py`.

### Medium priority

6. **`index.html` size** — ~2.6k lines monolith. Splitting JS/CSS is a future refactor, not blocking.
7. **Stutter proxy accuracy** — `stutter.py` is heuristic, not real frametime. Document limitations vs MangoHud.
8. **SQLite growth** — retention pruning in `store.py`; confirm bounds.
9. **Error handling** — broad `except` in sampler loop; intentional for resilience but may hide bugs.

### Low priority / polish

10. Typographic manufacturer badges, meter EMA smoothing, Cosmic theme tokens.
11. `backlog.json` is dev notes, not user-facing config.

## Key files to read first

| Order | File | Why |
|-------|------|-----|
| 1 | `server.py` — `collect_metrics`, `Handler`, `sampler` | Core loop |
| 2 | `tuning_actions.py` — `build_tuning_hints` | User-facing recommendations |
| 3 | `stutter.py` | Novel logic |
| 4 | `benchmarks.py` — `hardware_comparison` | Tier/league math |
| 5 | `index.html` — `tick()`, `renderVisualDashboard` | UI update strategy |

## Known limitations (not bugs)

- Stutter score is a **proxy** from kernel signals, not in-game frametime.
- AMD discrete GPU on `card1` is assumed; multi-GPU and NVIDIA need work.
- Some fix scripts reference `amdgpu-pci-0300` sensor label — machine-specific.
- Steam userdata path was removed; game detection uses process cmdline + compatdata paths.

## Giving feedback

Please note:

- **File:line** references when possible
- Severity: blocker / should-fix / nit / question
- Whether it's pre-publish or post-publish scope

Open issues, email, or inline comments on a PR all work once the remote exists.

## Pre-publish checklist

See [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md) for what remains before GitHub/GitLab.