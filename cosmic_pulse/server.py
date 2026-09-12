#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Live performance dashboard for Pop!_OS gaming rigs."""

import argparse
import atexit
import errno
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import psutil

from .benchmarks import chassis_identity, cpu_identity, hardware_comparison, memory_identity
from .cosmic_theme import get_cosmic_theme, get_cosmic_theme_pack
from .diagnostics import (
    diagnostics_job_status,
    get_diagnostics,
    invalidate_diagnostics_cache,
    primary_finding,
    request_diagnostics_scan,
)
from .game_performance import (
    abandon_active_session,
    finalize_open_session,
    seed_last_session,
    tick_game_performance,
)
from .games import (
    LEGACY_GAME_IDS,
    build_games_catalog,
    detect_games,
    primary_active_game_with_linger,
    running_game_ids,
)
from .gpu_thermal import gpu_thermal_state, profile_for_model
from .guidance_auto import apply_live_hysteresis, seed_clear_timers, tick_auto_resolve
from .hardware_probe import (
    discover_drm_cards,
    gpu_device_path,
    gpu_sensor_prefix,
    igpu_device_path,
    igpu_label,
    igpu_sensor_prefix,
    platform_identity,
    probe_nvme_smart,
    probe_storage,
)
from .hardware_profiles import detect_gpu_spec
from .issue_aggregate import (
    _games_for_active,
    build_issue_views,
    guidance_sort_key,
    merge_games_seen,
)
from .load_phase import tick_load_phase
from .paths import app_root, data_dir
from .pulse_config import (
    STATE_VERIFIED_INSIGHTS,
    get_insight_pref_sets,
    get_resolved_insights,
    get_suppressed_insights,
    get_tuning_log_max,
    load_config,
    resolve_insight,
    unresolve_insight,
)
from .store import (
    init_db,
    latest_game_session,
    prune_old,
    record_sample_maybe_prune,
    save_game_session,
    start_writer_worker,
)
from .store import (
    stats as store_stats,
)
from .stutter import attach_stutter, effective_disk_io_wait
from .version import __version__
from . import collectors as col
from .collectors import (  # noqa: F401 — re-export for tests / sample_worker
    PCIE_PEAK_GBPS,
    VRAM_PEAK_GBPS,
    _engine_pct,
    _gpu_stats_sysfs_only,
    _parse_hwmon_tree,
    _prime_rate_counters,
    cpu_freq_percpu,
    cpu_iowait_pct,
    cpu_temps,
    disk_rates,
    gpu_stats,
    load_memory_spec,
    memory_bandwidth,
    net_rates,
    parse_sensors,
    psi_read,
    read_cpu_power_w,
    read_str,
    reprime_rate_baselines,
    sensor_wall,
    set_host_identity,
    swap_rates,
    tools_status,
    vmstat_rates,
    vram_peak_gbps,
)

from .tuning_actions import build_tuning_hints, system_context

PORT = int(os.environ.get("PULSE_PORT", "8765"))
HISTORY_LEN = 3600  # 60 minutes at 1 Hz (Live lab 1m/5m/10m/60m views)
ROOT = app_root()


def _strip_hint(h: dict) -> dict:
    """Drop legacy fix-script fields if present in history / older payloads."""
    out = dict(h)
    for key in ("fix_script", "has_fix_script", "fixable"):
        out.pop(key, None)
    return out


def _strip_hints(hints: list) -> list:
    return [_strip_hint(h) for h in hints]


def _strip_game_performance_trends(gp: dict, *, keep_trend: bool) -> dict:
    """Omit session trend series from API payloads unless keep_trend (bootstrap).

    Live charts rebuild trend from the in-memory history ring; completed sessions
    load trend via /api/game-sessions. Keeps KPI fields identical.
    """
    if not isinstance(gp, dict):
        return gp
    out = dict(gp)
    if keep_trend:
        return out
    if "trend" in out:
        has = bool(out.get("trend"))
        out.pop("trend", None)
        if has:
            out["has_trend"] = True
    ls = out.get("last_session")
    if isinstance(ls, dict) and "trend" in ls:
        ls = dict(ls)
        has = bool(ls.get("trend"))
        ls.pop("trend", None)
        if has:
            ls["has_trend"] = True
        out["last_session"] = ls
    return out


def latest_for_api(
    latest: dict,
    *,
    include_game_issues: bool = True,
    include_session_trend: bool = False,
) -> dict:
    """Slim API payload: strip legacy script fields and optional session trends."""
    if not latest:
        return latest
    out = dict(latest)
    if isinstance(out.get("tuning"), list):
        out["tuning"] = _strip_hints(out["tuning"])
    if isinstance(out.get("tuning_active"), list):
        out["tuning_active"] = _strip_hints(out["tuning_active"])
    if include_game_issues:
        by_game = out.get("issues_by_game")
        if isinstance(by_game, dict):
            stripped = {}
            for gid, block in by_game.items():
                if not isinstance(block, dict):
                    stripped[gid] = block
                    continue
                entry = dict(block)
                if isinstance(entry.get("issues"), list):
                    entry["issues"] = _strip_hints(entry["issues"])
                stripped[gid] = entry
            out["issues_by_game"] = stripped
    else:
        out.pop("issues_by_game", None)
    if isinstance(out.get("game_performance"), dict):
        out["game_performance"] = _strip_game_performance_trends(
            out["game_performance"],
            keep_trend=include_session_trend,
        )
    return out


def slim_history_point(snap: dict) -> dict:
    """Ring-buffer entry for charts and stutter session stats — not full dashboard state.

    Keep only series the UI charts read (see index.html chart pickers). Full bandwidth
    / stutter blobs bloat bootstrap without adding fidelity.
    """
    comp = snap.get("comparison") or {}
    cpu_c = comp.get("cpu") or {}
    gpu_c = comp.get("gpu") or {}
    mem_c = comp.get("memory") or {}
    cpu = snap.get("cpu") or {}
    mem = snap.get("memory") or {}
    dgpu = (snap.get("gpu") or {}).get("discrete") or {}
    gfx_pct = None
    for eng in dgpu.get("engines") or []:
        if isinstance(eng, dict) and eng.get("id") == "gfx" and eng.get("pct") is not None:
            try:
                gfx_pct = float(eng["pct"])
            except (TypeError, ValueError):
                gfx_pct = None
            break
    if gfx_pct is None and dgpu.get("busy_pct") is not None:
        try:
            gfx_pct = float(dgpu.get("busy_pct"))
        except (TypeError, ValueError):
            gfx_pct = None
    gt = snap.get("game_totals") or {}
    slim_gt = {}
    if gt:
        slim_gt = {
            "game_id": gt.get("game_id"),
            "cpu_pct": gt.get("cpu_pct"),
            "running": gt.get("running"),
        }
    net = snap.get("network") or {}
    slim_net = {
        "down_mbps": net.get("down_mbps"),
        "up_mbps": net.get("up_mbps"),
    }
    disk = snap.get("disk") or {}
    slim_disk = {
        "read_mbps": disk.get("read_mbps"),
        "write_mbps": disk.get("write_mbps"),
        "busy_pct": disk.get("busy_pct"),
    }
    bw = snap.get("bandwidth") or {}
    bw_gpu = bw.get("gpu") or {}
    bw_mem = bw.get("memory") or {}
    slim_bw = {
        "gpu": {
            "vram_est_gbps": bw_gpu.get("vram_est_gbps"),
            "gtt_rate_mbps": bw_gpu.get("gtt_rate_mbps"),
        },
        "memory": {
            "dram_est_gbps": bw_mem.get("dram_est_gbps"),
        },
    }
    st = snap.get("stutter") or {}
    sess = st.get("session") or {}
    slim_stutter = {
        "score": st.get("score"),
        "smoothness": st.get("smoothness"),
        "event": st.get("event"),
        "est_ms": st.get("est_ms"),
        "severity": st.get("severity"),
        "components": st.get("components"),
        "session": {
            "events": sess.get("events"),
            "hitch_rate_per_min": sess.get("hitch_rate_per_min"),
            "score_avg": sess.get("score_avg"),
            "score_p95": sess.get("score_p95"),
            "hitch_ms_1pct": sess.get("hitch_ms_1pct"),
            "smoothness_session": sess.get("smoothness_session"),
        }
        if sess
        else {},
    }
    # Temps for Live overview dual-axis chart (package + GPU hotspot)
    cpu_temps = cpu.get("temps") or {}
    ccd = cpu_temps.get("ccd") or []
    package_c = cpu_temps.get("package")
    if package_c is None and ccd:
        try:
            package_c = max(v for v in ccd if v is not None)
        except ValueError:
            package_c = None
    return {
        "ts": snap.get("ts"),
        "cpu": {
            "overall_pct": cpu.get("overall_pct"),
            "temps": {
                "package": package_c,
            },
        },
        "memory": {"pct": mem.get("pct"), "swap_pct": mem.get("swap_pct")},
        "gpu": {
            "discrete": {
                "busy_pct": dgpu.get("busy_pct"),
                "gfx_pct": gfx_pct,
                "vram_pct": dgpu.get("vram_pct"),
                "vram_used_mb": dgpu.get("vram_used_mb"),
                "vram_total_mb": dgpu.get("vram_total_mb"),
                "junction_c": dgpu.get("junction_c"),
                "edge_c": dgpu.get("edge_c"),
                "mem_temp_c": dgpu.get("mem_temp_c"),
            }
        },
        "disk": slim_disk,
        "network": slim_net,
        "bandwidth": slim_bw,
        "stutter": slim_stutter,
        "game_totals": slim_gt,
        "comparison": {
            "session_index": comp.get("session_index"),
            "cpu": {"live_pct": cpu_c.get("live_pct")},
            "gpu": {"live_pct": gpu_c.get("live_pct")},
            "memory": {"live_pressure_pct": mem_c.get("live_pressure_pct")},
        },
    }



_lock = threading.Lock()
_history: list[dict] = []
_latest_full: dict = {}
_static: dict = {}
_tuning_ctx_cache: tuple[float, dict] = (0.0, {})
_TUNING_CTX_TTL = 5.0

# Sampler liveness — freeze-on-resume used to leave the UI on the last sample forever.
# generation bumps abandon a stuck tick thread; watchdog starts a fresh loop.
# Emergency core samples keep the scoreboard moving when a full tick wedges.
_sampler_gen = 0
_sampler_last_ok_mono = 0.0
_sampler_last_ok_wall = 0.0
_sampler_stalls = 0
_sampler_last_reason = ""
_sampler_resume_epoch = 0  # bumps on suspend/resume kill — clients force UI recover
_sampler_ready = threading.Event()
_sampler_restart_mono = 0.0
_sampler_restart_lock = threading.Lock()
# Set when a full tick begins; cleared on publish. Watchdog uses this so a hang
# mid-tick is visible even if the last emergency refresh was recent.
_sampler_tick_started_mono = 0.0
_sampler_tick_lock = threading.Lock()
SAMPLER_STALL_SEC = 8.0
# Don't thrash generations when a full tick is still wedged (thread storm → futex death).
SAMPLER_RESTART_COOLDOWN_SEC = 15.0
# Cap concurrent abandoned sampler loops (Python can't kill them; limit the mess).
SAMPLER_MAX_ABANDONED = 3
_sampler_live_loops = 0
_sampler_live_lock = threading.Lock()
# Supervisor heartbeats (sample_supervisor.py). Distinct from _sampler_last_ok_mono
# so emergency chips cannot hide a wedged apply thread.
_watchdog_last_mono = 0.0
_apply_last_mono = 0.0
_apply_loop_mono = 0.0
_apply_gen = 0
# Guidance / game-session enrich runs off the apply loop so a slow tick cannot
# stall publish (that used to look like a dead apply loop → thread storm).
_enrich_lock = threading.Lock()
_enrich_pending: dict | None = None
_enrich_event = threading.Event()
_enrich_thread: threading.Thread | None = None
_enrich_start_lock = threading.Lock()
_ENRICH_FIELDS = ("tuning", "issues_by_game", "game_performance")
# Wall advanced much more than monotonic → suspend/resume (or a large NTP step).
WALL_JUMP_SEC = 2.5
# Emergency sample must never block the watchdog (sysfs can wedge after suspend).
EMERGENCY_TIMEOUT_SEC = 1.5




_tuning_history: list[dict] = []
_tuning_by_id: dict[str, dict] = {}
_tuning_dirty = False
_tuning_last_save = 0.0
TUNING_LOG = data_dir() / ".tuning_log.json"
TUNING_SAVE_SEC = 12.0
BACKLOG_FILE = ROOT / "backlog.json"


def _tuning_log_file_stats() -> dict:
    """Size/count metadata for Options → Guidance log."""
    entries = len(_tuning_history)
    size_bytes = 0
    if TUNING_LOG.exists():
        try:
            size_bytes = TUNING_LOG.stat().st_size
        except OSError:
            size_bytes = 0
    return {
        "tuning_log_path": str(TUNING_LOG),
        "tuning_log_entries": entries,
        "tuning_log_size_kb": round(size_bytes / 1024, 1),
        "tuning_log_max": get_tuning_log_max(),
    }


def enrich_store_stats(base: dict | None = None) -> dict:
    out = dict(base if base is not None else store_stats())
    out.update(_tuning_log_file_stats())
    return out


def clear_tuning_log_memory(*, save: bool = True) -> int:
    """Drop in-memory Guidance history and optionally wipe the log file."""
    global _tuning_history, _tuning_dirty
    n = len(_tuning_history)
    _tuning_history = []
    _rebuild_tuning_index()
    _tuning_dirty = False
    if save:
        try:
            TUNING_LOG.write_text("[]\n")
        except OSError:
            pass
    return n


def trim_tuning_log_to_max() -> dict:
    """Cap history to configured max (newest kept via current sort order)."""
    global _tuning_history, _tuning_dirty
    cap = get_tuning_log_max()
    before = len(_tuning_history)
    if before > cap:
        del _tuning_history[cap:]
        _rebuild_tuning_index()
        _tuning_dirty = True
        save_tuning_log()
        _tuning_dirty = False
    return {"before": before, "after": len(_tuning_history), "max": cap}





def _migrate_tuning_history() -> None:
    """Normalize legacy game IDs and merge duplicate games_seen timestamps."""
    from .games import LEGACY_GAME_IDS, normalize_game_id

    changed = False
    for item in _tuning_history:
        seen = item.get("games_seen") or {}
        if seen:
            merged: dict[str, float] = {}
            for gid, ts in seen.items():
                norm = normalize_game_id(gid)
                if norm:
                    merged[norm] = max(merged.get(norm, 0), float(ts or 0))
            if merged != seen:
                item["games_seen"] = merged
                changed = True
        games = item.get("games") or []
        if games and games != ["all"]:
            normed = []
            for gid in games:
                norm = normalize_game_id(gid)
                if norm and norm not in normed:
                    normed.append(norm)
            if normed != games:
                item["games"] = normed
                changed = True
        for legacy, canonical in LEGACY_GAME_IDS.items():
            if canonical in (item.get("games_seen") or {}) and legacy in (
                item.get("games_seen") or {}
            ):
                item["games_seen"].pop(legacy, None)
                changed = True
        if item.get("active") is False:
            item["active"] = True
            changed = True
        if "condition_live" not in item:
            item["condition_live"] = False
            changed = True
    if changed:
        save_tuning_log()


def _rebuild_tuning_index() -> None:
    global _tuning_by_id
    _tuning_by_id = {item["insight_id"]: item for item in _tuning_history if item.get("insight_id")}


def _find_tuning_item(iid: str | None, title: str) -> dict | None:
    if iid:
        hit = _tuning_by_id.get(iid)
        if hit:
            return hit
    return next((x for x in _tuning_history if x.get("title") == title), None)


def load_tuning_log() -> None:
    global _tuning_history
    if not TUNING_LOG.exists():
        _rebuild_tuning_index()
        return
    try:
        _tuning_history = json.loads(TUNING_LOG.read_text())
        _migrate_tuning_history()
        _rebuild_tuning_index()
    except (json.JSONDecodeError, OSError):
        _tuning_history = []
        _rebuild_tuning_index()


def save_tuning_log() -> None:
    try:
        TUNING_LOG.write_text(json.dumps(_tuning_history, indent=2))
    except OSError:
        pass


def _maybe_save_tuning_log(*, force: bool = False) -> None:
    global _tuning_dirty, _tuning_last_save
    if not _tuning_dirty and not force:
        return
    now = time.time()
    if force or now - _tuning_last_save >= TUNING_SAVE_SEC:
        save_tuning_log()
        _tuning_last_save = now
        _tuning_dirty = False


def update_tuning_history(
    active: list[dict],
    running_ids: list[str],
    snap: dict | None = None,
) -> list[dict]:
    """Merge per-tick rule matches into persistent Guidance history.

    Active hints update ``condition_live`` and ``last_seen``; history rows stay
    visible when a condition drops for a tick. Sort uses ``guidance_sort_key``
    (severity / priority / first_seen) so order does not jump on live flips.
    See docs/ARCHITECTURE.md § Guidance history.
    """
    global _tuning_history, _tuning_dirty
    now = time.time()
    active_ids = {h["insight_id"] for h in active if h.get("insight_id")}
    resolved_ids, suppressed_ids = get_insight_pref_sets()
    for iid in list(resolved_ids):
        if iid in STATE_VERIFIED_INSIGHTS and iid in active_ids:
            unresolve_insight(iid)
            resolved_ids.discard(iid)
            _tuning_dirty = True
    # Re-open when a marked-fixed issue clears then is detected again (not while still live).
    for item in _tuning_history:
        iid = item.get("insight_id")
        if not iid or iid not in active_ids or iid not in resolved_ids:
            continue
        if not item.get("condition_live", False):
            unresolve_insight(iid)
            resolved_ids.discard(iid)
            _tuning_dirty = True
    for h in active:
        iid = h.get("insight_id")
        hit = _find_tuning_item(iid, h["title"])
        game_hits = _games_for_active(h, running_ids)
        if hit:
            hit.update(
                {
                    "level": h["level"],
                    "title": h["title"],
                    "text": h["text"],
                    "actions": h.get("actions", []),
                    "insight_id": iid,
                    "requires_root": h.get("requires_root"),
                    "games": h.get("games", ["all"]),
                    "bucket": h.get("bucket"),
                    "last_seen": now,
                    "count": hit.get("count", 1) + 1,
                    "active": True,
                    "condition_live": True,
                }
            )
            for legacy in ("fix_script", "has_fix_script", "fixable"):
                hit.pop(legacy, None)
            merge_games_seen(hit, game_hits, now)
            if iid:
                _tuning_by_id[iid] = hit
        else:
            entry = {
                **h,
                "first_seen": now,
                "last_seen": now,
                "count": 1,
                "active": True,
                "condition_live": True,
                "games_seen": {},
            }
            merge_games_seen(entry, game_hits, now)
            _tuning_history.insert(0, entry)
            if iid:
                _tuning_by_id[iid] = entry
    # Live badge hold (hysteresis) so 1 Hz flaps do not blink the list.
    live_ids = apply_live_hysteresis(_tuning_history, active_ids, now)
    for item in _tuning_history:
        iid = item.get("insight_id")
        item["active"] = bool(iid and iid in live_ids)
    # Clear timers: treat held-live as still "active" so we do not start resolving mid-hold.
    if seed_clear_timers(
        _tuning_history,
        live_ids,
        resolved_ids,
        suppressed_ids,
        now,
    ):
        _tuning_dirty = True

    def _fresh_active_ids() -> set[str]:
        invalidate_diagnostics_cache()
        base = snap if snap is not None else _latest_full or {}
        return {h["insight_id"] for h in tuning_hints(base) if h.get("insight_id")}

    # CRITICAL: pass *raw* rule matches (active_ids), NOT live_ids.
    # Passing live_ids re-extended cooldown every tick forever (fixed issues never cleared).
    if tick_auto_resolve(
        _tuning_history,
        active_ids,
        resolved_ids,
        suppressed_ids,
        now,
        resolve_insight,
        fresh_active_ids=_fresh_active_ids,
    ):
        _tuning_dirty = True
    _tuning_history.sort(key=guidance_sort_key)
    cap = get_tuning_log_max()
    if len(_tuning_history) > cap:
        del _tuning_history[cap:]
        _rebuild_tuning_index()
    _tuning_dirty = True
    _maybe_save_tuning_log()
    return _tuning_history


def _tuning_context() -> dict:
    global _tuning_ctx_cache
    now = time.time()
    if now - _tuning_ctx_cache[0] < _TUNING_CTX_TTL:
        return dict(_tuning_ctx_cache[1])
    ctx = system_context()
    drm = discover_drm_cards()
    dpath = drm["discrete"]["device_path"]
    ctx.update(
        {
            "gpu_model": col._gpu_spec.get("model", ""),
            "gpu_card": drm["discrete"].get("card", "card1"),
            "gpu_sysfs": str(dpath),
            "gpu_sensor": f"{(drm['discrete'].get('driver') or 'gpu')}-pci-{gpu_sensor_prefix()}",
        }
    )
    _tuning_ctx_cache = (now, ctx)
    return dict(ctx)


def tuning_hints(snap: dict) -> list[dict]:
    ctx = _tuning_context()
    ctx["gpu_model"] = col._gpu_spec.get("model", "")
    return build_tuning_hints(snap, col._mem_spec, ctx)




def collect_live_core_psutil() -> dict:
    """Absolute-minimum scoreboard sample — psutil/os only, no sysfs, no locks.

    Last-resort path when even sysfs GPU reads wedge (seen after long stalls /
    suspend). Enough for CPU/MEM chips to keep moving.
    """
    try:
        cpu_pct = psutil.cpu_percent(interval=None, percpu=True)
        overall_cpu = round(sum(cpu_pct) / len(cpu_pct), 1) if cpu_pct else 0.0
    except Exception:
        overall_cpu = 0.0
        cpu_pct = []
    try:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        mem = {
            "used_gb": round(vm.used / 1024**3, 2),
            "total_gb": round(vm.total / 1024**3, 2),
            "installed_gb": (col._mem_spec or {}).get("total_gb"),
            "available_gb": round(vm.available / 1024**3, 2),
            "pct": vm.percent,
            "swap_used_gb": round(sw.used / 1024**3, 2),
            "swap_total_gb": round(sw.total / 1024**3, 2),
            "swap_pct": round(sw.percent, 1),
        }
    except Exception:
        mem = {
            "used_gb": None,
            "total_gb": None,
            "installed_gb": (col._mem_spec or {}).get("total_gb"),
            "available_gb": None,
            "pct": 0,
            "swap_used_gb": None,
            "swap_total_gb": None,
            "swap_pct": None,
        }
    try:
        load1, load5, load15 = os.getloadavg()
        load = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except Exception:
        load = [0.0, 0.0, 0.0]
    label = (col._gpu_spec or {}).get("label") or (col._gpu_spec or {}).get("model", "GPU") or "GPU"
    # Preserve last GPU snapshot if any — do not touch sysfs here.
    prev_gpu = {}
    try:
        got = _lock.acquire(blocking=False)
        if got:
            try:
                prev = _latest_full or {}
                prev_gpu = ((prev.get("gpu") or {}).get("discrete")) or {}
            finally:
                _lock.release()
    except Exception:
        prev_gpu = {}
    dgpu = dict(prev_gpu) if prev_gpu else {
        "label": label,
        "busy_pct": None,
        "mem_busy_pct": None,
        "engines": [],
        "vram_used_mb": None,
        "vram_total_mb": None,
        "vram_pct": None,
        "junction_c": None,
        "power_w": None,
        "gtt": {},
    }
    if not dgpu.get("label"):
        dgpu["label"] = label
    return {
        "ts": time.time(),
        "cpu": {
            "overall_pct": overall_cpu,
            "iowait_pct": 0.0,
            "per_core": [],
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "load": load,
            "temps": {"package": None, "ccd": []},
            "power_w": None,
        },
        "memory": mem,
        "gpu": {"discrete": dgpu, "igpu": {}},
        "network": {},
        "disk": {},
        "games": {},
        "game_procs": [],
        "game_totals": {
            "running": False,
            "primary_name": None,
            "primary_pid": None,
            "cpu_pct": 0.0,
            "rss_mb": 0.0,
            "tree_rss_mb": 0.0,
            "proc_count": 0,
            "game_id": None,
            "game_name": None,
            "lingering": False,
            "linger_remaining_sec": None,
        },
        "sensors": [],
        "bandwidth": {"gpu": {}, "memory": {}},
        "load_phase": {},
        "stutter": {"score": 0, "smoothness": 100, "causes": [], "session": {}},
        "nvme_smart": {},
        "tuning_active": [],
        "tuning": [],
        "issues_by_game": {},
        "sensor_health": {"total": 0, "ok": 0, "missing": []},
        "comparison": None,
        "game_performance": {},
        "_degraded": True,
        "_degraded_level": "psutil",
    }


def collect_live_core() -> dict:
    """Minimal scoreboard sample — sysfs + psutil only, no sensors subprocess / game scan.

    Used by the watchdog when a full ``collect_metrics`` tick wedges so CPU/MEM/GPU/VRAM
    keep advancing instead of freezing for hours.
    """
    cpu_pct = psutil.cpu_percent(interval=None, percpu=True)
    overall_cpu = round(sum(cpu_pct) / len(cpu_pct), 1) if cpu_pct else 0.0
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    load1, load5, load15 = os.getloadavg()
    label = (col._gpu_spec or {}).get("label") or (col._gpu_spec or {}).get("model", "GPU") or "GPU"
    try:
        dgpu = _gpu_stats_sysfs_only(gpu_device_path(), label)
    except Exception:
        dgpu = {
            "label": label,
            "busy_pct": None,
            "mem_busy_pct": None,
            "engines": [],
            "vram_used_mb": None,
            "vram_total_mb": None,
            "vram_pct": None,
            "junction_c": None,
            "power_w": None,
            "gtt": {},
        }
    base = {
        "ts": time.time(),
        "cpu": {
            "overall_pct": overall_cpu,
            "iowait_pct": 0.0,
            "per_core": [],
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "temps": {"package": None, "ccd": []},
            "power_w": None,
        },
        "memory": {
            "used_gb": round(vm.used / 1024**3, 2),
            "total_gb": round(vm.total / 1024**3, 2),
            "installed_gb": (col._mem_spec or {}).get("total_gb"),
            "available_gb": round(vm.available / 1024**3, 2),
            "pct": vm.percent,
            "swap_used_gb": round(sw.used / 1024**3, 2),
            "swap_total_gb": round(sw.total / 1024**3, 2),
            "swap_pct": round(sw.percent, 1),
        },
        "gpu": {"discrete": dgpu, "igpu": {}},
        "network": {},
        "disk": {},
        "games": {},
        "game_procs": [],
        "game_totals": {
            "running": False,
            "primary_name": None,
            "primary_pid": None,
            "cpu_pct": 0.0,
            "rss_mb": 0.0,
            "tree_rss_mb": 0.0,
            "proc_count": 0,
            "game_id": None,
            "game_name": None,
            "lingering": False,
            "linger_remaining_sec": None,
        },
        "sensors": [],
        "bandwidth": {"gpu": {}, "memory": {}},
        "load_phase": {},
        "stutter": {"score": 0, "smoothness": 100, "causes": [], "session": {}},
        "nvme_smart": {},
        "tuning_active": [],
        "tuning": [],
        "issues_by_game": {},
        "sensor_health": {"total": 0, "ok": 0, "missing": []},
        "comparison": None,
        "game_performance": {},
        "_degraded": True,
        "_degraded_level": "sysfs",
    }
    # Preserve last full secondary series so emergency ticks don't blank UI/charts.
    # Non-blocking: skip preserve if lock is held by a wedged tick (never block watchdog).
    prev = {}
    got_lock = _lock.acquire(blocking=False)
    if got_lock:
        try:
            prev = _latest_full or {}
        finally:
            _lock.release()
    if prev:
        for key in (
            "comparison",
            "game_performance",
            "games",
            "game_procs",
            "game_totals",
            "tuning",
            "tuning_active",
            "issues_by_game",
            "bandwidth",
            "stutter",
            "sensors",
            "sensor_health",
            "network",
            "disk",
            "nvme_smart",
            "load_phase",
        ):
            if prev.get(key) is not None:
                base[key] = prev[key]
        # Overlay live CPU/MEM/GPU scoreboard on top of frozen secondaries.
        prev_d = ((prev.get("gpu") or {}).get("discrete")) or {}
        if prev_d:
            merged = dict(prev_d)
            for k, v in dgpu.items():
                if v is not None:
                    merged[k] = v
            base["gpu"]["discrete"] = merged
        if (prev.get("gpu") or {}).get("igpu"):
            base["gpu"]["igpu"] = prev["gpu"]["igpu"]
        if prev.get("cpu") and isinstance(prev["cpu"], dict):
            if not base["cpu"].get("temps") or base["cpu"]["temps"].get("package") is None:
                if prev["cpu"].get("temps"):
                    base["cpu"]["temps"] = prev["cpu"]["temps"]
            if not base["cpu"].get("per_core") and prev["cpu"].get("per_core"):
                base["cpu"]["per_core"] = prev["cpu"]["per_core"]
            if base["cpu"].get("power_w") is None and prev["cpu"].get("power_w") is not None:
                base["cpu"]["power_w"] = prev["cpu"]["power_w"]
    return base


def collect_metrics() -> dict:
    # interval=None: delta since last cpu_percent (primed in sampler) — avoids ~80ms block/tick.
    cpu_pct = psutil.cpu_percent(interval=None, percpu=True)
    freqs = cpu_freq_percpu()
    per_core = []
    for i, pct in enumerate(cpu_pct):
        mhz = None
        if freqs and i < len(freqs) and freqs[i]:
            mhz = round(freqs[i].current or 0, 0)
        per_core.append({"id": i, "pct": round(pct, 1), "mhz": mhz})

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    load1, load5, load15 = os.getloadavg()
    games_state = detect_games()
    primary_game = primary_active_game_with_linger(games_state)
    running_ids = running_game_ids(games_state)
    if primary_game and primary_game.get("lingering"):
        gid = primary_game.get("id")
        if gid and gid not in running_ids:
            running_ids.append(gid)
    game_procs = (primary_game or {}).get("procs") or []
    game_totals = {
        "running": bool(primary_game and primary_game.get("running")),
        "primary_name": (primary_game or {}).get("primary_name"),
        "primary_pid": (primary_game or {}).get("primary_pid"),
        "cpu_pct": (primary_game or {}).get("cpu_pct", 0.0),
        "rss_mb": (primary_game or {}).get("rss_mb", 0.0),
        "tree_rss_mb": (primary_game or {}).get("tree_rss_mb", 0.0),
        "proc_count": (primary_game or {}).get("proc_count", 0),
        "game_id": (primary_game or {}).get("id"),
        "game_name": (primary_game or {}).get("name"),
        "lingering": bool((primary_game or {}).get("lingering")),
        "linger_remaining_sec": (primary_game or {}).get("linger_remaining_sec"),
    }
    dgpu = gpu_stats(
        gpu_device_path(),
        col._gpu_spec.get("label") or col._gpu_spec.get("model", "GPU"),
        gpu_sensor_prefix(),
    )
    thermal_profile = col._gpu_spec.get("thermal_profile") or profile_for_model(
        col._gpu_spec.get("model", "")
    )
    dgpu["thermal_profile"] = thermal_profile
    gfx_mhz = dgpu.get("gfx_mhz")
    active_gid = game_totals.get("game_id") if game_totals.get("running") else None
    game_peak_mhz = 0.0
    if active_gid:
        busy_pct = dgpu.get("busy_pct") or 0
        if gfx_mhz and busy_pct >= 25:
            prev = col._gpu_peak_by_game.get(active_gid, 0.0)
            col._gpu_peak_by_game[active_gid] = max(prev, float(gfx_mhz))
        game_peak_mhz = col._gpu_peak_by_game.get(active_gid, 0.0)
    dgpu["thermal_state"] = gpu_thermal_state(dgpu, thermal_profile, game_peak_mhz)
    igpu = gpu_stats(
        igpu_device_path(),
        igpu_label(_static.get("cpu_model", "")),
        igpu_sensor_prefix(),
    )
    overall_cpu = round(sum(cpu_pct) / len(cpu_pct), 1) if cpu_pct else 0.0
    game_cpu = (
        (primary_game or {}).get("cpu_pct", 0.0)
        if primary_game and primary_game.get("running")
        else 0.0
    )
    disk = disk_rates()
    cpu_iowait = cpu_iowait_pct()
    mem_bw = memory_bandwidth(overall_cpu, game_cpu)
    io_wait = effective_disk_io_wait(
        psi_io=float(mem_bw.get("psi_io_avg10") or 0),
        psi_mem=float(mem_bw.get("psi_avg10") or 0),
        disk_busy_pct=float(disk.get("busy_pct") or 0),
        disk_read_mbps=float(disk.get("read_mbps") or 0),
        disk_write_mbps=float(disk.get("write_mbps") or 0),
        cpu_iowait_pct=cpu_iowait,
    )
    mem_bw["cpu_iowait_pct"] = cpu_iowait
    mem_bw["io_wait_pct"] = io_wait["io_wait_pct"]
    mem_bw["io_wait_source"] = io_wait["source"]
    mem_bw["io_wait_zram_dominated"] = io_wait["zram_dominated"]
    gtt = dgpu.get("gtt") or {}

    snap = {
        "ts": time.time(),
        "cpu": {
            "overall_pct": overall_cpu,
            "iowait_pct": cpu_iowait,
            "per_core": per_core,
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "temps": cpu_temps(),
            "power_w": read_cpu_power_w(),
        },
        "memory": {
            "used_gb": round(vm.used / 1024**3, 2),
            "total_gb": round(vm.total / 1024**3, 2),
            "installed_gb": col._mem_spec.get("total_gb"),
            "available_gb": round(vm.available / 1024**3, 2),
            "pct": vm.percent,
            "swap_used_gb": round(sw.used / 1024**3, 2),
            "swap_total_gb": round(sw.total / 1024**3, 2),
            "swap_pct": round(sw.percent, 1),
        },
        "gpu": {"discrete": dgpu, "igpu": igpu},
        "network": net_rates(),
        "disk": disk,
        "games": games_state,
        "game_procs": game_procs,
        "game_totals": game_totals,
        "sensors": sensor_wall(dgpu, igpu),
        "bandwidth": {
            "gpu": {
                "engine_busy_pct": dgpu.get("busy_pct"),
                "vram_busy_pct": dgpu.get("vram_busy_pct", dgpu.get("mem_busy_pct")),
                "vram_est_gbps": dgpu.get("vram_est_gbps"),
                "vram_peak_gbps": dgpu.get("vram_peak_gbps") or vram_peak_gbps(),
                "mclk_mhz": dgpu.get("mclk_mhz"),
                "pcie_link": dgpu.get("pcie_link"),
                "pcie_est_gbps": dgpu.get("pcie_est_gbps"),
                "pcie_peak_gbps": PCIE_PEAK_GBPS,
                "gtt_used_mb": gtt.get("used_mb"),
                "gtt_rate_mbps": gtt.get("rate_mbps"),
            },
            "memory": mem_bw,
        },
    }
    snap["load_phase"] = tick_load_phase(snap)
    # Copy history under lock; compute stutter outside so HTTP never waits on stutter math.
    with _lock:
        hist_snap = list(_history)
    attach_stutter(snap, hist_snap)
    # Optional smartctl NVMe health (cached ~3 min; no-op without permissions)
    smart = probe_nvme_smart()
    snap["nvme_smart"] = {
        "readable": bool(smart.get("readable")),
        "permission_error": bool(smart.get("permission_error")),
        "message": smart.get("message"),
        "drives": smart.get("drives") or {},
    }
    # Merge SMART onto static storage labels for the drive list UI
    if _static and smart.get("readable"):
        for drive in _static.get("storage") or []:
            name = drive.get("name") or drive.get("id")
            health = (smart.get("drives") or {}).get(name)
            if health:
                drive["smart"] = health
        rig_storage = (_static.get("rig") or {}).get("storage")
        if rig_storage is _static.get("storage"):
            pass  # same list
        elif isinstance(rig_storage, list):
            for drive in rig_storage:
                name = drive.get("name") or drive.get("id")
                health = (smart.get("drives") or {}).get(name)
                if health:
                    drive["smart"] = health
    active_hints = tuning_hints(snap)
    snap["tuning_active"] = active_hints
    # This-tick matches only. Parent accept_child_sample owns the Guidance log.
    snap["tuning"] = active_hints
    snap["issues_by_game"] = {}
    tiles = snap["sensors"]
    snap["sensor_health"] = {
        "total": len(tiles),
        "ok": sum(1 for t in tiles if t.get("value") is not None),
        "missing": [t["label"] for t in tiles if t.get("value") is None],
    }
    snap["comparison"] = hardware_comparison(
        _static.get("cpu_model", ""),
        _static.get("gpu_model", "Discrete GPU"),
        col._mem_spec,
        snap,
        gpu_info=_static.get("gpu") or col._gpu_spec,
        machine=_static.get("machine", ""),
        hostname=_static.get("hostname", ""),
        board_vendor=(
            ((_static.get("platform") or {}).get("vendor") or {}).get("name")
            or _static.get("board_vendor")
            or ""
        ),
        board_name=_static.get("board_name", ""),
    )
    # Game sessions persist on the parent apply path so a SIGKILL'd worker
    # does not drop the in-progress session.
    return snap



def _mark_sample_ok() -> None:
    global _sampler_last_ok_mono, _sampler_last_ok_wall
    _sampler_last_ok_mono = time.monotonic()
    _sampler_last_ok_wall = time.time()


def sampler_status() -> dict:
    """Liveness for /api/metrics — client uses this to show Stale vs Online.

    ``ok`` follows the **apply** heartbeat after the first full sample. Emergency
    scoreboard ticks still refresh ``age_sec`` so chips can move, but they cannot
    keep ``ok`` true while apply is dead (worker-fine / API-frozen).
    """
    now = time.monotonic()
    wd_age = round(now - _watchdog_last_mono, 2) if _watchdog_last_mono else None
    apply_age = round(now - _apply_last_mono, 2) if _apply_last_mono else None
    apply_loop_age = round(now - _apply_loop_mono, 2) if _apply_loop_mono else None
    if not _sampler_last_ok_mono:
        return {
            "ok": False,
            "age_sec": None,
            "generation": _sampler_gen,
            "stalls": _sampler_stalls,
            "reason": _sampler_last_reason or "starting",
            "degraded": False,
            "state": "starting",
            "last_apply_age_sec": apply_age,
            "watchdog_age_sec": wd_age,
            "apply_loop_age_sec": apply_loop_age,
        }
    age = now - _sampler_last_ok_mono
    tick_age = None
    with _sampler_tick_lock:
        started = _sampler_tick_started_mono
    if started:
        tick_age = round(now - started, 2)
    degraded = _sampler_last_reason in ("degraded", "stall")
    tick_wedged = bool(tick_age is not None and tick_age >= SAMPLER_STALL_SEC)
    full_ok = bool(_apply_last_mono and (now - _apply_last_mono) < SAMPLER_STALL_SEC)
    boot_ok = (not _apply_last_mono) and age < SAMPLER_STALL_SEC
    if tick_wedged or (not full_ok and not boot_ok):
        state = "stale"
    elif degraded:
        state = "degraded"
    elif boot_ok:
        state = "starting"
    else:
        state = "healthy"
    return {
        "ok": state in ("healthy", "starting", "degraded") and not tick_wedged,
        "age_sec": round(age, 2),
        "tick_age_sec": tick_age,
        "generation": _sampler_gen,
        "stalls": _sampler_stalls,
        "resume_epoch": int(_sampler_resume_epoch or 0),
        "reason": _sampler_last_reason or None,
        "degraded": degraded or tick_wedged or state == "stale",
        "state": state,
        "last_apply_age_sec": apply_age,
        "watchdog_age_sec": wd_age,
        "apply_loop_age_sec": apply_loop_age,
    }


def _publish_sample(
    snap: dict,
    my_gen: int | None = None,
    *,
    into_history: bool = True,
) -> bool:
    """Publish under lock if this generation still owns the loop (or gen is None = supervisor).

    Degraded/emergency samples set ``into_history=False`` so chart series are not
    zeroed by a partial scoreboard tick. Full child samples use ``into_history=True``.
    """
    global _history, _latest_full, _sampler_tick_started_mono, _apply_last_mono
    # Supervisor / emergency path (no generation ownership).
    if my_gen is None:
        got = _lock.acquire(blocking=True, timeout=0.5)
        if not got:
            # Last resort: publish without lock (better than freeze).
            _latest_full = snap
            _mark_sample_ok()
            if into_history:
                _apply_last_mono = time.monotonic()
            return True
        try:
            _latest_full = snap
            if into_history:
                _history.append(slim_history_point(snap))
                if len(_history) > HISTORY_LEN:
                    _history.pop(0)
        finally:
            _lock.release()
        with _sampler_tick_lock:
            _sampler_tick_started_mono = 0.0
        _mark_sample_ok()
        if into_history:
            _apply_last_mono = time.monotonic()
        return True

    with _lock:
        if my_gen is not None and my_gen != _sampler_gen:
            return False
        _latest_full = snap
        if into_history:
            _history.append(slim_history_point(snap))
            if len(_history) > HISTORY_LEN:
                _history.pop(0)
    with _sampler_tick_lock:
        _sampler_tick_started_mono = 0.0
    _mark_sample_ok()
    if into_history:
        _apply_last_mono = time.monotonic()
    return True


def _carry_live_enrich(prev: dict | None, snap: dict) -> None:
    """Keep last Guidance/session block on a new sample until enrich catches up."""
    if not prev:
        return
    for key in _ENRICH_FIELDS:
        if key not in snap and prev.get(key) is not None:
            snap[key] = prev[key]


def _ensure_enrich_thread() -> None:
    global _enrich_thread
    t = _enrich_thread
    if t is not None and t.is_alive():
        return
    with _enrich_start_lock:
        t = _enrich_thread
        if t is not None and t.is_alive():
            return
        t = threading.Thread(
            target=_run_sample_enrich_loop,
            daemon=True,
            name="pulse-enrich",
        )
        _enrich_thread = t
        t.start()


def _enqueue_sample_enrich(snap: dict) -> None:
    global _enrich_pending
    with _enrich_lock:
        _enrich_pending = snap
    _enrich_event.set()
    _ensure_enrich_thread()


def _run_sample_enrich_loop() -> None:
    global _enrich_pending
    while True:
        _enrich_event.wait(timeout=1.0)
        with _enrich_lock:
            snap = _enrich_pending
            _enrich_pending = None
            _enrich_event.clear()
        if snap is None:
            continue
        try:
            _enrich_published_sample(snap)
        except Exception as exc:
            print(f"Cosmic Pulse sampler: parent enrich failed: {exc}", flush=True)


def _enrich_published_sample(snap: dict) -> None:
    """Stutter window + Guidance history + game session — must not run on apply."""
    hist: list = []
    got = _lock.acquire(blocking=True, timeout=0.5)
    if got:
        try:
            hist = list(_history)
        finally:
            _lock.release()
    attach_stutter(snap, hist)
    games_state = snap.get("games") or {}
    running_ids = running_game_ids(games_state)
    gt = snap.get("game_totals") or {}
    gid = gt.get("game_id")
    if gt.get("running") and gid and gid not in running_ids:
        running_ids.append(gid)
    active = snap.get("tuning_active") or []
    history = update_tuning_history(active, running_ids, snap)
    views = build_issue_views(active, history, running_ids, games_state)
    snap["tuning"] = views["overall"]
    snap["issues_by_game"] = views["by_game"]
    snap["game_performance"] = tick_game_performance(snap, save_session=save_game_session)


def accept_child_sample(snap: dict) -> bool:
    """Publish the live sample immediately; enrich Guidance/session off-thread."""
    global _apply_loop_mono, _latest_full
    _apply_loop_mono = time.monotonic()
    prev = _latest_full if isinstance(_latest_full, dict) else None
    _carry_live_enrich(prev, snap)
    if not _publish_sample(snap, my_gen=None, into_history=True):
        return False
    _apply_loop_mono = time.monotonic()
    _enqueue_sample_enrich(snap)
    return True


def clear_live_history_ring() -> None:
    """Empty the in-memory chart ring (Options clear samples)."""
    global _history
    with _lock:
        _history = []
    abandon_active_session()


def listen_host() -> str:
    """Default loopback. ``--lan`` or ``PULSE_LAN=1`` binds all interfaces."""
    if "--lan" in sys.argv:
        return "0.0.0.0"
    flag = os.environ.get("PULSE_LAN", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return "0.0.0.0"
    return "127.0.0.1"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cosmic-pulse",
        description="Local Linux gaming performance dashboard (http://127.0.0.1:8765).",
    )
    parser.add_argument("--lan", action="store_true", help="Bind 0.0.0.0 (no auth; trusted LAN only)")
    parser.add_argument("--port", type=int, metavar="N", help="HTTP port (default 8765, or PULSE_PORT)")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the dashboard in a browser (if the port is busy, just open it)",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def apply_cli(args: argparse.Namespace) -> None:
    global PORT
    if args.port:
        if args.port < 1 or args.port > 65535:
            raise SystemExit(f"invalid --port {args.port}")
        os.environ["PULSE_PORT"] = str(args.port)
        PORT = args.port
    if args.lan:
        os.environ["PULSE_LAN"] = "1"


def _run_sampler_loop(my_gen: int, platform_last_refresh: float) -> None:
    """1 Hz sample loop for one generation. Abandoned gens exit without publishing."""
    global _sampler_last_reason, _sampler_tick_started_mono, _sampler_live_loops

    with _sampler_live_lock:
        _sampler_live_loops += 1
    last_wall = time.time()
    last_mono = time.monotonic()
    tools_tick = 0

    try:
        while my_gen == _sampler_gen:
            # Must never exit on a single tick failure — that used to freeze the UI.
            try:
                now_wall = time.time()
                now_mono = time.monotonic()
                wall_dt = now_wall - last_wall
                mono_dt = max(0.0, now_mono - last_mono)
                # Suspend/resume: wall jumps hours while mono only advanced ~sleep remainder.
                if (wall_dt - mono_dt) > WALL_JUMP_SEC or (wall_dt > 5.0 and mono_dt < 2.0):
                    print(
                        "Cosmic Pulse sampler: resume/time-jump detected "
                        f"(wall_dt={wall_dt:.1f}s mono_dt={mono_dt:.1f}s) — reprime rates",
                        flush=True,
                    )
                    _sampler_last_reason = "resume"
                    reprime_rate_baselines()
                    _prime_rate_counters()
                last_wall = now_wall
                last_mono = now_mono

                if my_gen != _sampler_gen:
                    return

                try:
                    pack = get_cosmic_theme_pack()
                    _static["cosmic_theme"] = pack["auto"]
                    _static["cosmic_theme_dark"] = pack["dark"]
                    _static["cosmic_theme_light"] = pack["light"]
                except Exception:
                    pass
                # Tool inventory is TTL-cached; refresh every ~30 ticks max, not every second.
                tools_tick += 1
                if tools_tick == 1 or tools_tick % 30 == 0:
                    try:
                        _static["tools"] = tools_status()
                    except Exception:
                        pass
                # Re-detect running DE rarely — session hops are uncommon
                now_plat = time.time()
                if now_plat - platform_last_refresh > 900:  # 15 min
                    try:
                        _static["platform"] = platform_identity()
                        platform_last_refresh = now_plat
                    except Exception:
                        pass

                with _sampler_tick_lock:
                    _sampler_tick_started_mono = time.monotonic()
                snap = collect_metrics()
                if my_gen != _sampler_gen:
                    return
                if not _publish_sample(snap, my_gen):
                    return
                if _sampler_last_reason in ("resume", "stall", "starting", "degraded"):
                    _sampler_last_reason = ""
                try:
                    record_sample_maybe_prune(snap)
                except Exception as exc:
                    print(f"Cosmic Pulse DB: sample write failed: {exc}", flush=True)
            except Exception as exc:
                print(f"Cosmic Pulse sampler: tick failed (will retry): {exc}", flush=True)
                import traceback

                traceback.print_exc()
                with _sampler_tick_lock:
                    _sampler_tick_started_mono = 0.0

            # Slice sleep so abandoned generations exit quickly and resume is noticed soon.
            for _ in range(10):
                if my_gen != _sampler_gen:
                    return
                time.sleep(0.1)
    finally:
        with _sampler_live_lock:
            _sampler_live_loops = max(0, _sampler_live_loops - 1)


def init_probe_state(*, for_child: bool = False) -> float:
    """Load hardware identity + static payload used by collect_metrics / HTTP.

    Returns ``platform_last_refresh`` wall time. Safe to call in parent (HTTP) and
    in the killable sample child (spawn). ``for_child`` skips backlog JSON read
    noise and keeps child init lean.
    """
    global _history, _latest_full, _static
    global _sampler_last_reason
    from . import hardware_probe as hp

    hp._drm_cache = None
    hp._storage_cache = None

    col._mem_spec = load_memory_spec()
    col._gpu_spec = detect_gpu_spec()
    col._gpu_peak_by_game = {}
    col.VRAM_PEAK_GBPS = col._gpu_spec["vram_peak_gbps"]
    load_tuning_log()
    discover_drm_cards()
    storage_drives = probe_storage()
    product = read_str(Path("/sys/class/dmi/id/product_name")) or "Unknown"
    product_ver = read_str(Path("/sys/class/dmi/id/product_version")) or ""
    sys_vendor = read_str(Path("/sys/class/dmi/id/sys_vendor")) or ""
    board_vendor = read_str(Path("/sys/class/dmi/id/board_vendor")) or ""
    board_name = read_str(Path("/sys/class/dmi/id/board_name")) or ""
    cpu_model = open("/proc/cpuinfo").read().split("model name\t: ", 1)[-1].split("\n", 1)[0]
    set_host_identity(cpu_model=cpu_model, storage=storage_drives)
    machine = f"{product} ({product_ver})" if product_ver else product
    host_platform = platform_identity()
    # Prefer chassis OEM (sys_vendor) so System76 Thelio is recognized reliably
    s76_vendor = sys_vendor or board_vendor or (host_platform.get("vendor") or {}).get("name") or ""
    platform_last_refresh = time.time()
    backlog: list = []
    if not for_child and BACKLOG_FILE.exists():
        try:
            backlog = json.loads(BACKLOG_FILE.read_text())
        except Exception:
            backlog = []
    _static = {
        "hostname": os.uname().nodename,
        "machine": machine,
        "board_vendor": board_vendor,
        "board_name": board_name,
        "cpu_model": cpu_model,
        "storage": storage_drives,
        "threads": psutil.cpu_count(logical=True),
        "history_max_sec": HISTORY_LEN,
        "gpu_model": col._gpu_spec.get("model", "Discrete GPU"),
        "gpu_thermal": (
            col._gpu_spec.get("thermal_profile") or profile_for_model(col._gpu_spec.get("model", ""))
        ),
        "gpu": col._gpu_spec,
        "vram_peak_gbps": col._gpu_spec.get("vram_peak_gbps", col.VRAM_PEAK_GBPS),
        "dram_peak_gbps": (col._mem_spec or {}).get("peak_gbps", 89.6),
        "pcie_peak_gbps": PCIE_PEAK_GBPS,
        "memory": col._mem_spec or {},
        "platform": host_platform,
        "rig": {
            "chassis": chassis_identity(
                machine, os.uname().nodename, s76_vendor, board_name
            ),
            "cpu": cpu_identity(cpu_model),
            "gpu": col._gpu_spec,
            "memory": memory_identity(col._mem_spec or {}),
            "storage": storage_drives,
        },
        "tools": tools_status(),
        "backlog": backlog,
        "pulse_root": str(ROOT),
        "cosmic_theme": get_cosmic_theme(),
        "suppressed_insights": get_suppressed_insights(),
        "resolved_insights": get_resolved_insights(),
        "pulse_config": load_config(),
        "games_catalog": build_games_catalog(),
        "legacy_game_ids": dict(LEGACY_GAME_IDS),
        "pulse_version": __version__,
    }
    _prime_rate_counters()
    try:
        psutil.cpu_percent(interval=0.1, percpu=True)
    except Exception:
        pass
    _sampler_last_reason = "starting"
    return platform_last_refresh


def sampler():
    """Legacy in-process sampler (tests / fallback). Production uses sample_supervisor."""
    platform_last_refresh = init_probe_state(for_child=False)
    _mark_sample_ok()
    _sampler_ready.set()
    _run_sampler_loop(_sampler_gen, platform_last_refresh)


def _watchdog_emergency_publish() -> bool:
    """Publish a core scoreboard sample so live chips keep moving during a full-tick hang.

    Never blocks the watchdog: sysfs/GPU reads run with a hard timeout; on timeout
    fall back to pure psutil. Does not append to the chart ring.
    """
    global _sampler_last_reason
    box: dict = {"snap": None, "err": None}

    def _worker(use_sysfs: bool) -> None:
        try:
            box["snap"] = collect_live_core() if use_sysfs else collect_live_core_psutil()
        except Exception as exc:
            box["err"] = exc

    # Prefer sysfs GPU; if it wedges, fall back to psutil-only.
    for use_sysfs, label in ((True, "sysfs"), (False, "psutil")):
        box["snap"] = None
        box["err"] = None
        t = threading.Thread(
            target=_worker,
            args=(use_sysfs,),
            daemon=True,
            name=f"pulse-emergency-{label}",
        )
        t.start()
        t.join(timeout=EMERGENCY_TIMEOUT_SEC)
        if t.is_alive():
            print(
                f"Cosmic Pulse sampler: emergency {label} timed out "
                f"({EMERGENCY_TIMEOUT_SEC}s) — trying fallback",
                flush=True,
            )
            continue
        if box["err"] is not None:
            print(f"Cosmic Pulse sampler: emergency {label} failed: {box['err']}", flush=True)
            continue
        snap = box["snap"]
        if not snap:
            continue
        if _publish_sample(snap, my_gen=None, into_history=False):
            _sampler_last_reason = "degraded"
            print(
                "Cosmic Pulse sampler: emergency core sample published "
                f"({label} cpu={snap['cpu'].get('overall_pct')}% "
                f"gpu={((snap.get('gpu') or {}).get('discrete') or {}).get('busy_pct')}%)",
                flush=True,
            )
            return True
    print("Cosmic Pulse sampler: emergency sample failed (all paths)", flush=True)
    return False


def sampler_watchdog() -> None:
    """Keep live stats alive if a full tick blocks past SAMPLER_STALL_SEC.

    1. Immediately publish a lightweight core sample (CPU/MEM/GPU/VRAM) so the UI unfreezes.
    2. Cooldown-restart a fresh full sample loop (abandon stuck gen) without spawning a storm.

    The watchdog loop itself must never block on sysfs/sensors/locks — that is how
    metrics stayed frozen for hours after a single stalled recovery.
    """
    global _sampler_gen, _sampler_stalls, _sampler_last_reason, _sampler_restart_mono

    if not _sampler_ready.wait(timeout=45):
        print("Cosmic Pulse sampler: watchdog — sampler never became ready", flush=True)
        # Still try to keep something alive.
        _mark_sample_ok()

    while True:
        try:
            time.sleep(2.0)
            if not _sampler_last_ok_mono:
                _mark_sample_ok()
                continue
            age = time.monotonic() - _sampler_last_ok_mono
            with _sampler_tick_lock:
                started = _sampler_tick_started_mono
            tick_age = (time.monotonic() - started) if started else 0.0
            # Stall if no publish recently OR a full tick has been in-flight too long
            # (emergency samples alone must not hide a permanently wedged full loop).
            stalled = age >= SAMPLER_STALL_SEC or tick_age >= SAMPLER_STALL_SEC
            if not stalled:
                continue

            # Always try to unfreeze the scoreboard first (timeout-bounded).
            _watchdog_emergency_publish()

            now_m = time.monotonic()
            with _sampler_restart_lock:
                if now_m - _sampler_restart_mono < SAMPLER_RESTART_COOLDOWN_SEC:
                    continue
                with _sampler_live_lock:
                    live = _sampler_live_loops
                if live >= SAMPLER_MAX_ABANDONED + 1:
                    # Don't spawn more abandoned loops; emergency keeps chips alive.
                    print(
                        f"Cosmic Pulse sampler: stalled age={age:.1f}s tick={tick_age:.1f}s — "
                        f"live loops={live} at cap, emergency only",
                        flush=True,
                    )
                    _sampler_restart_mono = now_m
                    continue
                _sampler_restart_mono = now_m
                _sampler_stalls += 1
                _sampler_gen += 1
                new_gen = _sampler_gen
                _sampler_last_reason = "stall"
            print(
                f"Cosmic Pulse sampler: stalled age={age:.1f}s tick={tick_age:.1f}s — "
                f"restarting generation {new_gen} (stalls={_sampler_stalls})",
                flush=True,
            )
            try:
                reprime_rate_baselines()
                _prime_rate_counters()
            except Exception as exc:
                print(f"Cosmic Pulse sampler: reprime after stall failed: {exc}", flush=True)
            t = threading.Thread(
                target=_run_sampler_loop,
                args=(new_gen, time.time()),
                daemon=True,
                name=f"pulse-sampler-{new_gen}",
            )
            t.start()
        except Exception as exc:
            print(f"Cosmic Pulse sampler: watchdog error (continuing): {exc}", flush=True)
            import traceback

            traceback.print_exc()
            time.sleep(2.0)



def _open_dashboard(host: str) -> None:
    url = f"http://127.0.0.1:{PORT}/"
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as exc:
        print(f"Cosmic Pulse: could not open browser ({exc})", flush=True)


def main(open_browser: bool = False):
    # spawn children must be protected on some platforms; always fine as main.
    init_db()
    # Background SQLite writer (WAL) — sample inserts never block the 1 Hz sampler.
    start_writer_worker()
    seed_last_session(latest_game_session())
    pruned = prune_old()
    if pruned:
        print(f"Cosmic Pulse DB: pruned {pruned} old samples")
    # Static probe in the PARENT so /api/metrics bootstrap works immediately.
    init_probe_state(for_child=False)
    _mark_sample_ok()
    _sampler_ready.set()
    # Warm Guidance Scan off the request path (quiet async; no modal).
    request_diagnostics_scan()
    # Killable sample child — wedged ticks get SIGKILL; parent stays alive forever.
    # Pass this module explicitly: when launched as ``python server.py`` we are
    # ``__main__``, not ``server``, and a second import would shadow state.
    from .sample_supervisor import start_sample_supervisor, stop_supervisor

    start_sample_supervisor(srv=sys.modules[__name__])
    time.sleep(1.2)
    atexit.register(lambda: finalize_open_session(save_session=save_game_session))
    from .http_api import Handler

    host = listen_host()
    try:
        server = ThreadingHTTPServer((host, PORT), Handler)
    except OSError as exc:
        if open_browser and getattr(exc, "errno", None) == errno.EADDRINUSE:
            print(f"Cosmic Pulse already on port {PORT} — opening the dashboard", flush=True)
            _open_dashboard(host)
            return
        raise
    print(f"Cosmic Pulse {__version__}: http://127.0.0.1:{PORT}")
    if host == "0.0.0.0":
        print("              LAN bind (--lan / PULSE_LAN=1) — no authentication")
        try:
            ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
            print(f"              http://{ip}:{PORT}")
        except (subprocess.SubprocessError, IndexError):
            pass
    print("Press Ctrl+C to stop.")

    def _stop(_signum=None, _frame=None):
        print("Cosmic Pulse: stopping", flush=True)
        try:
            stop_supervisor()
        except Exception:
            pass
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if open_browser:
        threading.Timer(0.5, lambda: _open_dashboard(host)).start()
    server.serve_forever()


def run() -> None:
    """Process entry: CLI + HTTP server. Used by ``server.py`` and ``-m cosmic_pulse``."""
    sys.modules.setdefault("cosmic_pulse.server", sys.modules[__name__])
    mp_method = os.environ.get("PULSE_MP_START", "spawn")
    try:
        import multiprocessing as _mp

        _mp.set_start_method(mp_method, force=False)
    except RuntimeError:
        pass
    _args = parse_args()
    apply_cli(_args)
    main(open_browser=_args.open)


if __name__ == "__main__":
    run()
