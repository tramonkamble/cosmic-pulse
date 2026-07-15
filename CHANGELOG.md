# Changelog

All notable changes to **Cosmic Pulse** (perf-dashboard) are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Dates use the machine local timezone (EDT unless noted).

## [Unreleased]

### Added
- **Proton Wayland general recommendation** — `proton-wayland-launch-fix` Guidance card (info, per-game) when a Proton title runs on Wayland without the X11 launch override; metrics from `session.wayland`, `game.proton`, and Steam `LaunchOptions`; `tests/test_game_launch.py`.
- **Backlog: per-game general options UI** — future home for clickable launch-option tunables on the games list (separate from live issue cards).
- **De-hardcode initiative** — game overrides and legacy AppIDs live in `rules/builtin/pulse-default/pack.yaml`; fix scripts use active `appid` (no CS2 `730` fallbacks); dynamic lib-install lines from diagnostics; `{steam.root}` templates in Steam rules; `legacy_game_ids` on static API; `tests/test_game_dynamic.py`.
- **Linting** — Ruff config in `pyproject.toml`; documented in `CONTRIBUTING.md`.

### Changed
- **Wayland launch dedupe** — X11 override guidance lives in `proton-wayland-launch-fix` only; GameMode/governor/resolution rules no longer repeat the same Steam launch string.

### Changed
- **Lazy per-game issues** — `issues_by_game` ships on bootstrap and via `GET /api/issues-by-game` when guidance structure changes; steady-state polls omit the ~70 KB block (live/running flags patched client-side from `games`).
- **Live overview order** — Stutter estimate now appears above Pulse Index.
- **Summary widget layout** — tetris 4×2 metric grid (tall Health + Pulse Index); flat rig strip; hardware status cards fill each row evenly. Reverted global 3-across dashboard compaction.
- **Summary hardware strip** — rig tiles slimmed down; temps/drives/network grouped into labeled status cards (no more cramped sensor pill grid).
- **Label refinements** — summary tile **Pulse Index**; hardware **Class** (was Tier); **Game process** (was Game CPU); **Memory bus** merges VRAM bus/controller; backlog hidden from UI; profiling tools drill stands alone.
- **Label pass (American English)** — GPU activity strip uses Shaders / Memory bus / Video; jargon trimmed across dashboard (stutter estimate, memory wait, GPU hotspot, vs typical/high-end PC, RAM bandwidth, etc.).

### Changed
- **Rig strip tiles** — hardware filter buttons drop live stats; tall right-side icon panel with subtle top-level brand wordmarks (AMD, Intel, NVIDIA, System76).
- **Lazy fix scripts** — tuning hints ship `has_fix_script` only; script bodies load on demand via `GET /api/fix-script?insight_id=…` (copy, save, view).
- **Metrics polling** — first load uses `/api/metrics?bootstrap=1` (static + full history); each 1s tick fetches latest + one slim history point only (~310 KB vs re-downloading the full buffer).
- **Metrics payload** — history ring buffer stores slim chart samples (~5 KB/point) instead of full dashboard snapshots (~310 KB/point); `/api/metrics` no longer ships duplicated fix scripts and per-game issues 600×.

### Added
- **Steam pending update (Guidance)** — `game-update-pending` insight when the active game has a suspended patch or incomplete download/stage; fix script opens Downloads and optionally clears `shadercache/<appid>`. Split from `game-files-corrupt` (verify-only).
- **Possible resolutions (Guidance)** — separate section for low-risk pattern matches (`bucket: resolutions`). First insight: **gpu-fps-cap** when GPU ≥85% busy on a ≤75 Hz display while a game runs.
- **More resolution patterns** — mild swap + stutter → free RAM; load page faults → wait 30s; CPU-bound + power-save governor → performance mode.
- **GPU engine strip** — decode AMD `gpu_metrics` sysfs (GFX / VRAM / MM activity %) and show per-engine bars in the rig snapshot; falls back to `gpu_busy_percent` / `mem_busy_percent` when a counter is unavailable.
- **Remediation policy** — Pulse never runs kill commands, sudo, or external apps. Fixes are copy-paste suggestions; **Fix** only applies safe user-owned config writes (none destructive today). Root scripts are labeled **Requires root**.
- **Warnings panel** — cleaner card layout, hides healthy “ok” hints, instant hardware-focus filter (no collapse glitch), session-aware sorting.
- **Game context** — active game name in header/meta, warnings “Monitoring …” chip, dynamic Game CPU chart label, CS2/Cities II proc table text.
- **Hardware focus filter** — redesigned rig strip with live stats; click chassis (Thelio) to view full rig, or click CPU/GPU/RAM to filter NOC widgets in place (same layout, unrelated metrics hidden).
- **Hardware focus polish** — viz widget titles react to CPU/GPU/Memory filter; focused summary cell gets subtle hero treatment; filtered metrics fade/collapse (respects reduced motion); warnings hide when not relevant to the active filter.

### Changed
- **Stutter proxy layout** — compact 50/50 split: driver bars on the left; hitch gauge, KPIs, weighted driver-mix bar, and 5-minute event timeline on the right.
- **Stutter proxy detail** — taller widget; KPI subs, live status line, session avg/p95/rate under timeline, richer hitch tooltips and timeline meta (peak score, est. ms, last hitch).

### Fixed
- **RDNA3 tuning hints** — `warm_c` is intentionally `None` on RDNA3; FPS-cap hint no longer crashes the sampler when junction is high.
- **Dashboard boot** — removed duplicate `prefersReducedMotion` declaration (const + function) that caused a script parse error and left the entire UI stuck on “Connecting…” with no live data.
- **Display stability** — EMA smoothing for session load index, league live bars, and chart series; tier badges only re-render when rank changes; util chart locked to 0–100% y-axis; bandwidth/I/O charts use slowly-adjusting axis max to prevent vertical jump.

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