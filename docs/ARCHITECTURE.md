# Architecture

Cosmic Pulse is a **local-only** performance coach: a Python sampler at 1 Hz and a single-page dashboard. This document explains how data flows and where the non-obvious UI/backend contracts live.

For security review notes, see [REVIEW.md](REVIEW.md).

## Data flow

```
collect_metrics()  [cosmic_pulse/server.py, sample worker]
    ├── hardware_probe / gpu_metrics / stutter / games / diagnostics
    ├── build_tuning_hints()     → active rule matches this tick
    ├── update_tuning_history()  → merge into persistent history
    └── build_issue_views()      → overall + per-game lists for API

/api/metrics  →  tick() in index.html  →  render*() with diff keys
```

**Bootstrap:** first poll uses `?bootstrap=1` (static rig info + full chart history). Steady-state polls fetch one slim history point per second.

**Guidance payload:** `latest.tuning` is the merged history (outstanding + marked-fixed). `condition_live` flips each tick; it must not control whether an issue exists in the list.

## Backend modules

| Module | Role |
|--------|------|
| `cosmic_pulse/server.py` | HTTP handler, sampler loop, metric assembly |
| `cosmic_pulse/tuning_actions.py` | Evaluate YAML rules → hint dicts |
| `cosmic_pulse/rule_packs.py` | Load `rules/builtin/…` packs |
| `cosmic_pulse/issue_aggregate.py` | Priority scoring, per-game grouping, stable sort |
| `cosmic_pulse/guidance_auto.py` | Auto-resolve timers, clear-after-fix grace |
| `cosmic_pulse/games.py` | Steam AppID detection, Proton/Wayland helpers, game linger |
| `cosmic_pulse/stutter.py` | Hitch proxy; `effective_disk_io_wait()` dampens zram PSI |
| `cosmic_pulse/diagnostics.py` | On-demand log/system scan (cached ~90s) |
| `cosmic_pulse/apply_fix.py` | `requires_root` labels only (Pulse never executes) |
| `cosmic_pulse/pulse_config.py` | `.pulse_config.json` — retention, suppressed/resolved insights |
| `cosmic_pulse/store.py` | SQLite history (`pulse.db`, gitignored) |

### Guidance history (`update_tuning_history`)

Each sampler tick:

1. Merge **active** hints (from rules) into `_tuning_history` by `insight_id`.
2. Set `condition_live` from whether the id appears in this tick's active set.
3. Re-open **state-verified** insights (e.g. Proton Wayland fix) when the condition returns after "Mark fixed".
4. Sort with `guidance_sort_key()` — severity, priority, `first_seen` — **not** live-first (avoids server-side reorder flicker).

Persisted to `.tuning_log.json` (debounced, gitignored).

### Rule packs

`rules/builtin/pulse-core/` and `rules/builtin/popos-core/` define insights (five each). Packs are data, not code — extend without editing Python when possible. Per-title `game_overrides` belong in community packs, not builtin. Authoring: [RULES.md](RULES.md). Index: [../RULE_PACKS.md](../RULE_PACKS.md). Annotated example: `rules/examples/hello-swappiness/` (not loaded from builtin).

**Product intent (0.1+):** Pulse owns the **engine** that evaluates packs; it does **not** own a large encyclopedia of game-tuning advice.

**Builtin for 0.1:** two packs, **five insights each** — `pulse-core` (Linux / Steam / hitch proxy / GPU-busy FPS cap) and `popos-core` (Pop-only: HDR, RAPL udev, Proton libs, MangoHud, GPU hot). Everything richer is **community packs** (`~/.config/pulse/rules/`).

**Launchers:** 0.1 is Steam-first (including extra Steam libraries from `libraryfolders.vdf`). Heroic / Lutris / etc. are planned post-0.1 integrations (`launcher-heroic-etc`).

## Frontend

Markup in `index.html`, styles in `assets/dashboard.css`, client logic in `assets/dashboard.js`. Chart.js is vendored under `assets/vendor/` (served locally, no CDN).

### Poll loop (`tick()`)

Calls render helpers each second. Most use a **layout key** (structural fingerprint) to skip `innerHTML` rebuilds when only volatile fields changed (`condition_live`, `last_seen`, meter values).

### Guidance tab

**Outstanding vs live**

- **Outstanding** — user has not marked fixed or ignored; shown in the index.
- **Live** — rule matches *this* tick (`condition_live`); shown as a dot/badge only.

Previously the index gated on live-only, which made cards vanish for a tick while reading. The index now lists all outstanding hints; live status is patched in place.

**Key functions**

| Function | Purpose |
|----------|---------|
| `hintsLayoutKey()` | Stable fingerprint for index/detail structure |
| `patchGuidanceLiveState()` | Update live dots + detail badge without rebuild |
| `sortGuidanceHints()` | Severity → priority → `first_seen` (stable order) |
| `renderFixes()` | Build index groups; early-return + patch when layout unchanged |
| `renderGuidanceIndex()` | Filter chips + list; sticky selection when filtered out |
| `warningsForDisplay()` | Dashboard warnings with ~45s dwell after going non-live |

**Selection stickiness:** if the selected `insight_id` still exists in the full hint pool but is hidden by a filter, the detail panel stays pinned instead of jumping to the first row.

### Game card linger

When a Proton game's PID disappears during load, `primary_active_game_with_linger()` (server) holds the game row ~10s. Client shows "Loading" from `game_totals.lingering`.

## Install paths (`paths.py`)

| Location | Role |
|----------|------|
| `app_root()` | Code, `index.html`, `rules/` (read-only in `.deb`) |
| `data_dir()` | `pulse.db`, `.pulse_config.json`, tuning log, caches |

- **Git clone / `install.sh`:** both under the install directory (e.g. `~/.local/share/cosmic-pulse`).
- **`.deb` install:** code in `/usr/lib/cosmic-pulse`, state in `~/.local/share/cosmic-pulse`.
- Override: `PULSE_DATA_DIR=/path/to/state`.

See [INSTALL.md](INSTALL.md).

## Local configuration (not in git)

| File | Purpose |
|------|---------|
| `.pulse_config.json` | Retention, suppressed/resolved insights — copy from `.pulse_config.example.json` |
| `.tuning_log.json` | Guidance history cache |
| `.memory_cache.json` | RAM probe cache |
| `pulse.db` | SQLite samples |

All live under `data_dir()` (see above).

## Tests

```bash
ruff check . --fix && ruff format .
python3 tests/test_*.py
```

Smoke and domain tests live under `tests/`. No pytest required for a quick local run.

## Related docs

- [RULES.md](RULES.md) — how to write Guidance YAML packs
- [REVIEW.md](REVIEW.md) — reviewer focus areas
- [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md) — release steps
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — git workflow