# Changelog

All notable changes to **Cosmic Pulse** (perf-dashboard) are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates use the machine local timezone (EDT unless noted).

## [Unreleased]

### Changed
- **Renamed to Cosmic Pulse** — UI title, header, docs, fix scripts, and service messages.

### Added
- **COSMIC theme sync** — reads `~/.config/cosmic` accent, palette, surfaces, radii, and frost setting; applies live CSS variables and chart colors.

### Changed
- **Visual polish** — Inter type, Cosmic surface hierarchy, accent-driven tabs/buttons, frosted mode when enabled in Cosmic settings.

### Fixed
- **UI stability** — fix cards no longer rebuild every second (`last_seen` excluded from struct key); expanded script/steps panels stay open with scroll position preserved; scroll-wheel no longer collapses expansions or scrolls the page through nested script panes.

### Changed
- **License** — MIT → **GPL-3.0-only** (System76 / Pop!_OS preferred license for applications); `LICENSING.md` and SPDX headers on source files.

### Added
- **Publish prep** — `README.md`, `requirements.txt`, dashboard screenshot, `docs/REVIEW.md` (code review guide), `docs/PUBLISH_CHECKLIST.md`.

### Changed
- **Portable paths** — `pulse_root` in static API; probe script paths no longer hardcode `/home/tkep`.

### Changed (earlier this week)
- **Git workflow** — `CONTRIBUTING.md` documents Conventional Commits, changelog sync, and local `main` practices.

## [2026-06-30] — local git

### Added
- **Local git repository** — `git init` in project root; `.gitignore` for DB, caches, and `__pycache__`; `deploy/pulse.service` template for future GitHub/GitLab installs.
- `CHANGELOG.md` — project change history.

## [2026-06-30] — dashboard

### Added
- **Meter smoothing** — CSS transitions on all meter fills; in-place DOM updates instead of rebuilding bars each tick; exponential moving average (`METER_SMOOTH_ALPHA = 0.22`) so values glide between 1s samples.
- **CoreCtrl integration** — listed in profiling tools panel; detected via `tools.corectrl` in static API; GPU thermal/warm recommendations offer **Open CoreCtrl** when installed; fix scripts launch CoreCtrl instead of suggesting `apt install`.
- **Hardware rig strip** — chassis, CPU, GPU, and RAM identity exposed in static API (`rig`) and shown in the dashboard header strip.
- **RX 7900 XTX tier** — separate benchmark entry (score 85, 960 GB/s VRAM); `detect_gpu_spec()` via lspci for XFX Speedster MERC 310.

### Changed
- **Layout stability** — fixed-height scroll regions for warnings, diagnostics, and sensor strip; toolbar min-heights; scroll position preserved across re-renders; empty states live inside scroll areas.
- **Dashboard grid** — summary 4×2 “tetris” layout (tall Health + League on sides); live overview uses explicit grid areas for util/temp/bw/league, spark/cores/glance, and stutter.
- **Manufacturer marks** — typographic badges (AMD, XFX, G.SKILL, S76, etc.) instead of SVG logo sprites.
- **Power & cooling panel** — glance grid with icon boxes and accent bars.
- **`_match_tier` fix** — XT no longer matches inside XTX alias strings.
- **7900 XTX alias** — `"7900 xtx"` maps to XTX tier, not XT.

### Fixed
- **XTX detection** — tables and hardware comparison no longer treat RX 7900 XTX as XT (wrong VRAM bandwidth and tier score).

## [2026-06-29] and earlier

Major milestones from project backlog (pre-changelog tracking).

### Added
- **Pulse** rename from perf-dashboard; Cosmic-style UI (frosted panels, Pop orange accent).
- **Summary rollups** with drill-down jumps to bandwidth, insights, league, and cores.
- **Hardware league** — session index, tier ranks, live vs enthusiast comparison table.
- **Bandwidth drill-down** — GPU VRAM and system DRAM estimates with busy % and PSI.
- **Stutter proxy** — hitch score from faults, PSI, swap, and I/O; sparkline hitch events; 1% low ms estimate; per-component breakdown and fix scripts.
- **Tuning insights** — persistent hints with timestamps; per-issue copy-paste commands and downloadable `.sh` fix scripts.
- **Per-game issues** — issues grouped by game; cross-game fixes ranked higher in the overall list.
- **Troubleshooting scanner** — boot journal, systemd failures, missing libraries, Steam logs, game exits, Vulkan, apt updates.
- **Profiling tools panel** — nvtop, turbostat, perf, iotop, nethogs, smartctl, dmidecode, sensors with install hints.
- **SQLite history** — `pulse.db` retention, charts, correlation APIs.
- **Sensor audit** — 34/34 sensors reporting after parser fixes; GPU PPT microwatt bug fixed; EMA rate smoothing.
- **Cities II process filter** — `Cities2.exe` only for hero CPU/RAM (no Wine/Proton noise).
- **Readability pass** — 1.5× UI scale, 200px core bars, 18px meters, 400px charts.
- **Sora / Inter typography** — lighter weights, tabular nums on stats.
- **systemd user service** — `pulse.service` on port 8765.

### Changed
- **RAM display** — installed vs usable clarified; dmidecode probe for exact speed.
- **Disk metrics** — busy % calculation corrected.

### Known gaps (not yet shipped)
- Session index over-time chart.
- NVMe SMART panel (smartmontools installed).
- True DRAM bandwidth via perf/turbostat (needs root).
- Live EXPO / RAM speed warning in BIOS.
- Threshold toasts/audio alerts.
- CSV export of history.
- Persist `stutter_score` to SQLite.
- True frametime hooks (beyond proxy).

---

## How to update this file

When shipping a user-visible change:

1. Add bullets under **`[Unreleased]`** in the right category (`Added`, `Changed`, `Fixed`, `Removed`).
2. On a meaningful batch (or end of session), rename `[Unreleased]` to a dated section (`## [YYYY-MM-DD]`) and open a fresh `[Unreleased]` section.
3. Commit in git with a short message that matches the changelog entry (e.g. `feat: smoother meter easing`).
4. Restart Cosmic Pulse after UI/backend changes: `systemctl --user restart pulse`.

### Local git (current)

- Repo root: `/home/tkep/perf-dashboard` · branch **`main`**
- Ignored: `pulse.db*`, `.tuning_log.json`, `.memory_cache.json`, `__pycache__/`, `.ruff_cache/`
- Systemd unit lives at `~/.config/systemd/user/pulse.service` (not in repo); template at `deploy/pulse.service`
- Remote not configured yet — add GitHub/GitLab when ready: `git remote add origin <url>` then `git push -u origin main`