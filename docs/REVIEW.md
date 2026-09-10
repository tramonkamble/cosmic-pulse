# Code review guide

Thanks for reviewing Cosmic Pulse. Start with [AGENTS.md](../AGENTS.md) and [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## What you're looking at

Cosmic Pulse is a **single-user, local-only** Python HTTP server that samples system metrics at 1 Hz and serves a single-page dashboard. There is no auth layer. It binds to `127.0.0.1` by default; `--lan` / `PULSE_LAN=1` listens on all interfaces for a second monitor.

**Stack:** Python 3 stdlib + `psutil` + `PyYAML` + `cosmic_pulse/` package + one HTML file. Chart.js is vendored in `assets/vendor/` (no CDN). SQLite for optional history.

## How to run

```bash
cd cosmic-pulse
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
# → http://127.0.0.1:8765
python3 tests/harness.py
```

No build step. UI changes are in `index.html`; restart the server after Python edits.

## Architecture (5-minute map)

```
server.py (sampler thread + HTTP)
    ├── benchmarks.py    → hardware tiers, session index
    ├── stutter.py       → hitch proxy from PSI/faults/swap
    ├── tuning_actions.py→ insights + action commands
    ├── apply_fix.py    → requires_root labels only (no command execution)
    ├── diagnostics.py   → journal/steam/vulkan scans
    ├── games.py         → Steam process detection
    └── store.py         → SQLite pulse.db (gitignored)

index.html
    └── fetch /api/metrics every 1s, render in-place (meters smoothed in JS)

issue_aggregate.py + guidance_auto.py
    └── persistent Guidance history, stable sort, auto-resolve
```

Data flow: `collect_metrics()` → ring buffer `_history` → `/api/metrics` → UI. Tuning hints are rebuilt each tick; history merges via `update_tuning_history()`.

**Deeper dive:** [ARCHITECTURE.md](ARCHITECTURE.md) — Guidance outstanding vs live, layout-key diffing, local config files.

## Suggested review focus

### High priority

1. **Security / exposure** — default is `127.0.0.1`; `--lan` still has no auth. Confirm that is acceptable for a trusted home LAN.
2. **Command injection** — Guidance `actions` embed shell command *suggestions*. Are any template inputs insufficiently sanitized?
3. **Thread safety** — `_history` and caches updated under `_lock`; verify handler reads are safe.
4. **GPU path assumptions** — `GPU_DISCRETE = card1`, hardcoded amdgpu paths in some step commands. Will break on NVIDIA-only or different DRM ordering.
5. **Game paths** — Proton compatdata is Steam-layout specific; AppIDs come from live processes and manifests, not hardcoded titles.

### Medium priority

6. **`index.html` size** — ~7.9k lines monolith. Splitting JS/CSS is a future refactor, not blocking.
7. **Stutter proxy accuracy** — `cosmic_pulse/stutter.py` is heuristic, not real frametime. Document limitations vs MangoHud.
8. **SQLite growth** — retention pruning in `cosmic_pulse/store.py`; confirm bounds.
9. **Error handling** — broad `except` in sampler loop; intentional for resilience but may hide bugs.

### Low priority / polish

10. Typographic manufacturer badges, meter EMA smoothing, Cosmic theme tokens.
11. `backlog.json` is dev notes, not user-facing config.

## Key files to read first

| Order | File | Why |
|-------|------|-----|
| 1 | `cosmic_pulse/server.py` — `collect_metrics`, `Handler` | Core loop |
| 2 | `cosmic_pulse/tuning_actions.py` — `build_tuning_hints` | User-facing recommendations |
| 3 | `cosmic_pulse/stutter.py` | Novel logic |
| 4 | `cosmic_pulse/benchmarks.py` — `hardware_comparison` | Tier/league math |
| 5 | `index.html` — `tick()`, `renderFixes`, `hintsLayoutKey` | UI update + Guidance stability |
| 6 | `cosmic_pulse/issue_aggregate.py` — `build_issue_views`, `guidance_sort_key` | Guidance ordering |

## Known limitations (not bugs)

- Stutter score is a **proxy** from kernel signals, not in-game frametime.
- AMD discrete GPU on `card1` is assumed; multi-GPU and NVIDIA need work.
- Some Guidance commands reference `amdgpu-pci-0300` sensor label — machine-specific.
- Steam userdata path was removed; game detection uses process cmdline + compatdata paths.

## Giving feedback

Please note:

- **File:line** references when possible
- Severity: blocker / should-fix / nit / question
- Whether it's pre-publish or post-publish scope

Open issues, email, or inline comments on a PR all work once the remote exists.

## Pre-publish checklist

See [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md) for what remains before GitHub/GitLab.