#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Live performance dashboard for Pop!_OS gaming rigs."""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psutil

from apply_fix import apply_fix
from benchmarks import chassis_identity, cpu_identity, hardware_comparison, memory_identity
from cosmic_theme import get_cosmic_theme
from diagnostics import (
    diagnostics_job_status,
    get_diagnostics,
    invalidate_diagnostics_cache,
    primary_finding,
    request_diagnostics_scan,
)
from game_performance import seed_last_session, tick_game_performance
from games import (
    LEGACY_GAME_IDS,
    build_games_catalog,
    detect_games,
    primary_active_game_with_linger,
    prime_game_cpu,
    running_game_ids,
)
from gpu_metrics import read_gpu_engines
from gpu_thermal import gpu_thermal_state, profile_for_model
from guidance_auto import apply_live_hysteresis, seed_clear_timers, tick_auto_resolve
from hardware_probe import (
    discover_drm_cards,
    enrich_memory_spec,
    gpu_device_path,
    gpu_sensor_prefix,
    igpu_device_path,
    igpu_label,
    igpu_sensor_prefix,
    nvme_sensor_tiles,
    platform_identity,
    probe_nvme_smart,
    probe_storage,
)
from hardware_profiles import detect_gpu_spec
from issue_aggregate import (
    _games_for_active,
    build_issue_views,
    guidance_sort_key,
    merge_games_seen,
)
from load_phase import tick_load_phase
from paths import app_root, data_dir
from probe_memory import infer_fallback
from pulse_config import (
    STATE_VERIFIED_INSIGHTS,
    get_insight_pref_sets,
    get_resolved_insights,
    get_suppressed_insights,
    get_tuning_log_max,
    load_config,
    resolve_insight,
    unresolve_insight,
)
from store import (
    correlate,
    init_db,
    latest_game_session,
    list_game_sessions,
    list_session_markers,
    prune_old,
    record_sample_maybe_prune,
    record_session_marker,
    save_game_session,
    series,
    start_writer_worker,
    update_settings,
)
from store import (
    stats as store_stats,
)
from stutter import attach_stutter, effective_disk_io_wait
from tuning_actions import build_tuning_hints, fix_script_for_insight, system_context

PORT = int(os.environ.get("PULSE_PORT", "8765"))
HISTORY_LEN = 600  # 10 minutes at 1 Hz
ROOT = app_root()


def _strip_hint(h: dict) -> dict:
    out = dict(h)
    if "fix_script" in out:
        if "has_fix_script" not in out:
            out["has_fix_script"] = bool(out.get("fix_script"))
        del out["fix_script"]
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
    """Drop bulky fix_script bodies (and optional session trends) from the browser payload."""
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
    / stutter blobs bloat bootstrap (~1 MB for 600 points) without adding fidelity.
    """
    comp = snap.get("comparison") or {}
    cpu_c = comp.get("cpu") or {}
    gpu_c = comp.get("gpu") or {}
    mem_c = comp.get("memory") or {}
    cpu = snap.get("cpu") or {}
    mem = snap.get("memory") or {}
    dgpu = (snap.get("gpu") or {}).get("discrete") or {}
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
_prev_net: dict[str, tuple] = {}
_prev_disk: tuple[int, int, float] | None = None
_prev_swap: tuple[int, int, float] | None = None
_prev_ctx: tuple[int, int, float] | None = None
_prev_gtt: tuple[int, float] | None = None
_gtt_high_streak: int = 0
_prev_vmstat: tuple[dict[str, int], float] | None = None
# Per-device busy_time samples (name -> (busy_ms, wall_ts)); never sum optical+NVMe.
_prev_disk_busy: dict[str, tuple[int, float]] | None = None
_prev_cpu_stat: tuple[int, int, float] | None = None
# RAPL package energy (µJ, wall time) → watts between samples
_prev_cpu_rapl: tuple[int, float] | None = None
_cpu_power_cache: tuple[float, float | None] = (0.0, None)
_sensors_cache: tuple[float, dict] = (0.0, {})
_rate_smooth: dict[str, float] = {}
_proc_stats_cache: tuple[float, int, int] = (0.0, 0, 0)
_psi_cache: dict[str, tuple[float, dict | None]] = {}
_tuning_ctx_cache: tuple[float, dict] = (0.0, {})
_PROC_STATS_TTL = 3.0
_TUNING_CTX_TTL = 5.0

# Sampler liveness — freeze-on-resume used to leave the UI on the last sample forever.
# generation bumps abandon a stuck tick thread; watchdog starts a fresh loop.
_sampler_gen = 0
_sampler_last_ok_mono = 0.0
_sampler_last_ok_wall = 0.0
_sampler_stalls = 0
_sampler_last_reason = ""
_sampler_ready = threading.Event()
SAMPLER_STALL_SEC = 8.0
# Wall advanced much more than monotonic → suspend/resume (or a large NTP step).
WALL_JUMP_SEC = 2.5

VRAM_PEAK_GBPS = 800.0
# PCIe 4.0 x16 one-way theoretical payload ≈ 31.5 GB/s
PCIE_PEAK_GBPS = 31.5
MEMORY_CACHE = data_dir() / ".memory_cache.json"


def load_memory_spec() -> dict:
    spec = None
    if MEMORY_CACHE.exists():
        try:
            spec = json.loads(MEMORY_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            spec = None
    if not spec:
        spec = infer_fallback()
        try:
            MEMORY_CACHE.write_text(json.dumps(spec, indent=2))
        except OSError:
            pass
    return enrich_memory_spec(spec)


_mem_spec: dict = {}
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


def read_int(path: Path, scale: float = 1.0) -> int | None:
    try:
        return int(float(path.read_text().strip()) / scale)
    except (OSError, ValueError):
        return None


def sanitize_pct(val: int | float | None, *, max_valid: float = 100.0) -> float | None:
    """Drop amdgpu sentinel/overflow reads (e.g. 65535) from percent metrics."""
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v < 0 or v > max_valid:
        return None
    return round(v, 1)


def read_float(path: Path) -> float | None:
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_str(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


_gpu_spec: dict = {}
_gpu_peak_by_game: dict[str, float] = {}


def gpu_hwmon(base: Path) -> Path | None:
    for p in sorted(base.glob("hwmon/hwmon*")):
        if (p / "temp1_input").exists():
            return p
    return None


def ema_rate(key: str, raw: float, *, alpha: float = 0.35, cap: float | None = None) -> float:
    if cap is not None:
        raw = min(max(raw, 0.0), cap)
    prev = _rate_smooth.get(key)
    if prev is None:
        _rate_smooth[key] = raw
        return raw
    val = prev * (1 - alpha) + raw * alpha
    _rate_smooth[key] = val
    return val


def read_gpu_power_w(base: Path, sens: dict, sensor_prefix: str) -> float | None:
    """Read GPU board power (PPT) in watts — sysfs uses microwatts, sensors-json uses watts."""
    hw = gpu_hwmon(base)
    sysfs_w: float | None = None
    if hw:
        for fname in ("power1_average", "power1_input"):
            raw = read_float(hw / fname)
            if raw is not None and raw > 0:
                w = raw / 1_000_000
                if w >= 0.5:
                    sysfs_w = w
                    break
    sensor_w: float | None = None
    for k, v in sens.items():
        if sensor_prefix not in k or not isinstance(v, (int, float)):
            continue
        kl = k.lower()
        if "ppt" in kl and ("power1_average" in kl or "power1_input" in kl):
            sensor_w = float(v)
            break
    if sysfs_w is not None and sensor_w is not None:
        return round(max(sysfs_w, sensor_w), 1)
    pick = sysfs_w if sysfs_w is not None else sensor_w
    return round(pick, 1) if pick is not None else None


def read_cpu_power_w() -> float | None:
    """CPU package power in watts.

    Prefer RAPL/powercap energy deltas (``intel-rapl`` ABI — also used on many AMD
    kernels). ``energy_uj`` is often root-only; when unreadable we try hwmon chips
    that are not amdgpu (zenpower / fam15h_power / package).

    Result is cached ~0.4s so multiple callers per tick share one RAPL sample.
    """
    global _prev_cpu_rapl, _cpu_power_cache
    now = time.time()
    if now - _cpu_power_cache[0] < 0.4:
        return _cpu_power_cache[1]

    result: float | None = None
    powercap = Path("/sys/class/powercap")
    package_paths: list[Path] = []
    if powercap.is_dir():
        for domain in sorted(powercap.glob("intel-rapl:*")):
            # Skip core subdomains (intel-rapl:0:0)
            rest = domain.name[len("intel-rapl:") :]
            if ":" in rest:
                continue
            name_f = domain / "name"
            energy_f = domain / "energy_uj"
            if not energy_f.is_file():
                continue
            try:
                dname = name_f.read_text().strip() if name_f.is_file() else ""
            except OSError:
                dname = ""
            # Prefer package-* domains
            if dname and not dname.startswith("package") and "package" not in dname.lower():
                continue
            package_paths.append(domain)
        if not package_paths:
            for domain in sorted(powercap.glob("intel-rapl:*")):
                rest = domain.name[len("intel-rapl:") :]
                if ":" in rest:
                    continue
                if (domain / "energy_uj").is_file():
                    package_paths.append(domain)
                    break
    for domain in package_paths:
        energy_f = domain / "energy_uj"
        try:
            uj = int(energy_f.read_text().strip())
        except (OSError, ValueError):
            continue
        prev = _prev_cpu_rapl
        _prev_cpu_rapl = (uj, now)
        if prev:
            duj = uj - prev[0]
            dt = now - prev[1]
            if duj >= 0 and dt >= 0.25:
                watts = (duj / 1_000_000.0) / dt
                if 0.5 <= watts < 500:
                    result = round(watts, 1)
        break

    if result is None:
        try:
            for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
                try:
                    name = (hw / "name").read_text().strip().lower()
                except OSError:
                    continue
                if name.startswith(("amdgpu", "nvme", "iwlwifi", "enp")) or name in (
                    "amdgpu",
                    "system76_io",
                ):
                    continue
                if not any(
                    x in name for x in ("zen", "fam15", "power", "cpu", "core", "k10", "energy")
                ):
                    continue
                for fname in ("power1_average", "power1_input", "power2_average", "power2_input"):
                    p = hw / fname
                    if not p.is_file():
                        continue
                    raw = read_float(p)
                    if raw is None or raw <= 0:
                        continue
                    w = raw / 1_000_000 if raw > 500 else raw
                    if 0.5 <= w < 500:
                        result = round(w, 1)
                        break
                if result is not None:
                    break
        except OSError:
            pass

    _cpu_power_cache = (now, result)
    return result


def parse_sensors() -> dict:
    global _sensors_cache
    now = time.time()
    if now - _sensors_cache[0] < 2.0:
        return _sensors_cache[1]
    out: dict[str, float | int | None] = {}
    try:
        raw = subprocess.check_output(["sensors", "-j"], text=True, timeout=2)
        data = json.loads(raw)
        amdgpu_names = {"edge": "temp1_input", "junction": "temp2_input", "mem": "temp3_input"}
        for chip, vals in data.items():
            for key, v in vals.items():
                if not isinstance(v, dict):
                    continue
                label = f"{chip}:{key}"
                if chip.startswith("amdgpu") and key in amdgpu_names:
                    tval = v.get(amdgpu_names[key])
                    if tval is not None:
                        out[f"{chip}:{key}"] = round(tval, 1)
                for field, suffix in (
                    ("temp1_input", "c"),
                    ("temp2_input", "c"),
                    ("temp3_input", "c"),
                    ("temp4_input", "c"),
                    ("temp5_input", "c"),
                    ("fan1_input", "rpm"),
                    ("fan2_input", "rpm"),
                    ("fan1", "rpm"),
                    ("power1_average", "w"),
                    ("power1_input", "w"),
                    ("in0_input", "v"),
                ):
                    val = v.get(field)
                    if val is None:
                        continue
                    k = label if field.startswith("temp") else f"{label}:{field}"
                    if suffix == "w" and isinstance(val, (int, float)):
                        # sensors-json: watts; sysfs-style dumps: microwatts
                        out[k] = round(val / 1_000_000, 1) if val > 50_000 else round(val, 1)
                    elif suffix == "v":
                        out[k] = round(val, 3)
                    else:
                        out[k] = round(val, 1) if isinstance(val, float) else val
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass
    _sensors_cache = (now, out)
    return out


def psi_read(kind: str) -> dict | None:
    now = time.time()
    cached = _psi_cache.get(kind)
    if cached and now - cached[0] < 1.0:
        return cached[1]
    path = Path(f"/proc/pressure/{kind}")
    if not path.exists():
        _psi_cache[kind] = (now, None)
        return None
    try:
        text = path.read_text()
        m = re.search(r"some avg10=([\d.]+) avg60=([\d.]+) avg300=([\d.]+)", text)
        if not m:
            _psi_cache[kind] = (now, None)
            return None
        result = {
            "avg10": float(m.group(1)),
            "avg60": float(m.group(2)),
            "avg300": float(m.group(3)),
        }
        _psi_cache[kind] = (now, result)
        return result
    except OSError:
        _psi_cache[kind] = (now, None)
        return None


def _proc_stats() -> tuple[int, int]:
    """Process + thread counts (cached — full walk is ~20ms on this rig)."""
    global _proc_stats_cache
    now = time.time()
    if now - _proc_stats_cache[0] < _PROC_STATS_TTL:
        return _proc_stats_cache[1], _proc_stats_cache[2]
    procs = len(psutil.pids())
    threads = 0
    for proc in psutil.process_iter(["num_threads"]):
        try:
            threads += proc.info["num_threads"] or 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _proc_stats_cache = (now, procs, threads)
    return procs, threads


def swap_rates() -> dict:
    global _prev_swap
    now = time.time()
    sw = psutil.swap_memory()
    try:
        sin = sw.sin  # type: ignore[attr-defined]
        sout = sw.sout  # type: ignore[attr-defined]
    except AttributeError:
        return {"in_kbps": 0, "out_kbps": 0}
    prev = _prev_swap
    _prev_swap = (sin, sout, now)
    if not prev:
        return {"in_kbps": 0, "out_kbps": 0}
    dt = now - prev[2]
    if dt <= 0:
        return {"in_kbps": 0, "out_kbps": 0}
    raw_in = (sin - prev[0]) / dt / 1024
    raw_out = (sout - prev[1]) / dt / 1024
    if dt < 0.5:
        raw_in = raw_out = 0
    return {
        "in_kbps": round(ema_rate("swap:in", raw_in, cap=2_000_000), 1),
        "out_kbps": round(ema_rate("swap:out", raw_out, cap=2_000_000), 1),
    }


def ctx_rates() -> dict:
    global _prev_ctx
    now = time.time()
    st = psutil.cpu_stats()
    prev = _prev_ctx
    _prev_ctx = (st.ctx_switches, st.interrupts, now)
    if not prev:
        return {"ctx_per_s": 0, "intr_per_s": 0}
    dt = now - prev[2]
    if dt <= 0:
        return {"ctx_per_s": 0, "intr_per_s": 0}
    return {
        "ctx_per_s": int((st.ctx_switches - prev[0]) / dt),
        "intr_per_s": int((st.interrupts - prev[1]) / dt),
    }


def read_dpm_active_mhz(path: Path) -> int | None:
    text = read_str(path)
    if not text:
        return None
    for line in text.splitlines():
        if "*" in line:
            m = re.search(r"(\d+)\s*Mhz", line, re.I)
            if m:
                return int(m.group(1))
    return None


def gtt_rates(base: Path) -> dict:
    global _prev_gtt, _gtt_high_streak
    now = time.time()
    used = read_int(base / "mem_info_gtt_used")
    total = read_int(base / "mem_info_gtt_total")
    prev = _prev_gtt
    _prev_gtt = (used or 0, now)
    rate_mbps = 0.0
    if prev and used is not None and now > prev[1]:
        dt = now - prev[1]
        if dt >= 0.5:
            raw = abs(used - prev[0]) / dt / 1024**2
            rate_mbps = round(ema_rate("gtt:mbps", raw, cap=20_000), 2)
    if rate_mbps > 50:
        _gtt_high_streak += 1
    else:
        _gtt_high_streak = 0
    return {
        "used_mb": round(used / 1024**2, 1) if used else None,
        "total_mb": round(total / 1024**2, 1) if total else None,
        "pct": round(100 * used / total, 1) if used and total else None,
        "rate_mbps": rate_mbps,
        "sustained_high": _gtt_high_streak >= 3,
        "high_streak": _gtt_high_streak,
    }


def vmstat_rates() -> dict:
    global _prev_vmstat
    now = time.time()
    keys = ("pgfault", "pgmajfault", "workingset_refault_file", "workingset_refault_anon")
    cur: dict[str, int] = {}
    try:
        for line in Path("/proc/vmstat").read_text().splitlines():
            k, v = line.split(maxsplit=1)
            if k in keys:
                cur[k] = int(v)
    except OSError:
        return {
            "pgfault_per_s": 0,
            "pgmajfault_per_s": 0,
            "refault_file_per_s": 0,
            "refault_anon_per_s": 0,
        }
    prev = _prev_vmstat
    _prev_vmstat = (cur, now)
    if not prev:
        return {
            "pgfault_per_s": 0,
            "pgmajfault_per_s": 0,
            "refault_file_per_s": 0,
            "refault_anon_per_s": 0,
        }
    dt = now - prev[1]
    if dt <= 0:
        return {
            "pgfault_per_s": 0,
            "pgmajfault_per_s": 0,
            "refault_file_per_s": 0,
            "refault_anon_per_s": 0,
        }
    if dt < 0.5:
        return {
            "pgfault_per_s": int(_rate_smooth.get("vmstat:pgfault", 0)),
            "pgmajfault_per_s": int(_rate_smooth.get("vmstat:pgmajfault", 0)),
            "refault_file_per_s": int(_rate_smooth.get("vmstat:refault_file", 0)),
            "refault_anon_per_s": int(_rate_smooth.get("vmstat:refault_anon", 0)),
        }
    return {
        "pgfault_per_s": int(
            ema_rate(
                "vmstat:pgfault",
                (cur.get("pgfault", 0) - prev[0].get("pgfault", 0)) / dt,
                cap=80_000,
            )
        ),
        "pgmajfault_per_s": int(
            ema_rate(
                "vmstat:pgmajfault",
                (cur.get("pgmajfault", 0) - prev[0].get("pgmajfault", 0)) / dt,
                cap=10_000,
            )
        ),
        "refault_file_per_s": int(
            ema_rate(
                "vmstat:refault_file",
                (cur.get("workingset_refault_file", 0) - prev[0].get("workingset_refault_file", 0))
                / dt,
                cap=50_000,
            )
        ),
        "refault_anon_per_s": int(
            ema_rate(
                "vmstat:refault_anon",
                (cur.get("workingset_refault_anon", 0) - prev[0].get("workingset_refault_anon", 0))
                / dt,
                cap=50_000,
            )
        ),
    }


def vram_peak_gbps() -> float:
    return float(_gpu_spec.get("vram_peak_gbps") or VRAM_PEAK_GBPS)


def _engine_pct(metrics_val: int | None, sysfs_fallback: int | None) -> float | None:
    val = metrics_val if metrics_val is not None else sysfs_fallback
    return round(float(val), 1) if val is not None else None


def gpu_stats(base: Path, label: str, sensor_prefix: str, *, track_gtt: bool = True) -> dict:
    hw = gpu_hwmon(base)
    sens = parse_sensors()
    vram_used = read_int(base / "mem_info_vram_used", 1024**2)
    vram_total = read_int(base / "mem_info_vram_total", 1024**2)
    busy = sanitize_pct(read_int(base / "gpu_busy_percent"))
    mem_busy = sanitize_pct(read_int(base / "mem_busy_percent"))
    temp = read_int(hw / "temp1_input", 1000) if hw else None
    power_w = read_gpu_power_w(base, sens, sensor_prefix)
    fan = read_int(hw / "fan1_input") if hw else None
    gfx_mhz = read_dpm_active_mhz(base / "pp_dpm_sclk")
    mclk_mhz = read_dpm_active_mhz(base / "pp_dpm_mclk")
    pcie = read_str(base / "pp_dpm_pcie")
    pcie_active = None
    if pcie:
        for line in pcie.splitlines():
            if "*" in line:
                pcie_active = line.strip()
                break
    link_speed = read_str(base / "current_link_speed")
    link_width = read_int(base / "current_link_width")
    gtt = gtt_rates(base) if track_gtt and base.resolve() == gpu_device_path().resolve() else {}
    peak = vram_peak_gbps()
    vram_est_gbps = round((mem_busy or 0) * peak / 100, 1) if mem_busy is not None else None
    pcie_est_gbps = round(min(gtt.get("rate_mbps", 0) / 1024, PCIE_PEAK_GBPS), 2) if gtt else None
    junction = mem_temp = None
    for k, v in sens.items():
        if sensor_prefix not in k:
            continue
        kl = k.lower()
        if k.endswith(":junction") or (":junction:" in kl):
            junction = v
        elif k.endswith(":mem") or (":mem:" in kl and "temp" in kl):
            mem_temp = v
        elif junction is None and "junction" in kl and "temp" in kl:
            junction = v
        elif mem_temp is None and kl.endswith(":mem"):
            mem_temp = v
    if junction is None and hw:
        junction = read_int(hw / "temp2_input", 1000)
    if mem_temp is None and hw:
        mem_temp = read_int(hw / "temp3_input", 1000)
    engine_raw = read_gpu_engines(base) or {}
    engines = [
        {
            "id": "gfx",
            "label": "Shaders",
            "pct": _engine_pct(engine_raw.get("gfx"), busy),
        },
        {
            "id": "vram",
            "label": "Memory bus",
            "pct": _engine_pct(engine_raw.get("vram"), mem_busy),
        },
        {
            "id": "mm",
            "label": "Video",
            "pct": _engine_pct(engine_raw.get("mm"), None),
        },
    ]
    return {
        "label": label,
        "busy_pct": busy,
        "mem_busy_pct": mem_busy,
        "engines": engines,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
        "vram_pct": round(100 * vram_used / vram_total, 1) if vram_used and vram_total else None,
        "temp_c": temp,
        "junction_c": junction,
        "mem_temp_c": mem_temp,
        "power_w": power_w,
        "fan_rpm": fan,
        "gfx_mhz": gfx_mhz,
        "mclk_mhz": mclk_mhz,
        "pcie_active": pcie_active,
        "pcie_link": f"{link_speed or '?'} x{link_width or '?'}",
        "vram_est_gbps": vram_est_gbps,
        "vram_peak_gbps": peak,
        "pcie_est_gbps": pcie_est_gbps,
        "pcie_peak_gbps": PCIE_PEAK_GBPS,
        "gtt": gtt,
    }


def sensor_wall(dgpu: dict | None = None, igpu: dict | None = None) -> list[dict]:
    """Extended telemetry tiles for the dashboard."""
    sens = parse_sensors()
    du = psutil.disk_usage("/")
    uptime_s = int(float(open("/proc/uptime").read().split()[0]))
    procs, threads = _proc_stats()
    freq = psutil.cpu_freq()
    sw = swap_rates()
    ctx = ctx_rates()
    psi_cpu = psi_read("cpu")
    psi_mem = psi_read("memory")
    psi_io = psi_read("io")

    def pick(*keys, default=None, match_all: bool = False):
        for sk, sv in sens.items():
            sl = sk.lower()
            if match_all:
                if all(k.lower() in sl for k in keys):
                    return sv
            else:
                for k in keys:
                    if k.lower() in sl:
                        return sv
        return default

    vm = psutil.virtual_memory()
    load1, _, _ = os.getloadavg()
    dgpu_prefix = gpu_sensor_prefix()
    igpu_prefix = igpu_sensor_prefix()
    cpu_model = _static.get("cpu_model", "")
    dgpu = dgpu or gpu_stats(
        gpu_device_path(),
        _gpu_spec.get("label") or _gpu_spec.get("model", "GPU"),
        dgpu_prefix,
        track_gtt=False,
    )
    igpu = igpu or gpu_stats(
        igpu_device_path(),
        igpu_label(cpu_model),
        igpu_prefix,
        track_gtt=False,
    )

    nvme_tiles = nvme_sensor_tiles(sens, _static.get("storage"))
    tiles = [
        *nvme_tiles,
        {"id": "nic_phy", "label": "NIC PHY", "value": pick("PHY"), "unit": "°C", "kind": "temp"},
        {"id": "nic_mac", "label": "NIC MAC", "value": pick("MAC"), "unit": "°C", "kind": "temp"},
        {
            "id": "wifi",
            "label": "WiFi Radio",
            "value": pick("iwlwifi"),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "gpu_edge",
            "label": "GPU Edge",
            "value": dgpu.get("temp_c") or pick(dgpu_prefix, "edge", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "gpu_junc",
            "label": "GPU Junction",
            "value": dgpu.get("junction_c") or pick(dgpu_prefix, "junction", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "gpu_memt",
            "label": "VRAM Temp",
            "value": dgpu.get("mem_temp_c") or pick(dgpu_prefix, "mem", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "igpu_edge",
            "label": "iGPU Edge",
            "value": pick(igpu_prefix, "edge", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "cpu_pkg",
            "label": "CPU Package",
            "value": pick("k10temp", "Tctl"),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "ccd1",
            "label": "CCD1 Die",
            "value": pick("k10temp", "Tccd1"),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "ccd2",
            "label": "CCD2 Die",
            "value": pick("k10temp", "Tccd2"),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "cpu_mhz",
            "label": "CPU Avg CLK",
            "value": round(freq.current, 0) if freq else None,
            "unit": "MHz",
            "kind": "freq",
        },
        {
            "id": "gpu_clk",
            "label": "GPU GFX CLK",
            "value": dgpu.get("gfx_mhz"),
            "unit": "MHz",
            "kind": "freq",
        },
        {
            "id": "gpu_vram",
            "label": "VRAM Load",
            "value": dgpu.get("vram_pct"),
            "unit": "%",
            "kind": "pct",
        },
        {
            "id": "gpu_mbusy",
            "label": "VRAM Busy",
            "value": dgpu.get("mem_busy_pct"),
            "unit": "%",
            "kind": "pct",
        },
        {
            "id": "gpu_fan",
            "label": "GPU Fan",
            "value": dgpu.get("fan_rpm"),
            "unit": "rpm",
            "kind": "rate",
        },
        {
            "id": "gpu_pwr",
            "label": "GPU Power",
            "value": dgpu.get("power_w"),
            "unit": "W",
            "kind": "rate",
        },
        {
            "id": "cpu_pwr",
            "label": "CPU Power",
            "value": read_cpu_power_w(),
            "unit": "W",
            "kind": "rate",
        },
        {
            "id": "igpu_pwr",
            "label": "iGPU Power",
            "value": igpu.get("power_w"),
            "unit": "W",
            "kind": "rate",
        },
        {
            "id": "case_cpu",
            "label": "Case CPUF",
            "value": pick("system76_io", "CPUF", match_all=True),
            "unit": "rpm",
            "kind": "rate",
        },
        {
            "id": "case_int",
            "label": "Case INTF",
            "value": pick("system76_io", "INTF", match_all=True),
            "unit": "rpm",
            "kind": "rate",
        },
        {
            "id": "ram_avail",
            "label": "RAM Avail",
            "value": round(vm.available / 1024**3, 1),
            "unit": "GB",
            "kind": "info",
        },
        {"id": "load1", "label": "Load 1m", "value": round(load1, 2), "unit": "", "kind": "info"},
        {"id": "disk_use", "label": "Root Disk", "value": du.percent, "unit": "%", "kind": "pct"},
        {
            "id": "uptime",
            "label": "Uptime",
            "value": uptime_s // 3600,
            "unit": "hrs",
            "kind": "info",
        },
        {"id": "procs", "label": "Processes", "value": procs, "unit": "", "kind": "info"},
        {"id": "threads", "label": "Threads", "value": threads, "unit": "", "kind": "info"},
        {
            "id": "swap_in",
            "label": "Swap In",
            "value": sw["in_kbps"],
            "unit": "KB/s",
            "kind": "rate",
        },
        {
            "id": "swap_out",
            "label": "Swap Out",
            "value": sw["out_kbps"],
            "unit": "KB/s",
            "kind": "rate",
        },
        {
            "id": "ctx",
            "label": "Ctx Switches",
            "value": ctx["ctx_per_s"],
            "unit": "/s",
            "kind": "rate",
        },
        {
            "id": "intr",
            "label": "Interrupts",
            "value": ctx["intr_per_s"],
            "unit": "/s",
            "kind": "rate",
        },
        {
            "id": "psi_cpu",
            "label": "PSI CPU",
            "value": psi_cpu["avg10"] if psi_cpu else None,
            "unit": "%",
            "kind": "psi",
        },
        {
            "id": "psi_mem",
            "label": "PSI Memory",
            "value": psi_mem["avg10"] if psi_mem else None,
            "unit": "%",
            "kind": "psi",
        },
        {
            "id": "psi_io",
            "label": "PSI I/O",
            "value": psi_io["avg10"] if psi_io else None,
            "unit": "%",
            "kind": "psi",
        },
    ]
    return tiles


_NET_SKIP_PREFIXES = (
    "lo",
    "docker",
    "veth",
    "br-",
    "virbr",
    "vnet",
    "tun",
    "tap",
    "wg",
    "tailscale",
    "zt",
    "lxc",
    "cni",
    "flannel",
    "cali",
)


def _is_tracked_nic(name: str) -> bool:
    """Skip loopback and common virtual bridges so aggregate rates stay real."""
    if name == "lo":
        return False
    lower = name.lower()
    return not any(lower.startswith(p) for p in _NET_SKIP_PREFIXES)


def net_rates() -> dict:
    """Per-NIC and aggregate link throughput (Mbps) plus primary iface metadata."""
    global _prev_net
    now = time.time()
    rates: dict[str, dict] = {}
    counters = psutil.net_io_counters(pernic=True) or {}
    try:
        stats = psutil.net_if_stats() or {}
    except Exception:
        stats = {}

    for nic, c in counters.items():
        if not _is_tracked_nic(nic):
            continue
        st = stats.get(nic)
        is_up = bool(st.isup) if st else True
        speed = int(st.speed) if st and st.speed and st.speed > 0 else None
        prev = _prev_net.get(nic)
        down = 0.0
        up = 0.0
        err_in = 0.0
        err_out = 0.0
        if prev:
            dt = now - prev[2]
            if dt > 0:
                down = (c.bytes_recv - prev[0]) * 8 / dt / 1e6
                up = (c.bytes_sent - prev[1]) * 8 / dt / 1e6
                # prev slots 3–4 store cumulative errors when available
                if len(prev) >= 5:
                    err_in = max(0.0, (c.errin - prev[3]) / dt)
                    err_out = max(0.0, (c.errout - prev[4]) / dt)
        rates[nic] = {
            "down_mbps": round(max(0.0, down), 2),
            "up_mbps": round(max(0.0, up), 2),
            "is_up": is_up,
            "speed_mbps": speed,
            "err_in_ps": round(err_in, 2),
            "err_out_ps": round(err_out, 2),
        }
        _prev_net[nic] = (c.bytes_recv, c.bytes_sent, now, c.errin, c.errout)

    # Drop stale NICs that disappeared
    for stale in list(_prev_net.keys()):
        if stale not in rates and stale not in counters:
            _prev_net.pop(stale, None)

    down_total = round(sum(v["down_mbps"] for v in rates.values()), 2)
    up_total = round(sum(v["up_mbps"] for v in rates.values()), 2)

    # Primary = up interface with most combined traffic this tick, else fastest up link.
    primary = None
    if rates:
        up_nics = [n for n, v in rates.items() if v.get("is_up")]
        pool = up_nics or list(rates.keys())

        def _rank(n: str) -> tuple:
            v = rates[n]
            return (
                v["down_mbps"] + v["up_mbps"],
                v.get("speed_mbps") or 0,
            )

        primary = max(pool, key=_rank)

    primary_meta = rates.get(primary or "", {}) if primary else {}
    return {
        "per_nic": rates,
        "down_mbps": down_total,
        "up_mbps": up_total,
        "primary": primary,
        "primary_speed_mbps": primary_meta.get("speed_mbps"),
        "primary_up": bool(primary_meta.get("is_up")) if primary else False,
        "nic_count": len(rates),
        "up_count": sum(1 for v in rates.values() if v.get("is_up")),
    }


def cpu_iowait_pct() -> float:
    """Rolling CPU iowait % from /proc/stat (classic disk-wait signal)."""
    global _prev_cpu_stat
    now = time.time()
    try:
        line = Path("/proc/stat").read_text().splitlines()[0]
        parts = [int(x) for x in line.split()[1:]]
        if len(parts) < 5:
            return 0.0
        total = sum(parts[: min(len(parts), 10)])
        iowait = parts[4]
        prev = _prev_cpu_stat
        _prev_cpu_stat = (total, iowait, now)
        if not prev or now - prev[2] < 0.4:
            return 0.0
        dt_total = total - prev[0]
        dt_io = iowait - prev[1]
        if dt_total <= 0:
            return 0.0
        return round(dt_io / dt_total * 100.0, 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def _is_storage_disk(name: str) -> bool:
    """Whole-disk block devices that should drive the Live lab storage dial.

    Excludes optical (sr0), loop/zram, and partitions so busy% is not inflated by
    summing unrelated devices (classic cause of pegging at 100%).
    """
    n = (name or "").lower()
    if not n:
        return False
    if n.startswith(("loop", "ram", "zram", "fd", "sr", "cdrom", "dvd", "sr")):
        return False
    # Device-mapper often double-counts the underlying NVMe/SATA drive.
    if n.startswith("dm-") or n.startswith("md"):
        return False
    # Partitions: nvme0n1p1, sda1, vda2, mmcblk0p1
    if n.startswith("nvme") and "p" in n.split("n", 1)[-1]:
        return False
    if re.match(r"^(sd|vd|hd)[a-z]+\d+$", n):
        return False
    if n.startswith("mmcblk") and "p" in n:
        return False
    return True


def disk_rates() -> dict:
    """Disk throughput + busy%.

    Busy uses **max** of per-disk util among real storage (NVMe/SATA), not the
    system-wide sum of ``busy_time``. Aggregating all devices includes optical
    (``sr0``) and multi-disk sums that clamp at 100% even when SSDs are idle.
    """
    global _prev_disk, _prev_disk_busy
    now = time.time()
    per = psutil.disk_io_counters(perdisk=True) or {}
    storage = {n: c for n, c in per.items() if _is_storage_disk(n)}
    # Throughput: storage whole disks only (not optical rips double-counting as "system busy")
    read_b = sum(getattr(c, "read_bytes", 0) or 0 for c in storage.values())
    write_b = sum(getattr(c, "write_bytes", 0) or 0 for c in storage.values())
    prev = _prev_disk
    _prev_disk = (read_b, write_b, now)

    busy_pct = 0.0
    busiest = None
    prev_busy = _prev_disk_busy or {}
    next_busy: dict[str, tuple[int, float]] = {}
    for name, c in storage.items():
        busy_ms = getattr(c, "busy_time", None)
        if busy_ms is None:
            continue
        next_busy[name] = (int(busy_ms), now)
        old = prev_busy.get(name)
        if not old:
            continue
        dtb = now - old[1]
        if dtb < 0.5:
            continue
        # busy_time is ms spent doing I/O; % = Δms / (Δs * 1000) * 100 = Δms / Δs / 10
        pct = min(100.0, (int(busy_ms) - old[0]) / dtb / 10.0)
        if pct >= busy_pct:
            busy_pct = pct
            busiest = name
    _prev_disk_busy = next_busy
    busy_pct = round(busy_pct, 1)

    if not prev:
        return {
            "read_mbps": 0,
            "write_mbps": 0,
            "busy_pct": busy_pct,
            "busy_device": busiest,
        }
    dt = now - prev[2]
    if dt <= 0:
        return {
            "read_mbps": 0,
            "write_mbps": 0,
            "busy_pct": busy_pct,
            "busy_device": busiest,
        }
    # Bytes → megabytes/s (UI labels "MB/s"). Do NOT *8 — that is megabits (network).
    return {
        "read_mbps": round((read_b - prev[0]) / dt / 1e6, 2),
        "write_mbps": round((write_b - prev[1]) / dt / 1e6, 2),
        "busy_pct": busy_pct,
        "busy_device": busiest,
    }


def memory_bandwidth(cpu_pct: float = 0.0, game_cpu_pct: float = 0.0) -> dict:
    vm = psutil.virtual_memory()
    sw = swap_rates()
    vmstat = vmstat_rates()
    psi_mem = psi_read("memory")
    psi_io = psi_read("io")

    # Bytes implied by faults — useful for stutter, NOT total DRAM throughput.
    fault_proxy_gbps = round(
        (vmstat["pgmajfault_per_s"] * 65536 + vmstat["pgfault_per_s"] * 4096) / 1e9, 2
    )
    refault_proxy_gbps = round(
        (vmstat["refault_file_per_s"] + vmstat["refault_anon_per_s"]) * 4096 / 1e9, 2
    )
    dram_fault_gbps = round(fault_proxy_gbps + refault_proxy_gbps, 2)

    psi10 = psi_mem["avg10"] if psi_mem else 0
    ram_pct = vm.percent
    workload_cpu = max(float(cpu_pct or 0), float(game_cpu_pct or 0))
    dram_peak = _mem_spec.get("peak_gbps") or 89.6

    # Workload demand model — no perf counter on Linux without root.
    # Blends CPU load, RAM residency, PSI stall, and page-fault churn.
    churn_pct = min(22.0, vmstat["pgfault_per_s"] / 1400.0)
    demand_pct = min(
        100.0,
        (psi10 / 100.0) * 50.0
        + (workload_cpu / 100.0) * 40.0
        + (ram_pct / 100.0) * 15.0
        + churn_pct
        + min(12.0, dram_fault_gbps / dram_peak * 100),
    )
    if workload_cpu > 12 or ram_pct > 45:
        demand_pct = max(demand_pct, workload_cpu * 0.28 + ram_pct * 0.10)
    dram_util_pct = round(demand_pct, 1)
    dram_est_gbps = round(dram_peak * demand_pct / 100.0, 2)

    return {
        "dram_peak_gbps": dram_peak,
        "dram_est_gbps": dram_est_gbps,
        "dram_method": "workload",
        "spec_label": _mem_spec.get("label"),
        "spec_confidence": _mem_spec.get("confidence"),
        "dram_util_pct": dram_util_pct,
        "dram_fault_gbps": dram_fault_gbps,
        "fault_proxy_gbps": fault_proxy_gbps,
        "refault_proxy_gbps": refault_proxy_gbps,
        "pgfault_per_s": vmstat["pgfault_per_s"],
        "pgmajfault_per_s": vmstat["pgmajfault_per_s"],
        "psi_avg10": psi10,
        "psi_avg60": psi_mem["avg60"] if psi_mem else None,
        "psi_io_avg10": psi_io["avg10"] if psi_io else None,
        "swap_in_kbps": sw["in_kbps"],
        "swap_out_kbps": sw["out_kbps"],
        "cached_gb": round(vm.buffers / 1024**3 + getattr(vm, "cached", 0) / 1024**3, 2),
        "active_gb": round(getattr(vm, "active", vm.used) / 1024**3, 2),
    }


def tools_status() -> dict:
    """Tools Pulse actually uses — data sources that feed metrics, plus one thermal helper.

    Removed from the old shopping list: nvtop, radeontop, turbostat, perf, iotop, nethogs.
    Those never improved dashboard data (Pulse already samples /sys and /proc).
    """
    smart = probe_nvme_smart()
    sensors_ok = bool(shutil.which("sensors"))
    dmidecode_ok = bool(shutil.which("dmidecode"))
    corectrl_ok = bool(shutil.which("corectrl"))

    mem_src = (_mem_spec or {}).get("source") or ""
    mem_feeding = mem_src in ("dmidecode", "dmidecode-cache", "cache") or bool(
        (_mem_spec or {}).get("sticks") and mem_src not in ("", "inferred", "estimated")
    )
    # Also treat high-confidence non-inferred labels as fed when cache came from dmidecode
    if (_mem_spec or {}).get("confidence") in ("exact", "high") and dmidecode_ok:
        mem_feeding = True
    if mem_src == "dmidecode":
        mem_feeding = True

    data_sources = [
        {
            "id": "sensors",
            "bin": "sensors",
            "pkg": "lm-sensors",
            "role": "data",
            "note": "CPU/GPU/NVMe temperatures, fans, PPT — primary sensor feed",
            "installed": sensors_ok,
            "feeding": sensors_ok,
            "detail": "live · sensors -j every sample" if sensors_ok else "install to unlock sensor strip temps",
        },
        {
            "id": "smartctl",
            "bin": "smartctl",
            "pkg": "smartmontools",  # apt package name (UI title); binary is smartctl
            "role": "data",
            "note": "NVMe wear %, spare capacity, TB written, media errors",
            "installed": bool(smart.get("installed")),
            "feeding": bool(smart.get("readable")),
            "detail": smart.get("message") or "",
            "setup": (
                "enable-nvme-smart"
                if smart.get("installed") and not smart.get("readable")
                else None
            ),
        },
        {
            "id": "dmidecode",
            "bin": "dmidecode",
            "pkg": "dmidecode",
            "role": "data",
            "note": "Exact RAM SPD / configured MHz (one-time sudo probe)",
            "installed": dmidecode_ok,
            "feeding": bool(mem_feeding),
            "detail": (
                f"memory source: {mem_src or 'inferred'}"
                if dmidecode_ok
                else "install + sudo probe_memory.py for exact kit speed"
            ),
        },
    ]
    helpers = [
        {
            "id": "corectrl",
            "bin": "corectrl",
            "pkg": "corectrl",
            "role": "helper",
            "note": "AMD fan curves / power — opened by GPU thermal Fix when installed",
            "installed": corectrl_ok,
            "feeding": False,
            "detail": (
                "ready · one-click thermal Fix can launch it"
                if corectrl_ok
                else "optional for AMD fan curves"
            ),
        },
    ]
    # Backward-compatible flat list for older UI bits
    recommended = []
    for t in data_sources + helpers:
        recommended.append(
            {
                "bin": t["bin"],
                "pkg": t["pkg"],
                "note": t["note"],
                "installed": t["installed"],
                "feeding": t.get("feeding", False),
                "role": t.get("role", "data"),
                "detail": t.get("detail", ""),
                "setup": t.get("setup"),
                "id": t.get("id", t["bin"]),
            }
        )
    return {
        "sensors": sensors_ok,
        "dmidecode": dmidecode_ok,
        "smartctl": bool(smart.get("installed")),
        "smartctl_feeding": bool(smart.get("readable")),
        "nvtop": False,  # removed from recommendations; keep key stable
        "corectrl": corectrl_ok,
        "data_sources": data_sources,
        "helpers": helpers,
        "recommended": recommended,
        "smart": {
            "readable": bool(smart.get("readable")),
            "permission_error": bool(smart.get("permission_error")),
            "drive_count": len(smart.get("drives") or {}),
            "message": smart.get("message"),
        },
    }


def _migrate_tuning_history() -> None:
    """Normalize legacy game IDs and merge duplicate games_seen timestamps."""
    from games import LEGACY_GAME_IDS, normalize_game_id

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
                    "fix_script": h.get("fix_script"),
                    "has_fix_script": h.get("has_fix_script"),
                    "requires_root": h.get("requires_root"),
                    "fixable": h.get("fixable"),
                    "games": h.get("games", ["all"]),
                    "bucket": h.get("bucket"),
                    "last_seen": now,
                    "count": hit.get("count", 1) + 1,
                    "active": True,
                    "condition_live": True,
                }
            )
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
    # 15s live-hold so badges/lists do not flap every 1 Hz tick.
    live_ids = apply_live_hysteresis(_tuning_history, active_ids, now)
    for item in _tuning_history:
        item["active"] = True
    if seed_clear_timers(
        _tuning_history,
        live_ids,  # treat held-live as still active for clear-timer seeding
        resolved_ids,
        suppressed_ids,
        now,
    ):
        _tuning_dirty = True

    def _fresh_active_ids() -> set[str]:
        invalidate_diagnostics_cache()
        base = snap if snap is not None else _latest_full or {}
        return {h["insight_id"] for h in tuning_hints(base) if h.get("insight_id")}

    if tick_auto_resolve(
        _tuning_history,
        live_ids,  # hysteresis-aware active set
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
            "gpu_model": _gpu_spec.get("model", ""),
            "gpu_card": drm["discrete"].get("card", "card1"),
            "gpu_sysfs": str(dpath),
            "gpu_sensor": f"amdgpu-pci-{gpu_sensor_prefix()}",
        }
    )
    _tuning_ctx_cache = (now, ctx)
    return dict(ctx)


def tuning_hints(snap: dict) -> list[dict]:
    ctx = _tuning_context()
    ctx["gpu_model"] = _gpu_spec.get("model", "")
    return build_tuning_hints(snap, _mem_spec, ctx)


def collect_metrics() -> dict:
    # interval=None: delta since last cpu_percent (primed in sampler) — avoids ~80ms block/tick.
    cpu_pct = psutil.cpu_percent(interval=None, percpu=True)
    freqs = psutil.cpu_freq(percpu=True)
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
        _gpu_spec.get("label") or _gpu_spec.get("model", "GPU"),
        gpu_sensor_prefix(),
    )
    global _gpu_peak_by_game
    thermal_profile = _gpu_spec.get("thermal_profile") or profile_for_model(
        _gpu_spec.get("model", "")
    )
    dgpu["thermal_profile"] = thermal_profile
    gfx_mhz = dgpu.get("gfx_mhz")
    active_gid = game_totals.get("game_id") if game_totals.get("running") else None
    game_peak_mhz = 0.0
    if active_gid:
        busy_pct = dgpu.get("busy_pct") or 0
        if gfx_mhz and busy_pct >= 25:
            prev = _gpu_peak_by_game.get(active_gid, 0.0)
            _gpu_peak_by_game[active_gid] = max(prev, float(gfx_mhz))
        game_peak_mhz = _gpu_peak_by_game.get(active_gid, 0.0)
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
            "installed_gb": _mem_spec.get("total_gb"),
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
                "vram_busy_pct": dgpu.get("mem_busy_pct"),
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
    with _lock:
        attach_stutter(snap, _history)
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
    history = update_tuning_history(active_hints, running_ids, snap)
    views = build_issue_views(active_hints, history, running_ids, games_state)
    snap["tuning_active"] = active_hints
    snap["tuning"] = views["overall"]
    snap["issues_by_game"] = views["by_game"]
    tiles = snap["sensors"]
    snap["sensor_health"] = {
        "total": len(tiles),
        "ok": sum(1 for t in tiles if t.get("value") is not None),
        "missing": [t["label"] for t in tiles if t.get("value") is None],
    }
    snap["comparison"] = hardware_comparison(
        _static.get("cpu_model", ""),
        _static.get("gpu_model", "Discrete GPU"),
        _mem_spec,
        snap,
        gpu_info=_static.get("gpu") or _gpu_spec,
        machine=_static.get("machine", ""),
        hostname=_static.get("hostname", ""),
    )
    snap["game_performance"] = tick_game_performance(snap, save_session=save_game_session)
    return snap


def cpu_temps() -> dict:
    out = {"package": None, "ccd": []}
    sens = parse_sensors()
    for k, v in sens.items():
        if "k10temp" in k and ("Tctl" in k or "Tdie" in k):
            out["package"] = v
        elif "Tccd" in k:
            out["ccd"].append(v)
    return out


def reprime_rate_baselines() -> None:
    """Drop delta baselines so post-resume rates are not averaged over hours of sleep."""
    global _prev_net, _prev_disk, _prev_swap, _prev_ctx, _prev_gtt
    global _prev_vmstat, _prev_disk_busy, _prev_cpu_stat, _prev_cpu_rapl, _sensors_cache
    _prev_net = {}
    _prev_disk = None
    _prev_swap = None
    _prev_ctx = None
    _prev_gtt = None
    _prev_vmstat = None
    _prev_disk_busy = None
    _prev_cpu_stat = None
    _prev_cpu_rapl = None
    _sensors_cache = (0.0, {})


def _prime_rate_counters() -> None:
    """Establish fresh counter baselines (zeros on next-tick deltas)."""
    try:
        net_rates()
        disk_rates()
        swap_rates()
        ctx_rates()
        gtt_rates(gpu_device_path())
        vmstat_rates()
        psutil.cpu_percent(interval=None, percpu=True)
        prime_game_cpu()
    except Exception as exc:
        print(f"Cosmic Pulse sampler: reprime failed: {exc}", flush=True)


def _mark_sample_ok() -> None:
    global _sampler_last_ok_mono, _sampler_last_ok_wall
    _sampler_last_ok_mono = time.monotonic()
    _sampler_last_ok_wall = time.time()


def sampler_status() -> dict:
    """Liveness for /api/metrics — client uses this to show Stale vs Online."""
    if not _sampler_last_ok_mono:
        return {
            "ok": False,
            "age_sec": None,
            "generation": _sampler_gen,
            "stalls": _sampler_stalls,
            "reason": _sampler_last_reason or "starting",
        }
    age = time.monotonic() - _sampler_last_ok_mono
    return {
        "ok": age < SAMPLER_STALL_SEC,
        "age_sec": round(age, 2),
        "generation": _sampler_gen,
        "stalls": _sampler_stalls,
        "reason": _sampler_last_reason or None,
    }


def _run_sampler_loop(my_gen: int, platform_last_refresh: float) -> None:
    """1 Hz sample loop for one generation. Abandoned gens exit without publishing."""
    global _history, _latest_full, _sampler_last_reason

    last_wall = time.time()
    last_mono = time.monotonic()

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

            _static["cosmic_theme"] = get_cosmic_theme()
            # Refresh tool feed status (cheap; smartctl itself is cached)
            _static["tools"] = tools_status()
            # Re-detect running DE rarely — session hops are uncommon
            now_plat = time.time()
            if now_plat - platform_last_refresh > 900:  # 15 min
                try:
                    _static["platform"] = platform_identity()
                    platform_last_refresh = now_plat
                except Exception:
                    pass

            snap = collect_metrics()
            if my_gen != _sampler_gen:
                return
            with _lock:
                if my_gen != _sampler_gen:
                    return
                _latest_full = snap
                _history.append(slim_history_point(snap))
                if len(_history) > HISTORY_LEN:
                    _history.pop(0)
            _mark_sample_ok()
            if _sampler_last_reason in ("resume", "stall", "starting"):
                _sampler_last_reason = ""
            try:
                record_sample_maybe_prune(snap)
            except Exception as exc:
                print(f"Cosmic Pulse DB: sample write failed: {exc}", flush=True)
        except Exception as exc:
            print(f"Cosmic Pulse sampler: tick failed (will retry): {exc}", flush=True)
            import traceback

            traceback.print_exc()

        # Slice sleep so abandoned generations exit quickly and resume is noticed soon.
        for _ in range(10):
            if my_gen != _sampler_gen:
                return
            time.sleep(0.1)


def sampler():
    global _history, _latest_full, _static, _mem_spec, _gpu_spec, VRAM_PEAK_GBPS, _gpu_peak_by_game
    global _sampler_last_reason
    import hardware_probe as hp

    hp._drm_cache = None
    hp._storage_cache = None

    _mem_spec = load_memory_spec()
    _gpu_spec = detect_gpu_spec()
    _gpu_peak_by_game = {}
    VRAM_PEAK_GBPS = _gpu_spec["vram_peak_gbps"]
    load_tuning_log()
    discover_drm_cards()
    storage_drives = probe_storage()
    product = read_str(Path("/sys/class/dmi/id/product_name")) or "Unknown"
    product_ver = read_str(Path("/sys/class/dmi/id/product_version")) or ""
    sys_vendor = read_str(Path("/sys/class/dmi/id/sys_vendor")) or ""
    board_vendor = read_str(Path("/sys/class/dmi/id/board_vendor")) or ""
    board_name = read_str(Path("/sys/class/dmi/id/board_name")) or ""
    cpu_model = open("/proc/cpuinfo").read().split("model name\t: ", 1)[-1].split("\n", 1)[0]
    machine = f"{product} ({product_ver})" if product_ver else product
    host_platform = platform_identity()
    # Prefer chassis OEM (sys_vendor) so System76 Thelio is recognized reliably
    s76_vendor = sys_vendor or board_vendor or (host_platform.get("vendor") or {}).get("name") or ""
    platform_last_refresh = time.time()
    _static = {
        "hostname": os.uname().nodename,
        "machine": machine,
        "board_vendor": board_vendor,
        "board_name": board_name,
        "cpu_model": cpu_model,
        "storage": storage_drives,
        "threads": psutil.cpu_count(logical=True),
        "history_max_sec": HISTORY_LEN,
        "gpu_model": _gpu_spec.get("model", "Discrete GPU"),
        "gpu_thermal": (
            _gpu_spec.get("thermal_profile") or profile_for_model(_gpu_spec.get("model", ""))
        ),
        "gpu": _gpu_spec,
        "vram_peak_gbps": _gpu_spec.get("vram_peak_gbps", VRAM_PEAK_GBPS),
        "dram_peak_gbps": _mem_spec.get("peak_gbps", 89.6),
        "pcie_peak_gbps": PCIE_PEAK_GBPS,
        "memory": _mem_spec,
        "platform": host_platform,
        "rig": {
            "chassis": chassis_identity(machine, os.uname().nodename, s76_vendor),
            "cpu": cpu_identity(cpu_model),
            "gpu": _gpu_spec,
            "memory": memory_identity(_mem_spec),
            "storage": storage_drives,
        },
        "tools": tools_status(),
        "backlog": json.loads(BACKLOG_FILE.read_text()) if BACKLOG_FILE.exists() else [],
        "pulse_root": str(ROOT),
        "cosmic_theme": get_cosmic_theme(),
        "suppressed_insights": get_suppressed_insights(),
        "resolved_insights": get_resolved_insights(),
        "pulse_config": load_config(),
        "games_catalog": build_games_catalog(),
        "legacy_game_ids": dict(LEGACY_GAME_IDS),
    }
    _prime_rate_counters()
    # One blocking prime so first live % is meaningful (only at process start).
    try:
        psutil.cpu_percent(interval=0.1, percpu=True)
    except Exception:
        pass
    _sampler_last_reason = "starting"
    _sampler_ready.set()
    _run_sampler_loop(_sampler_gen, platform_last_refresh)


def sampler_watchdog() -> None:
    """Restart the sample loop if a tick blocks past SAMPLER_STALL_SEC (e.g. hung I/O after resume)."""
    global _sampler_gen, _sampler_stalls, _sampler_last_reason

    if not _sampler_ready.wait(timeout=45):
        print("Cosmic Pulse sampler: watchdog — sampler never became ready", flush=True)

    while True:
        time.sleep(2.0)
        if not _sampler_last_ok_mono:
            continue
        age = time.monotonic() - _sampler_last_ok_mono
        if age < SAMPLER_STALL_SEC:
            continue
        _sampler_stalls += 1
        _sampler_gen += 1
        _sampler_last_reason = "stall"
        print(
            f"Cosmic Pulse sampler: stalled {age:.1f}s — "
            f"restarting generation {_sampler_gen} (stalls={_sampler_stalls})",
            flush=True,
        )
        reprime_rate_baselines()
        _prime_rate_counters()
        t = threading.Thread(
            target=_run_sampler_loop,
            args=(_sampler_gen, time.time()),
            daemon=True,
            name=f"pulse-sampler-{_sampler_gen}",
        )
        t.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            data = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/assets/"):
            # Brand logos and other static assets (no path traversal)
            rel = path[len("/assets/") :].lstrip("/")
            asset_root = (ROOT / "assets").resolve()
            try:
                fp = (asset_root / rel).resolve()
            except OSError:
                fp = None
            under_assets = fp and (
                fp == asset_root or str(fp).startswith(str(asset_root) + os.sep)
            )
            if not under_assets or not fp.is_file():
                self.send_response(404)
                self.end_headers()
                return
            data = fp.read_bytes()
            ctype = "application/octet-stream"
            if fp.suffix == ".svg":
                ctype = "image/svg+xml"
            elif fp.suffix == ".png":
                ctype = "image/png"
            elif fp.suffix == ".jpg" or fp.suffix == ".jpeg":
                ctype = "image/jpeg"
            elif fp.suffix == ".webp":
                ctype = "image/webp"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/probe-memory":
            import subprocess as sp

            payload = {"ok": False, "message": "Run: sudo python3 probe_memory.py"}
            try:
                raw = sp.check_output(
                    ["sudo", "-n", "python3", str(ROOT / "probe_memory.py")],
                    text=True,
                    timeout=8,
                    stderr=sp.DEVNULL,
                )
                global _mem_spec
                _mem_spec = load_memory_spec()
                payload = {"ok": True, "memory": _mem_spec, "output": raw[-500:]}
            except (sp.SubprocessError, OSError):
                pass
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/metrics":
            bootstrap = (qs.get("bootstrap") or ["0"])[0] in ("1", "true", "yes")
            # Copy under lock only — never hold the lock across json.dumps (or config I/O).
            # Holding the lock for the full encode used to delay the sampler after resume.
            with _lock:
                # Bootstrap keeps last_session.trend once for instant game chart;
                # steady 1 Hz polls omit the ~64 KB series (client uses history /
                # /api/game-sessions instead).
                latest = latest_for_api(
                    _latest_full,
                    include_game_issues=bootstrap,
                    include_session_trend=bootstrap,
                )
                history_copy = list(_history) if bootstrap else None
                point = (
                    _history[-1]
                    if _history
                    else slim_history_point(_latest_full)
                )
                static_snap = _static
            # Fresh COSMIC tokens every poll (mtime-cached — free when unchanged).
            cosmic_theme = get_cosmic_theme()
            if static_snap is not None:
                static_snap["cosmic_theme"] = cosmic_theme
            samp = sampler_status()
            if bootstrap:
                body = {
                    "static": static_snap,
                    "latest": latest,
                    "history": history_copy,
                    "sampler": samp,
                    "theme": cosmic_theme,
                    "cosmic_theme": cosmic_theme,
                }
            else:
                body = {
                    "latest": latest,
                    "point": point,
                    "theme": cosmic_theme,
                    "cosmic_theme": cosmic_theme,
                    "resolved_insights": get_resolved_insights(),
                    "suppressed_insights": get_suppressed_insights(),
                    "sampler": samp,
                }
            payload = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif path == "/api/issues-by-game":
            with _lock:
                latest = latest_for_api(_latest_full)
                by_game = latest.get("issues_by_game") or {}
            self._json({"issues_by_game": by_game})
        elif path == "/api/fix-script":
            insight_id = (qs.get("insight_id") or [""])[0].strip()
            if not insight_id:
                self._json({"ok": False, "error": "insight_id required"}, status=400)
                return
            with _lock:
                script = fix_script_for_insight(
                    insight_id,
                    _latest_full,
                    _mem_spec,
                    history=_tuning_history,
                )
            self._json(
                {
                    "ok": bool(script),
                    "insight_id": insight_id,
                    "script": script,
                }
            )
        elif path == "/api/diagnostics":
            from rule_packs import evaluate_rule_packs, scan_findings_for_guidance

            force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
            # force starts background job — HTTP never waits on journalctl
            if force:
                request_diagnostics_scan()
            job = diagnostics_job_status()
            # Prefer last completed scan; never block the request thread.
            if job.get("has_result") and job.get("findings") is not None:
                diag = {
                    "scanned_at": job.get("scanned_at"),
                    "counts": job.get("counts") or {},
                    "findings": job.get("findings") or [],
                    "categories": [],
                    "pending": bool(job.get("running")),
                }
            else:
                diag = get_diagnostics(force=False)
            # Snapshot metrics under lock; evaluate outside so scans can't stall sampler.
            with _lock:
                full = _latest_full
                mem = _mem_spec
                gt = (full or {}).get("game_totals") or {}
                active = gt.get("game_id") or gt.get("appid")
                running = bool(gt.get("running"))
            ctx = system_context()
            _, emitted = evaluate_rule_packs(full or {}, mem, ctx)
            scan = scan_findings_for_guidance(
                diag.get("findings") or [],
                emitted,
                active_appid=str(active) if active else None,
                running=running,
            )
            primary = primary_finding(scan) or primary_finding(diag.get("findings") or [])
            diag = {
                **diag,
                "scan_findings": scan,
                "primary": primary,
                "job": {
                    "status": job.get("status"),
                    "running": bool(job.get("running")),
                    "ready": bool(job.get("has_result")),
                    "error": job.get("error"),
                },
            }
            self._json(diag)
        elif path == "/api/store":
            self._json(enrich_store_stats())
        elif path == "/api/rule-packs":
            from rule_packs import list_packs, list_rules

            qs = parse_qs(parsed.query)
            if (qs.get("view") or ["packs"])[0] == "rules":
                pack_id = (qs.get("pack") or [None])[0]
                q = (qs.get("q") or [None])[0]
                self._json(
                    {
                        "ok": True,
                        "rules": list_rules(pack_id=pack_id, q=q),
                        "packs": list_packs(include_disabled=True),
                    }
                )
            else:
                packs = list_packs(include_disabled=True)
                self._json(
                    {
                        "ok": True,
                        "packs": packs,
                        "enabled_count": sum(1 for p in packs if p.get("enabled")),
                        "rule_count": sum(p.get("rule_count") or 0 for p in packs if p.get("enabled")),
                    }
                )
        elif path == "/api/trends":
            metric = (qs.get("metric") or ["gpu_junction_c"])[0]
            try:
                hours = float((qs.get("hours") or ["24"])[0])
            except (TypeError, ValueError):
                hours = 24.0
            hours = max(0.1, min(hours, 24.0 * 90.0))  # cap at 90 days
            try:
                bucket = int((qs.get("bucket") or ["60"])[0])
            except (TypeError, ValueError):
                bucket = 60
            bucket = max(1, min(bucket, 3600))
            game_id = (qs.get("game") or [None])[0]
            self._json(
                {
                    "metric": metric,
                    "hours": hours,
                    "bucket_sec": bucket,
                    "game_id": game_id,
                    "points": series(metric, hours, bucket, game_id),
                }
            )
        elif path == "/api/correlation":
            a = (qs.get("a") or ["swap_pct"])[0]
            b = (qs.get("b") or ["pgfault_per_s"])[0]
            try:
                hours = float((qs.get("hours") or ["4"])[0])
            except (TypeError, ValueError):
                hours = 4.0
            hours = max(0.1, min(hours, 48.0))  # correlate is heavy — keep short
            game_id = (qs.get("game") or [None])[0]
            self._json(correlate(a, b, hours, game_id))
        elif path == "/api/game-sessions":
            game_id = (qs.get("game") or [None])[0]
            try:
                days = float((qs.get("days") or ["30"])[0])
            except (TypeError, ValueError):
                days = 30.0
            days = max(0.1, min(days, 90.0))
            self._json(
                {
                    "game_id": game_id,
                    "days": days,
                    "sessions": list_game_sessions(game_id, days),
                    "markers": list_session_markers(game_id, days),
                }
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        # Cap body to limit DoS / accidental huge payloads (JSON control plane)
        _max_post = 256 * 1024
        if length < 0 or length > _max_post:
            self._json({"ok": False, "error": "payload too large"}, status=413)
            return
        try:
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid JSON"}, status=400)
            return
        except UnicodeDecodeError:
            self._json({"ok": False, "error": "invalid encoding"}, status=400)
            return
        if path == "/api/rule-packs":
            from rule_packs import reload_packs, set_pack_enabled

            action = body.get("action") if isinstance(body.get("action"), str) else ""
            if action == "reload":
                packs = reload_packs()
                self._json({"ok": True, "packs": packs})
                return
            if action in ("enable", "disable"):
                pack_id = body.get("pack_id")
                if not pack_id or not isinstance(pack_id, str):
                    self._json({"ok": False, "error": "pack_id required"}, status=400)
                    return
                result = set_pack_enabled(pack_id.strip(), enabled=(action == "enable"))
                self._json(result, status=200 if result.get("ok") else 400)
                return
            if action == "set_enabled":
                pack_id = body.get("pack_id")
                enabled = body.get("enabled")
                if not pack_id or not isinstance(pack_id, str):
                    self._json({"ok": False, "error": "pack_id required"}, status=400)
                    return
                if not isinstance(enabled, bool):
                    self._json({"ok": False, "error": "enabled must be boolean"}, status=400)
                    return
                result = set_pack_enabled(pack_id.strip(), enabled=enabled)
                self._json(result, status=200 if result.get("ok") else 400)
                return
            self._json(
                {"ok": False, "error": "action must be reload, enable, disable, or set_enabled"},
                status=400,
            )
            return
        if path == "/api/apply-fix":
            # Read-only policy: never execute. Return script text for copy/paste.
            insight_id = body.get("insight_id")
            if not insight_id or not isinstance(insight_id, str):
                self._json({"ok": False, "error": "insight_id required"}, status=400)
                return
            iid = insight_id.strip()
            result = apply_fix(iid)
            with _lock:
                latest = _latest_full
                history = list(_tuning_history)
            gt = latest.get("game_totals") or {}
            game_id = gt.get("game_id") if gt.get("running") else None
            if not game_id:
                for item in history:
                    if item.get("insight_id") != iid:
                        continue
                    seen = item.get("games_seen") or {}
                    if seen:
                        game_id = max(seen, key=lambda k: seen[k])
                    break
            try:
                script = fix_script_for_insight(
                    iid,
                    latest or {},
                    _mem_spec,
                    history=history,
                )
            except Exception:
                script = ""
            result = {
                **result,
                "insight_id": iid,
                "script": script or "",
                "has_fix_script": bool(script),
            }
            self._json(result)
            return
        if path == "/api/store":
            if "retention_days" in body:
                try:
                    int(body["retention_days"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "retention_days must be an integer"}, status=400
                    )
                    return
            if "ui_scale" in body:
                try:
                    float(body["ui_scale"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "ui_scale must be a number"}, status=400
                    )
                    return
            if "tuning_log_max" in body:
                try:
                    int(body["tuning_log_max"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "tuning_log_max must be an integer"}, status=400
                    )
                    return
            if "theme_mode" in body:
                mode = body["theme_mode"]
                if not isinstance(mode, str) or mode.strip().lower() not in (
                    "cosmic",
                    "system",
                    "dark",
                    "light",
                ):
                    self._json(
                        {
                            "ok": False,
                            "error": "theme_mode must be cosmic, system, dark, or light",
                        },
                        status=400,
                    )
                    return

            action = body.get("action") if isinstance(body.get("action"), str) else None
            # Confirm gate for destructive actions (store also enforces).
            if action in (
                "clear_samples",
                "clear_tuning_log",
                "reset_guidance_prefs",
                "reset_all_pulse_data",
            ) and body.get("confirm") != "RESET":
                out = enrich_store_stats()
                out["ok"] = False
                out["error"] = "Type RESET to confirm this action"
                self._json(out, status=400)
                return

            result = update_settings(body)
            if not result.get("ok"):
                self._json(enrich_store_stats(result))
                return

            details = dict(result.get("details") or {})
            if action == "clear_tuning_log" or action == "reset_all_pulse_data":
                with _lock:
                    n = clear_tuning_log_memory(save=True)
                details["cleared_tuning_entries"] = n
            if action == "trim_tuning_log" or "tuning_log_max" in body:
                with _lock:
                    details["trim_tuning_log"] = trim_tuning_log_to_max()
            if action in ("clear_diag_cache", "reset_all_pulse_data"):
                invalidate_diagnostics_cache()
                details["cleared_diag_cache"] = True
            if action in ("clear_samples", "reset_all_pulse_data"):
                # Ask clients to drop in-memory chart buffers.
                details["client_clear_history"] = True

            out = enrich_store_stats(result)
            out["ok"] = True
            if details:
                out["details"] = details
            self._json(out)
            return
        self.send_response(404)
        self.end_headers()


def main():
    init_db()
    # Background SQLite writer (WAL) — sample inserts never block the 1 Hz sampler.
    start_writer_worker()
    seed_last_session(latest_game_session())
    pruned = prune_old()
    if pruned:
        print(f"Cosmic Pulse DB: pruned {pruned} old samples")
    # Warm Guidance Scan off the request path (quiet async; no modal).
    request_diagnostics_scan()
    t = threading.Thread(target=sampler, daemon=True, name="pulse-sampler-0")
    t.start()
    wd = threading.Thread(target=sampler_watchdog, daemon=True, name="pulse-sampler-watchdog")
    wd.start()
    time.sleep(1.2)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Cosmic Pulse: http://localhost:{PORT}")
    try:
        ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
        print(f"              http://{ip}:{PORT}")
    except (subprocess.SubprocessError, IndexError):
        pass
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
