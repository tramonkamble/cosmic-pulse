# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Sysfs / proc collectors used by the 1 Hz sampler.

Moved out of server.py so HTTP + publish stay in the process module.
Behavior is unchanged — rate caches live here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil

from .games import prime_game_cpu
from .gpu_metrics import read_gpu_engines
from .hardware_probe import (
    discover_drm_cards,
    enrich_memory_spec,
    gpu_device_path,
    gpu_sensor_prefix,
    igpu_device_path,
    igpu_label,
    igpu_sensor_prefix,
    nvme_sensor_tiles,
    parse_nvidia_smi_csv,
    pci_to_sensor_suffix,
    probe_nvme_smart,
)
from .paths import data_dir
from .probe_memory import infer_fallback

VRAM_PEAK_GBPS = 800.0
PCIE_PEAK_GBPS = 31.5
MEMORY_CACHE = data_dir() / ".memory_cache.json"
_HWMON_CHIPS_TTL = 30.0
_RAPL_DOMAIN_TTL = 60.0
_PCI_BDF_RE = re.compile(r"([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])", re.I)
_PROC_STATS_TTL = 3.0
_TOOLS_STATUS_TTL = 30.0

_prev_net: dict[str, tuple] = {}
_prev_disk: tuple[int, int, float] | None = None
_prev_swap: tuple[int, int, float] | None = None
_prev_ctx: tuple[int, int, float] | None = None
_prev_gtt: tuple[int, float] | None = None
_gtt_high_streak: int = 0
_prev_vmstat: tuple[dict[str, int], float] | None = None
_prev_disk_busy: dict[str, tuple[int, float]] | None = None
_prev_cpu_stat: tuple[int, int, float] | None = None
_prev_cpu_rapl: tuple[int, float] | None = None
_cpu_power_cache: tuple[float, float | None] = (0.0, None)
_sensors_cache: tuple[float, dict] = (0.0, {})
_hwmon_chips_cache: tuple[float, list[tuple[Path, str]]] = (0.0, [])
_rapl_domain_cache: tuple[float, Path | None] = (0.0, None)
_rate_smooth: dict[str, float] = {}
_proc_stats_cache: tuple[float, int, int] = (0.0, 0, 0)
_psi_cache: dict[str, tuple[float, dict | None]] = {}
_tools_status_cache: tuple[float, dict] = (0.0, {})
_sensors_lock = threading.Lock()
_mem_spec: dict = {}
_gpu_spec: dict = {}
_gpu_peak_by_game: dict[str, float] = {}
_cpu_model: str = ""
_storage: list = []


def set_host_identity(*, cpu_model: str = "", storage: list | None = None) -> None:
    """Filled by server.init_probe_state so sensor_wall need not import server."""
    global _cpu_model, _storage
    if cpu_model:
        _cpu_model = cpu_model
    if storage is not None:
        _storage = storage

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


def cpu_rapl_probe() -> dict:
    """RAPL package energy counter: present vs readable (often root-only)."""
    energy = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    present = energy.is_file()
    readable = False
    if present:
        try:
            energy.read_text()
            readable = True
        except OSError:
            readable = False
    return {"present": present, "readable": readable}


def _hwmon_chip_id(hw: Path, name: str) -> str:
    """lm-sensors-style chip id: ``k10temp-pci-00c3``, ``amdgpu-pci-0300``."""
    try:
        resolved = str((hw / "device").resolve())
    except OSError:
        return name
    matches = _PCI_BDF_RE.findall(resolved)
    if not matches:
        return name
    suf = pci_to_sensor_suffix(matches[-1])
    return f"{name}-pci-{suf}" if suf else name


def _hwmon_chips(hwmon_root: Path | None = None) -> list[tuple[Path, str]]:
    """Cached list of (hwmon dir, chip_id)."""
    global _hwmon_chips_cache
    now = time.time()
    if hwmon_root is None and now - _hwmon_chips_cache[0] < _HWMON_CHIPS_TTL and _hwmon_chips_cache[1]:
        return _hwmon_chips_cache[1]
    root = hwmon_root if hwmon_root is not None else Path("/sys/class/hwmon")
    chips: list[tuple[Path, str]] = []
    if root.is_dir():
        for hw in sorted(root.glob("hwmon*")):
            try:
                name = (hw / "name").read_text().strip()
            except OSError:
                continue
            if not name:
                continue
            chips.append((hw, _hwmon_chip_id(hw, name)))
    if hwmon_root is None:
        _hwmon_chips_cache = (now, chips)
    return chips


def _parse_hwmon_tree(hwmon_root: Path | None = None) -> dict[str, float | int | None]:
    """Read temps/fans/power from sysfs hwmon — no ``sensors`` subprocess."""
    out: dict[str, float | int | None] = {}
    for hw, chip in _hwmon_chips(hwmon_root):
        for path in hw.glob("temp*_input"):
            stem = path.name[: -len("_input")]  # temp1
            label_f = hw / f"{stem}_label"
            try:
                label = label_f.read_text().strip() if label_f.is_file() else stem
            except OSError:
                label = stem
            raw = read_float(path)
            if raw is None:
                continue
            celsius = raw / 1000.0 if abs(raw) > 200 else raw
            out[f"{chip}:{label}"] = round(celsius, 1)
        for path in hw.glob("fan*_input"):
            stem = path.name[: -len("_input")]
            label_f = hw / f"{stem}_label"
            try:
                label = label_f.read_text().strip() if label_f.is_file() else stem
            except OSError:
                label = stem
            raw = read_float(path)
            if raw is None:
                continue
            out[f"{chip}:{label}:{path.name}"] = int(raw)
        for path in list(hw.glob("power*_average")) + list(hw.glob("power*_input")):
            raw = read_float(path)
            if raw is None or raw <= 0:
                continue
            watts = raw / 1_000_000.0 if raw > 50_000 else raw
            label_f = hw / path.name.replace("_average", "_label").replace("_input", "_label")
            try:
                plabel = label_f.read_text().strip() if label_f.is_file() else "PPT"
            except OSError:
                plabel = "PPT"
            out[f"{chip}:{plabel}:{path.name}"] = round(watts, 1)
    return out


def _rapl_package_dir() -> Path | None:
    global _rapl_domain_cache
    now = time.time()
    if now - _rapl_domain_cache[0] < _RAPL_DOMAIN_TTL:
        return _rapl_domain_cache[1]
    powercap = Path("/sys/class/powercap")
    found: Path | None = None
    if powercap.is_dir():
        package_paths: list[Path] = []
        for domain in sorted(powercap.glob("intel-rapl:*")):
            rest = domain.name[len("intel-rapl:") :]
            if ":" in rest:
                continue
            energy_f = domain / "energy_uj"
            if not energy_f.is_file():
                continue
            name_f = domain / "name"
            try:
                dname = name_f.read_text().strip() if name_f.is_file() else ""
            except OSError:
                dname = ""
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
        found = package_paths[0] if package_paths else None
    _rapl_domain_cache = (now, found)
    return found


def _cpu_power_from_hwmon() -> float | None:
    """Zenpower / package hwmon watts — uses cached chip list, not a fresh glob."""
    try:
        for hw, chip in _hwmon_chips():
            name = chip.split("-pci-", 1)[0].lower()
            if name.startswith(("amdgpu", "nvme", "iwlwifi", "enp")) or name in (
                "amdgpu",
                "system76_io",
            ):
                continue
            if not any(x in name for x in ("zen", "fam15", "power", "cpu", "core", "k10", "energy")):
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
                    return round(w, 1)
    except OSError:
        return None
    return None


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
    domain = _rapl_package_dir()
    if domain is not None:
        energy_f = domain / "energy_uj"
        try:
            uj = int(energy_f.read_text().strip())
        except (OSError, ValueError):
            uj = None
        if uj is not None:
            prev = _prev_cpu_rapl
            _prev_cpu_rapl = (uj, now)
            if prev:
                duj = uj - prev[0]
                dt = now - prev[1]
                if duj >= 0 and dt >= 0.25:
                    watts = (duj / 1_000_000.0) / dt
                    if 0.5 <= watts < 500:
                        result = round(watts, 1)

    if result is None:
        result = _cpu_power_from_hwmon()

    _cpu_power_cache = (now, result)
    return result


def parse_sensors() -> dict:
    """Read hwmon sysfs (no ``sensors -j`` fork). Cached ~2s, single-flight.

    Keys stay lm-sensors-shaped (``k10temp-pci-00c3:Tctl``, ``amdgpu-pci-0300:edge``)
    so cpu_temps / sensor_wall / nvme tiles keep matching.
    """
    global _sensors_cache
    now = time.time()
    if now - _sensors_cache[0] < 2.0:
        return _sensors_cache[1]
    with _sensors_lock:
        now = time.time()
        if now - _sensors_cache[0] < 2.0:
            return _sensors_cache[1]
        try:
            out = _parse_hwmon_tree()
        except OSError:
            out = dict(_sensors_cache[1]) if _sensors_cache[1] else {}
        if not out and _sensors_cache[1]:
            out = dict(_sensors_cache[1])
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
    """Process + thread counts (cached — full walk is tens of ms)."""
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
    """Prefer any live (>0) reading. gpu_metrics can report 0 while gpu_busy_percent
    is moving, and mem_busy_percent is often stuck at 0 on RDNA3 while UMC activity is not.
    """
    nums = [float(v) for v in (metrics_val, sysfs_fallback) if v is not None]
    if not nums:
        return None
    positives = [n for n in nums if n > 0]
    return round(max(positives) if positives else 0.0, 1)


_NVIDIA_SMI_CACHE: tuple[float, dict] = (0.0, {})
_NVIDIA_SMI_QUERY = (
    "nvidia-smi",
    "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,"
    "temperature.gpu,power.draw,clocks.gr,clocks.mem,fan.speed",
    "--format=csv,noheader,nounits",
)


def _nvidia_smi_snapshot() -> dict:
    """1 Hz nvidia-smi for proprietary NVIDIA. Empty dict if unavailable."""
    global _NVIDIA_SMI_CACHE
    now = time.time()
    if now - _NVIDIA_SMI_CACHE[0] < 0.85 and _NVIDIA_SMI_CACHE[1]:
        return _NVIDIA_SMI_CACHE[1]
    if not shutil.which("nvidia-smi"):
        _NVIDIA_SMI_CACHE = (now, {})
        return {}
    try:
        raw = subprocess.check_output(
            _NVIDIA_SMI_QUERY, text=True, timeout=1.2, stderr=subprocess.DEVNULL
        )
        line = (raw.splitlines() or [""])[0]
        parsed = parse_nvidia_smi_csv(line)
    except (subprocess.SubprocessError, OSError, ValueError):
        parsed = {}
    _NVIDIA_SMI_CACHE = (now, parsed)
    return parsed


def _gpu_stats_nvidia(label: str) -> dict:
    snap = _nvidia_smi_snapshot()
    busy = snap.get("busy_pct")
    mem_busy = snap.get("mem_busy_pct")
    engines = [
        {"id": "gfx", "label": "Shaders", "pct": busy},
        {"id": "vram", "label": "Memory bus", "pct": mem_busy},
        {"id": "mm", "label": "Video", "pct": None},
    ]
    peak = vram_peak_gbps()
    vram_est = (
        round((mem_busy or 0) * peak / 100, 1) if mem_busy is not None else None
    )
    return {
        "label": label,
        "busy_pct": busy,
        "gfx_pct": busy,
        "mem_busy_pct": mem_busy,
        "engines": engines,
        "vram_used_mb": snap.get("vram_used_mb"),
        "vram_total_mb": snap.get("vram_total_mb"),
        "vram_pct": snap.get("vram_pct"),
        "temp_c": snap.get("temp_c"),
        "junction_c": snap.get("junction_c"),
        "mem_temp_c": None,
        "power_w": snap.get("power_w"),
        "fan_rpm": snap.get("fan_rpm"),
        "fan_pct": snap.get("fan_pct"),
        "gfx_mhz": snap.get("gfx_mhz"),
        "mclk_mhz": snap.get("mclk_mhz"),
        "pcie_active": None,
        "pcie_link": "?",
        "vram_est_gbps": vram_est,
        "vram_busy_pct": mem_busy,
        "vram_peak_gbps": peak,
        "pcie_est_gbps": None,
        "pcie_peak_gbps": PCIE_PEAK_GBPS,
        "gtt": {},
        "driver": "nvidia",
    }


def gpu_stats(base: Path, label: str, sensor_prefix: str, *, track_gtt: bool = True) -> dict:
    driver = ""
    try:
        driver = str((discover_drm_cards().get("discrete") or {}).get("driver") or "")
    except Exception:
        driver = ""
    if driver == "nvidia":
        return _gpu_stats_nvidia(label)
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
    gfx_pct = _engine_pct(engine_raw.get("gfx"), busy)
    umc_pct = _engine_pct(engine_raw.get("vram"), mem_busy)
    engines = [
        {
            "id": "gfx",
            "label": "Shaders",
            "pct": gfx_pct,
        },
        {
            "id": "vram",
            "label": "Memory bus",
            "pct": umc_pct,
        },
        {
            "id": "mm",
            "label": "Video",
            "pct": _engine_pct(engine_raw.get("mm"), None),
        },
    ]
    # Bus GB/s from the coalesced UMC % — sysfs mem_busy is often 0 on AMD.
    vram_busy_for_bw = umc_pct if umc_pct is not None else mem_busy
    vram_est_gbps = (
        round((vram_busy_for_bw or 0) * peak / 100, 1) if vram_busy_for_bw is not None else None
    )
    return {
        "label": label,
        "busy_pct": busy,
        "gfx_pct": gfx_pct,
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
        "vram_busy_pct": vram_busy_for_bw,
        "vram_peak_gbps": peak,
        "pcie_est_gbps": pcie_est_gbps,
        "pcie_peak_gbps": PCIE_PEAK_GBPS,
        "gtt": gtt,
        "driver": driver or None,
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
    cpu_model = _cpu_model
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

    nvme_tiles = nvme_sensor_tiles(sens, _storage)
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
            "value": pick("k10temp", "Tctl", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "ccd1",
            "label": "CCD1 Die",
            "value": pick("k10temp", "Tccd1", match_all=True),
            "unit": "°C",
            "kind": "temp",
        },
        {
            "id": "ccd2",
            "label": "CCD2 Die",
            "value": pick("k10temp", "Tccd2", match_all=True),
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

    # Workload demand model — no DRAM perf counter on Linux without root.
    # Minor page faults are *not* bus traffic (Pulse's own sampler can do 80k/s
    # while DRAM is idle). Only major faults / PSI / CPU / residency count.
    maj_churn_pct = min(8.0, vmstat["pgmajfault_per_s"] / 40.0)
    demand_pct = min(
        100.0,
        (psi10 / 100.0) * 50.0
        + (workload_cpu / 100.0) * 40.0
        + (ram_pct / 100.0) * 15.0
        + maj_churn_pct
        + min(8.0, dram_fault_gbps / max(dram_peak, 1) * 100),
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
    Cached ~30s — must not run on the 1 Hz sampler critical path every tick.
    """
    global _tools_status_cache
    now = time.time()
    if _tools_status_cache[1] and now - _tools_status_cache[0] < _TOOLS_STATUS_TTL:
        return _tools_status_cache[1]

    smart = probe_nvme_smart()
    hwmon_root = Path("/sys/class/hwmon")
    hwmon_ok = hwmon_root.is_dir() and any(hwmon_root.glob("hwmon*"))
    dmidecode_ok = bool(shutil.which("dmidecode"))
    corectrl_ok = bool(shutil.which("corectrl"))
    rapl = cpu_rapl_probe()

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
            "bin": "hwmon",
            "pkg": "",
            "role": "data",
            "note": "CPU/GPU/NVMe temperatures, fans, PPT — sysfs hwmon (no subprocess)",
            "installed": hwmon_ok,
            "feeding": hwmon_ok,
            "detail": "live · /sys/class/hwmon every ~2s" if hwmon_ok else "no /sys/class/hwmon nodes",
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
            "id": "cpu-rapl",
            "bin": "powercap",
            "pkg": "RAPL udev rule",
            "role": "data",
            "note": "CPU package watts from RAPL energy_uj (no extra apt package)",
            "installed": bool(rapl.get("present")),
            "feeding": bool(rapl.get("readable")),
            "detail": (
                "live · RAPL package-0"
                if rapl.get("readable")
                else (
                    "energy_uj is root-only — install deploy/99-rapl-readable.rules"
                    if rapl.get("present")
                    else "no intel-rapl sysfs node"
                )
            ),
            "setup": (
                "enable-cpu-rapl"
                if rapl.get("present") and not rapl.get("readable")
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
    out = {
        "sensors": hwmon_ok,
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
    _tools_status_cache = (now, out)
    return out


def _gpu_stats_sysfs_only(base: Path, label: str) -> dict:
    """GPU scoreboard fields from sysfs only — never calls ``sensors`` (watchdog-safe)."""
    try:
        if (discover_drm_cards().get("discrete") or {}).get("driver") == "nvidia":
            return _gpu_stats_nvidia(label)
    except Exception:
        pass
    hw = gpu_hwmon(base)
    vram_used = read_int(base / "mem_info_vram_used", 1024**2)
    vram_total = read_int(base / "mem_info_vram_total", 1024**2)
    busy = sanitize_pct(read_int(base / "gpu_busy_percent"))
    mem_busy = sanitize_pct(read_int(base / "mem_busy_percent"))
    temp = read_int(hw / "temp1_input", 1000) if hw else None
    junction = read_int(hw / "temp2_input", 1000) if hw else None
    mem_temp = read_int(hw / "temp3_input", 1000) if hw else None
    power_w = None
    if hw:
        for fname in ("power1_average", "power1_input"):
            raw = read_float(hw / fname) if (hw / fname).is_file() else None
            if raw is None or raw <= 0:
                continue
            w = raw / 1_000_000 if raw > 500 else raw
            if 0.5 <= w < 500:
                power_w = round(w, 1)
                break
    fan = read_int(hw / "fan1_input") if hw else None
    gfx_mhz = read_dpm_active_mhz(base / "pp_dpm_sclk")
    mclk_mhz = read_dpm_active_mhz(base / "pp_dpm_mclk")
    vram_pct = None
    if vram_used is not None and vram_total:
        vram_pct = round(100.0 * float(vram_used) / float(vram_total), 1)
    engines = [
        {"id": "gfx", "label": "Shaders", "pct": busy},
        {"id": "vram", "label": "Memory bus", "pct": mem_busy},
        {"id": "mm", "label": "Video", "pct": None},
    ]
    return {
        "label": label,
        "busy_pct": busy,
        "gfx_pct": busy,
        "mem_busy_pct": mem_busy,
        "engines": engines,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
        "vram_pct": vram_pct,
        "temp_c": temp,
        "junction_c": junction if junction is not None else temp,
        "mem_temp_c": mem_temp,
        "power_w": power_w,
        "fan_rpm": fan,
        "gfx_mhz": gfx_mhz,
        "mclk_mhz": mclk_mhz,
        "gtt": {},
    }

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
    global _hwmon_chips_cache, _rapl_domain_cache
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
    _hwmon_chips_cache = (0.0, [])
    _rapl_domain_cache = (0.0, None)


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


