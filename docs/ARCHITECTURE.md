# Architecture

Cosmic Pulse is a **local-only** performance coach: a Python sampler at 1 Hz and a single-page dashboard. This document explains how data flows and where the non-obvious UI/backend contracts live.

For security review notes, see [REVIEW.md](REVIEW.md).

## Data flow

```
collect_metrics()  [server.py, sampler thread]
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
| `server.py` | HTTP handler, sampler loop, metric assembly |
| `tuning_actions.py` | Evaluate YAML rules → hint dicts |
| `rule_packs.py` | Load `rules/builtin/…` packs |
| `issue_aggregate.py` | Priority scoring, per-game grouping, stable sort |
| `guidance_auto.py` | Auto-resolve timers, clear-after-fix grace |
| `games.py` | Steam AppID detection, Proton/Wayland helpers, game linger |
| `stutter.py` | Hitch proxy; `effective_disk_io_wait()` dampens zram PSI |
| `diagnostics.py` | On-demand log/system scan (cached ~90s) |
| `fix_scripts.py` | Bash templates; loaded lazily via `/api/fix-script` |
| `apply_fix.py` | Safe user-writable fixes only (no sudo/kill) |
| `pulse_config.py` | `.pulse_config.json` — retention, suppressed/resolved insights |
| `store.py` | SQLite history (`pulse.db`, gitignored) |

### Guidance history (`update_tuning_history`)

Each sampler tick:

1. Merge **active** hints (from rules) into `_tuning_history` by `insight_id`.
2. Set `condition_live` from whether the id appears in this tick's active set.
3. Re-open **state-verified** insights (e.g. Proton Wayland fix) when the condition returns after "Mark fixed".
4. Sort with `guidance_sort_key()` — severity, priority, `first_seen` — **not** live-first (avoids server-side reorder flicker).

Persisted to `.tuning_log.json` (debounced, gitignored).

### Rule packs

`rules/builtin/pulse-default/*.yaml` define insights. Game overrides and legacy AppIDs live in `pack.yaml`. Packs are data, not code — extend without editing Python when possible.

## Frontend (`index.html`)

~7.9k lines: CSS, markup, and JS in one file. Chart.js from CDN.

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

## Local configuration (not in git)

| File | Purpose |
|------|---------|
| `.pulse_config.json` | Retention, suppressed/resolved insights — copy from `.pulse_config.example.json` |
| `.tuning_log.json` | Guidance history cache |
| `.memory_cache.json` | RAM probe cache |
| `pulse.db` | SQLite samples |

## Tests

```bash
ruff check . --fix && ruff format .
python3 tests/test_*.py
```

Smoke and domain tests live under `tests/`. No pytest required for a quick local run.

## Related docs

- [REVIEW.md](REVIEW.md) — reviewer focus areas
- [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md) — release steps
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — git workflow