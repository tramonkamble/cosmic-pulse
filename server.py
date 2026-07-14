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
from diagnostics import get_diagnostics, invalidate_diagnostics_cache
from game_performance import seed_last_session, tick_game_performance
from games import (
    LEGACY_GAME_IDS,
    build_games_catalog,
    detect_games,
    primary_active_game,
    prime_game_cpu,
    running_game_ids,
)
from gpu_metrics import read_gpu_engines
from gpu_thermal import gpu_thermal_state, profile_for_model
from guidance_auto import seed_clear_timers, tick_auto_resolve
from hardware_probe import (
    discover_drm_cards,
    enrich_memory_spec,
    gpu_device_path,
    gpu_sensor_prefix,
    igpu_device_path,
    igpu_label,
    igpu_sensor_prefix,
    nvme_sensor_tiles,
    probe_storage,
)
from hardware_profiles import detect_gpu_spec
from issue_aggregate import _games_for_active, build_issue_views, merge_games_seen
from load_phase import tick_load_phase
from probe_memory import infer_fallback
from pulse_config import (
    get_insight_pref_sets,
    get_resolved_insights,
    get_suppressed_insights,
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
    update_settings,
)
from store import (
    stats as store_stats,
)
from stutter import attach_stutter
from tuning_actions import build_tuning_hints, fix_script_for_insight, system_context

PORT = 8765
HISTORY_LEN = 600  # 10 minutes at 1 Hz
ROOT = Path(__file__).resolve().parent


def _strip_hint(h: dict) -> dict:
    out = dict(h)
    if "fix_script" in out:
        if "has_fix_script" not in out:
            out["has_fix_script"] = bool(out.get("fix_script"))
        del out["fix_script"]
    return out


def _strip_hints(hints: list) -> list:
    return [_strip_hint(h) for h in hints]


def latest_for_api(latest: dict, *, include_game_issues: bool = True) -> dict:
    """Drop bulky fix_script bodies from hints sent to the browser."""
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
    return out


def slim_history_point(snap: dict) -> dict:
    """Ring-buffer entry for charts and stutter session stats — not full dashboard state."""
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
    return {
        "ts": snap.get("ts"),
        "cpu": {"overall_pct": cpu.get("overall_pct")},
        "memory": {"pct": mem.get("pct"), "swap_pct": mem.get("swap_pct")},
        "gpu": {"discrete": {"busy_pct": dgpu.get("busy_pct")}},
        "disk": snap.get("disk"),
        "bandwidth": snap.get("bandwidth"),
        "stutter": snap.get("stutter"),
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
_prev_net: dict[str, tuple[int, int, float]] = {}
_prev_disk: tuple[int, int, float] | None = None
_prev_swap: tuple[int, int, float] | None = None
_prev_ctx: tuple[int, int, float] | None = None
_prev_gtt: tuple[int, float] | None = None
_gtt_high_streak: int = 0
_prev_vmstat: tuple[dict[str, int], float] | None = None
_prev_disk_busy: tuple[int, float] | None = None
_sensors_cache: tuple[float, dict] = (0.0, {})
_rate_smooth: dict[str, float] = {}
_proc_stats_cache: tuple[float, int, int] = (0.0, 0, 0)
_psi_cache: dict[str, tuple[float, dict | None]] = {}
_tuning_ctx_cache: tuple[float, dict] = (0.0, {})
_PROC_STATS_TTL = 3.0
_TUNING_CTX_TTL = 5.0

VRAM_PEAK_GBPS = 800.0
# PCIe 4.0 x16 one-way theoretical payload ≈ 31.5 GB/s
PCIE_PEAK_GBPS = 31.5
MEMORY_CACHE = ROOT / ".memory_cache.json"


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
TUNING_LOG = ROOT / ".tuning_log.json"
TUNING_MAX = 48
TUNING_SAVE_SEC = 12.0
BACKLOG_FILE = ROOT / "backlog.json"


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
            "label": "GPU PPT",
            "value": dgpu.get("power_w"),
            "unit": "W",
            "kind": "rate",
        },
        {
            "id": "igpu_pwr",
            "label": "iGPU PPT",
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


def net_rates() -> dict:
    global _prev_net
    now = time.time()
    rates: dict[str, dict] = {}
    counters = psutil.net_io_counters(pernic=True)
    for nic, c in counters.items():
        if nic == "lo":
            continue
        prev = _prev_net.get(nic)
        if prev:
            dt = now - prev[2]
            if dt > 0:
                rates[nic] = {
                    "down_mbps": round((c.bytes_recv - prev[0]) * 8 / dt / 1e6, 2),
                    "up_mbps": round((c.bytes_sent - prev[1]) * 8 / dt / 1e6, 2),
                }
        _prev_net[nic] = (c.bytes_recv, c.bytes_sent, now)
    return {
        "per_nic": rates,
        "down_mbps": round(sum(v["down_mbps"] for v in rates.values()), 2),
        "up_mbps": round(sum(v["up_mbps"] for v in rates.values()), 2),
    }


def disk_rates() -> dict:
    global _prev_disk, _prev_disk_busy
    now = time.time()
    d = psutil.disk_io_counters()
    if not d:
        return {"read_mbps": 0, "write_mbps": 0, "busy_pct": 0}
    prev = _prev_disk
    busy_ms = getattr(d, "busy_time", None)
    _prev_disk = (d.read_bytes, d.write_bytes, now)
    busy_pct = 0.0
    if busy_ms is not None:
        bprev = _prev_disk_busy
        _prev_disk_busy = (busy_ms, now)
        if bprev and now > bprev[1]:
            dtb = now - bprev[1]
            if dtb >= 0.5:
                busy_pct = round(min(100.0, (busy_ms - bprev[0]) / dtb / 10.0), 1)
    if not prev:
        return {"read_mbps": 0, "write_mbps": 0, "busy_pct": busy_pct}
    dt = now - prev[2]
    if dt <= 0:
        return {"read_mbps": 0, "write_mbps": 0, "busy_pct": busy_pct}
    return {
        "read_mbps": round((d.read_bytes - prev[0]) * 8 / dt / 1e6, 2),
        "write_mbps": round((d.write_bytes - prev[1]) * 8 / dt / 1e6, 2),
        "busy_pct": busy_pct,
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
    recommended = [
        {
            "bin": "corectrl",
            "pkg": "corectrl",
            "note": "AMD GPU fan curves, power limits, per-app profiles",
        },
        {"bin": "nvtop", "pkg": "nvtop", "note": "GPU util, VRAM, power, clocks"},
        {"bin": "radeontop", "pkg": "radeontop", "note": "Lightweight AMD GPU stats"},
        {
            "bin": "turbostat",
            "pkg": "linux-tools-common linux-tools-generic",
            "note": "CPU power, C-states, DRAM hints (needs sudo)",
        },
        {
            "bin": "perf",
            "pkg": "linux-tools-common linux-tools-generic",
            "note": "Kernel perf counters & profiling",
        },
        {"bin": "iotop", "pkg": "iotop", "note": "Per-process disk I/O"},
        {"bin": "nethogs", "pkg": "nethogs", "note": "Per-process network usage"},
        {"bin": "smartctl", "pkg": "smartmontools", "note": "NVMe/SATA health & wear"},
        {"bin": "dmidecode", "pkg": "dmidecode", "note": "RAM part numbers & configured speed"},
        {"bin": "sensors", "pkg": "lm-sensors", "note": "lm-sensors — temps, fans, PPT"},
    ]
    for t in recommended:
        t["installed"] = bool(shutil.which(t["bin"]))
    return {
        "sensors": bool(shutil.which("sensors")),
        "dmidecode": bool(shutil.which("dmidecode")),
        "smartctl": bool(shutil.which("smartctl")),
        "nvtop": bool(shutil.which("nvtop")),
        "corectrl": bool(shutil.which("corectrl")),
        "recommended": recommended,
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
    global _tuning_history, _tuning_dirty
    now = time.time()
    active_ids = {h["insight_id"] for h in active if h.get("insight_id")}
    resolved_ids, suppressed_ids = get_insight_pref_sets()
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
    for item in _tuning_history:
        iid = item.get("insight_id")
        if iid:
            item["condition_live"] = iid in active_ids
        item["active"] = True
    if seed_clear_timers(
        _tuning_history,
        active_ids,
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
        active_ids,
        resolved_ids,
        suppressed_ids,
        now,
        resolve_insight,
        fresh_active_ids=_fresh_active_ids,
    ):
        _tuning_dirty = True
    _tuning_history.sort(
        key=lambda x: (x.get("condition_live", False), x.get("last_seen", 0)),
        reverse=True,
    )
    if len(_tuning_history) > TUNING_MAX:
        del _tuning_history[TUNING_MAX:]
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
    running_ids = running_game_ids(games_state)
    primary_game = primary_active_game(games_state)
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
    mem_bw = memory_bandwidth(overall_cpu, game_cpu)
    gtt = dgpu.get("gtt") or {}

    snap = {
        "ts": time.time(),
        "cpu": {
            "overall_pct": overall_cpu,
            "per_core": per_core,
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
            "temps": cpu_temps(),
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
        "disk": disk_rates(),
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


def sampler():
    global _history, _latest_full, _static, _mem_spec, _gpu_spec, VRAM_PEAK_GBPS, _gpu_peak_by_game
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
    board_vendor = read_str(Path("/sys/class/dmi/id/board_vendor")) or ""
    board_name = read_str(Path("/sys/class/dmi/id/board_name")) or ""
    cpu_model = open("/proc/cpuinfo").read().split("model name\t: ", 1)[-1].split("\n", 1)[0]
    machine = f"{product} ({product_ver})" if product_ver else product
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
        "rig": {
            "chassis": chassis_identity(machine, os.uname().nodename, board_vendor),
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
    net_rates()
    disk_rates()
    swap_rates()
    ctx_rates()
    gtt_rates(gpu_device_path())
    vmstat_rates()
    psutil.cpu_percent(interval=0.1, percpu=True)
    prime_game_cpu()
    while True:
        _static["cosmic_theme"] = get_cosmic_theme()
        snap = collect_metrics()
        with _lock:
            _latest_full = snap
            _history.append(slim_history_point(snap))
            if len(_history) > HISTORY_LEN:
                _history.pop(0)
        try:
            record_sample_maybe_prune(snap)
        except Exception as exc:
            print(f"Cosmic Pulse DB: sample write failed: {exc}", flush=True)
        time.sleep(1)


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
            with _lock:
                latest = latest_for_api(
                    _latest_full,
                    include_game_issues=bootstrap,
                )
                if bootstrap:
                    body = {
                        "static": _static,
                        "latest": latest,
                        "history": _history,
                    }
                else:
                    body = {
                        "latest": latest,
                        "point": _history[-1] if _history else slim_history_point(_latest_full),
                        "cosmic_theme": _static.get("cosmic_theme"),
                        "resolved_insights": get_resolved_insights(),
                        "suppressed_insights": get_suppressed_insights(),
                    }
                payload = json.dumps(body).encode()
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
            diag = get_diagnostics(force=force)
            with _lock:
                gt = (_latest_full or {}).get("game_totals") or {}
                active = gt.get("game_id") or gt.get("appid")
                ctx = system_context()
                _, emitted = evaluate_rule_packs(_latest_full or {}, _mem_spec, ctx)
                scan = scan_findings_for_guidance(
                    diag.get("findings") or [],
                    emitted,
                    active_appid=str(active) if active else None,
                    running=bool(gt.get("running")),
                )
            diag = {**diag, "scan_findings": scan}
            self._json(diag)
        elif path == "/api/store":
            self._json(store_stats())
        elif path == "/api/trends":
            metric = (qs.get("metric") or ["gpu_junction_c"])[0]
            hours = float((qs.get("hours") or ["24"])[0])
            bucket = int((qs.get("bucket") or ["60"])[0])
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
            hours = float((qs.get("hours") or ["4"])[0])
            game_id = (qs.get("game") or [None])[0]
            self._json(correlate(a, b, hours, game_id))
        elif path == "/api/game-sessions":
            game_id = (qs.get("game") or [None])[0]
            days = float((qs.get("days") or ["30"])[0])
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
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid JSON"}, status=400)
            return
        if path == "/api/apply-fix":
            insight_id = body.get("insight_id")
            if not insight_id or not isinstance(insight_id, str):
                self._json({"ok": False, "error": "insight_id required"}, status=400)
                return
            with _lock:
                latest = _latest_full
            gt = latest.get("game_totals") or {}
            result = apply_fix(
                insight_id.strip(),
                game_id=gt.get("game_id") if gt.get("running") else None,
                game_name=gt.get("game_name"),
            )
            if result.get("ok"):
                gid = gt.get("game_id")
                if gid:
                    record_session_marker(
                        gid,
                        "fix",
                        label=insight_id.strip(),
                        insight_id=insight_id.strip(),
                        meta=(result.get("message") or "")[:240],
                    )
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
            self._json(update_settings(body))
            return
        self.send_response(404)
        self.end_headers()


def main():
    init_db()
    seed_last_session(latest_game_session())
    pruned = prune_old()
    if pruned:
        print(f"Cosmic Pulse DB: pruned {pruned} old samples")
    t = threading.Thread(target=sampler, daemon=True)
    t.start()
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
