# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic hardware discovery — portable across System76, generic Linux, and mixed GPU layouts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# AMD Raphael / Phoenix integrated graphics PCI device IDs (uppercase hex).
_IGPU_PCI_IDS = frozenset(
    {
        "1002:164E",  # Raphael iGPU
        "1002:15BF",  # Phoenix / Hawk Point
        "1002:1900",  # Van Gogh (Steam Deck class)
    }
)

# Known NVMe vendor strings embedded in model fields from sysfs/lsblk.
_NVME_VENDOR_HINTS: tuple[tuple[str, str], ...] = (
    ("SAMSUNG", "Samsung"),
    ("TOSHIBA", "Toshiba"),
    ("KIOXIA", "Kioxia"),
    ("WDC ", "Western Digital"),
    ("WD_BLACK", "WD Black"),
    ("SABRENT", "Sabrent"),
    ("SEAGATE", "Seagate"),
    ("CRUCIAL", "Crucial"),
    ("MICRON", "Micron"),
    ("INTEL", "Intel"),
    ("SK HYNIX", "SK hynix"),
    ("HYNIX", "SK hynix"),
    ("SOLIDIGM", "Solidigm"),
    ("CORSAIR", "Corsair"),
    ("KINGSTON", "Kingston"),
    ("ADATA", "ADATA"),
    ("GIGABYTE", "Gigabyte"),
    ("PREDATOR", "Predator"),
)

_drm_cache: dict | None = None
_storage_cache: list[dict] | None = None


def _pci_from_nvme_block(block: Path) -> str:
    """Extract NVMe controller BDF from /sys/block/nvmeXn1/device path."""
    try:
        dev_link = str((block / "device").resolve())
        m = re.search(
            r"/([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9])/nvme/",
            dev_link,
            re.I,
        )
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


def pci_to_sensor_suffix(bdf: str) -> str:
    """Map 0000:04:00.0 → sensor chip suffix 0400 (matches nvme-pci-0400)."""
    m = re.search(r":([0-9a-f]{2}):([0-9a-f]{2})\.", bdf, re.I)
    if not m:
        return ""
    return f"{m.group(1)}{m.group(2)}".lower()


def _read_uevent(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _is_igpu(pci_id: str) -> bool:
    pid = (pci_id or "").upper()
    if pid in _IGPU_PCI_IDS:
        return True
    return pid.endswith(":164E") or pid.endswith(":15BF")


def _vram_bytes(base: Path) -> int:
    for name in ("mem_info_vram_total", "mem_info_vram_used"):
        try:
            val = int((base / name).read_text().strip())
            if val > 0:
                return val
        except (OSError, ValueError):
            continue
    return 0


def _parse_nvme_model(raw: str) -> tuple[str, str, str]:
    """Return (brand, model, label) from sysfs/lsblk model string."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        return "NVMe", "Drive", "NVMe drive"

    upper = text.upper()
    brand = "NVMe"
    for hint, name in _NVME_VENDOR_HINTS:
        if hint in upper:
            brand = name
            break

    if brand == "Samsung" and text.lower().startswith("samsung"):
        product = text
    elif brand in ("Toshiba", "Kioxia"):
        product = re.sub(r"\s+NVMe.*", "", text, flags=re.I).strip()
    else:
        product = text
        for hint, _name in _NVME_VENDOR_HINTS:
            product = re.sub(re.escape(hint), "", product, flags=re.I).strip()

    product = re.sub(r"\s+", " ", product).strip(" -")
    label = f"{brand} {product}".strip() if brand not in product else product
    return brand, product or text, label


def _lspci_nvme_controllers() -> dict[str, str]:
    """PCI BDF → controller description from lspci."""
    out: dict[str, str] = {}
    try:
        text = subprocess.check_output(["lspci", "-D"], text=True, timeout=3)
        for line in text.splitlines():
            if "non-volatile" not in line.lower() and "nvme" not in line.lower():
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            out[parts[0]] = parts[1]
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return out


def probe_storage() -> list[dict]:
    """Enumerate NVMe drives with brand, model, size, PCI, and sensor key."""
    global _storage_cache
    if _storage_cache is not None:
        return _storage_cache

    controllers = _lspci_nvme_controllers()
    drives: list[dict] = []
    seen: set[str] = set()

    lsblk: dict[str, dict] = {}
    try:
        raw = subprocess.check_output(
            ["lsblk", "-J", "-o", "NAME,MODEL,VENDOR,SIZE,TYPE,TRAN"],
            text=True,
            timeout=3,
        )
        for dev in json.loads(raw).get("blockdevices", []):
            if dev.get("type") == "disk" and (
                dev.get("tran") == "nvme" or str(dev.get("name", "")).startswith("nvme")
            ):
                lsblk[dev["name"]] = dev
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError):
        pass

    for block in sorted(Path("/sys/block").glob("nvme*n1")):
        name = block.name
        if name in seen:
            continue
        seen.add(name)

        model_raw = ""
        try:
            model_raw = (block / "device" / "model").read_text().strip()
        except OSError:
            pass

        pci_bdf = _pci_from_nvme_block(block)

        brand, model, label = _parse_nvme_model(model_raw or lsblk.get(name, {}).get("model", ""))
        if pci_bdf and pci_bdf in controllers and brand == "NVMe":
            ctrl = controllers[pci_bdf]
            for vendor in (
                "Samsung",
                "Toshiba",
                "Kioxia",
                "Western Digital",
                "Seagate",
                "Crucial",
                "Intel",
            ):
                if vendor.lower() in ctrl.lower():
                    brand = vendor
                    break

        lb = lsblk.get(name, {})
        size = lb.get("size") or ""
        sensor_suffix = pci_to_sensor_suffix(pci_bdf) if pci_bdf else ""
        sensor_chip = f"nvme-pci-{sensor_suffix}" if sensor_suffix else ""

        drives.append(
            {
                "id": name,
                "name": name,
                "brand": brand,
                "model": model,
                "label": label,
                "size": size,
                "pci_bdf": pci_bdf,
                "sensor_chip": sensor_chip,
                "sensor_suffix": sensor_suffix,
                "controller": controllers.get(pci_bdf, ""),
                "tran": "nvme",
            }
        )

    _storage_cache = drives
    return drives


def discover_drm_cards() -> dict:
    """Find discrete vs integrated DRM cards from sysfs."""
    global _drm_cache
    if _drm_cache is not None:
        return _drm_cache

    cards: list[dict] = []
    drm_root = Path("/sys/class/drm")
    if drm_root.is_dir():
        for entry in sorted(drm_root.iterdir(), key=lambda p: p.name):
            if not re.fullmatch(r"card\d+", entry.name):
                continue
            uevent = entry / "device" / "uevent"
            if not uevent.is_file():
                continue
            env = _read_uevent(uevent)
            driver = env.get("DRIVER", "")
            pci_id = env.get("PCI_ID", "")
            pci_bdf = env.get("PCI_SLOT_NAME", "")
            if driver not in ("amdgpu", "nvidia", "i915", "xe"):
                continue
            device_path = entry / "device"
            cards.append(
                {
                    "card": entry.name,
                    "device_path": device_path,
                    "driver": driver,
                    "pci_id": pci_id,
                    "pci_bdf": pci_bdf,
                    "sensor_suffix": pci_to_sensor_suffix(pci_bdf) if pci_bdf else "",
                    "vram_bytes": _vram_bytes(device_path),
                    "igpu": _is_igpu(pci_id),
                }
            )

    igpu = next((c for c in cards if c["igpu"]), None)
    discrete_candidates = [c for c in cards if not c["igpu"]]
    discrete = None
    if discrete_candidates:
        discrete = max(discrete_candidates, key=lambda c: c["vram_bytes"])

    fallback_discrete = Path("/sys/class/drm/card1/device")
    fallback_igpu = Path("/sys/class/drm/card0/device")

    result = {
        "discrete": discrete
        or {
            "card": "card1",
            "device_path": fallback_discrete,
            "driver": "amdgpu",
            "pci_id": "",
            "pci_bdf": "",
            "sensor_suffix": "0300",
            "vram_bytes": 0,
            "igpu": False,
        },
        "igpu": igpu
        or {
            "card": "card0",
            "device_path": fallback_igpu,
            "driver": "amdgpu",
            "pci_id": "1002:164E",
            "pci_bdf": "",
            "sensor_suffix": "1a00",
            "vram_bytes": 0,
            "igpu": True,
        },
        "cards": cards,
    }
    _drm_cache = result
    return result


def get_drm_paths() -> dict:
    return discover_drm_cards()


def gpu_device_path() -> Path:
    return Path(get_drm_paths()["discrete"]["device_path"])


def igpu_device_path() -> Path:
    return Path(get_drm_paths()["igpu"]["device_path"])


def gpu_sensor_prefix() -> str:
    return get_drm_paths()["discrete"].get("sensor_suffix") or "0300"


def igpu_sensor_prefix() -> str:
    return get_drm_paths()["igpu"].get("sensor_suffix") or "1a00"


def igpu_label(cpu_model: str = "") -> str:
    """Human label for the integrated GPU (not assumed Raphael)."""
    cpu = (cpu_model or "").lower()
    if "ryzen" in cpu or "amd" in cpu:
        if any(x in cpu for x in ("7945", "7940", "7840", "7700", "7600", "7950", "7900")):
            return "Radeon iGPU"
        return "AMD iGPU"
    if "intel" in cpu:
        return "Intel iGPU"
    return "Integrated GPU"


def nvme_sensor_tiles(sens: dict, drives: list[dict] | None = None) -> list[dict]:
    """Build sensor wall tiles for NVMe composite temps matched to drive labels."""
    drives = drives if drives is not None else probe_storage()
    tiles: list[dict] = []
    for i, drive in enumerate(drives):
        chip = drive.get("sensor_chip") or ""
        temp = None
        if chip:
            for sk, sv in sens.items():
                if chip in sk.lower() and "composite" in sk.lower():
                    temp = sv
                    break
            if temp is None:
                for sk, sv in sens.items():
                    if chip in sk.lower() and ":temp" in sk.lower():
                        temp = sv
                        break
        short = drive.get("label") or drive.get("model") or f"NVMe {i + 1}"
        if len(short) > 42:
            short = f"{drive.get('brand', 'NVMe')} {drive.get('model', '')[:28]}".strip()
        tiles.append(
            {
                "id": f"nvme_{drive.get('name', i)}",
                "label": short,
                "value": temp,
                "unit": "°C",
                "kind": "temp",
                "hw": "storage",
                "drive": drive,
            }
        )
    return tiles


# NVMe SMART via smartctl — optional; needs read access to /dev/nvmeN (root or udev).
_nvme_smart_cache: tuple[float, dict] = (0.0, {})


def _parse_smartctl_nvme(payload: dict) -> dict | None:
    """Normalize smartctl -j NVMe health into a compact dict."""
    if not payload or not isinstance(payload, dict):
        return None
    log = payload.get("nvme_smart_health_information_log") or {}
    if not log and not payload.get("model_name"):
        return None
    # NVMe data units are 1000 × 512 B = 512_000 bytes each (spec).
    units_written = log.get("data_units_written")
    units_read = log.get("data_units_read")
    tb_written = None
    tb_read = None
    if units_written is not None:
        tb_written = round(float(units_written) * 512_000 / (1000**4), 2)
    if units_read is not None:
        tb_read = round(float(units_read) * 512_000 / (1000**4), 2)
    temp = log.get("temperature")
    if temp is None and isinstance(payload.get("temperature"), dict):
        temp = payload["temperature"].get("current")
    crit = log.get("critical_warning")
    if isinstance(crit, dict):
        crit = crit.get("value", 0)
    return {
        "model": (payload.get("model_name") or "").strip() or None,
        "serial": (payload.get("serial_number") or "").strip() or None,
        "percentage_used": log.get("percentage_used"),
        "available_spare": log.get("available_spare"),
        "available_spare_threshold": log.get("available_spare_threshold"),
        "critical_warning": int(crit) if crit is not None else 0,
        "temperature_c": int(temp) if temp is not None else None,
        "media_errors": log.get("media_errors"),
        "num_err_log_entries": log.get("num_err_log_entries"),
        "power_on_hours": log.get("power_on_hours"),
        "power_cycles": log.get("power_cycles"),
        "data_units_written": units_written,
        "data_units_read": units_read,
        "tb_written": tb_written,
        "tb_read": tb_read,
        "unsafe_shutdowns": log.get("unsafe_shutdowns"),
    }


def probe_nvme_smart(max_age_sec: float = 180.0) -> dict:
    """Read NVMe SMART when smartctl can open the devices.

    Without elevated access smartctl returns permission errors; we still report
    that so the tools panel can show "installed · needs access".
    """
    global _nvme_smart_cache
    import time as _time

    now = _time.time()
    if now - _nvme_smart_cache[0] < max_age_sec and _nvme_smart_cache[1]:
        return dict(_nvme_smart_cache[1])

    installed = bool(shutil.which("smartctl"))
    result: dict = {
        "installed": installed,
        "readable": False,
        "permission_error": False,
        "drives": {},
        "message": "smartmontools not installed (provides smartctl)",
    }
    if not installed:
        _nvme_smart_cache = (now, result)
        return dict(result)

    # Controllers (/dev/nvme0) and namespaces (/dev/nvme0n1) — prefer controller.
    candidates: list[tuple[str, str]] = []  # (block_name, dev_path)
    for ctrl in sorted(Path("/sys/class/nvme").glob("nvme*")):
        if not ctrl.name[4:].isdigit():
            continue
        block_name = None
        for child in sorted(ctrl.iterdir()):
            if child.name.startswith(ctrl.name) and "n" in child.name[len(ctrl.name) :]:
                block_name = child.name
                break
        if not block_name:
            # fallback: first nvmeXn1 under /sys/block matching controller
            for block in sorted(Path("/sys/block").glob(f"{ctrl.name}n*")):
                block_name = block.name
                break
        if not block_name:
            continue
        ctrl_dev = Path(f"/dev/{ctrl.name}")
        ns_dev = Path(f"/dev/{block_name}")
        if ctrl_dev.exists():
            candidates.append((block_name, str(ctrl_dev)))
        elif ns_dev.exists():
            candidates.append((block_name, str(ns_dev)))

    if not candidates:
        result["message"] = "smartmontools installed · no NVMe devices found"
        _nvme_smart_cache = (now, result)
        return dict(result)

    readable = 0
    perm_denied = 0
    other_fail = 0
    for block_name, dev_path in candidates:
        try:
            proc = subprocess.run(
                ["smartctl", "-a", "-j", dev_path],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            other_fail += 1
            continue
        raw = proc.stdout or ""
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        messages = (payload.get("smartctl") or {}).get("messages") or []
        msg_text = " ".join(
            m.get("string", "") if isinstance(m, dict) else str(m) for m in messages
        ).lower()
        has_log = bool(payload.get("nvme_smart_health_information_log"))
        if not has_log:
            # exit 2 = open failed (almost always permissions for /dev/nvmeN)
            if "permission" in msg_text or proc.returncode == 2:
                perm_denied += 1
                continue
            other_fail += 1
            continue
        parsed = _parse_smartctl_nvme(payload)
        if not parsed:
            other_fail += 1
            continue
        parsed["device"] = dev_path
        parsed["ok"] = parsed.get("critical_warning", 0) == 0 and (
            parsed.get("percentage_used") is None or parsed["percentage_used"] < 90
        )
        result["drives"][block_name] = parsed
        readable += 1

    result["readable"] = readable > 0
    result["permission_error"] = perm_denied > 0 and readable == 0
    if readable:
        result["message"] = f"SMART feeding · {readable} NVMe"
    elif perm_denied:
        result["message"] = (
            "installed · needs device access (disk group + udev, or run as root once via setup script)"
        )
    elif other_fail:
        result["message"] = "installed · smartctl cannot read SMART (need disk group / udev)"
    else:
        result["message"] = "installed · no data"

    _nvme_smart_cache = (now, result)
    return dict(result)


def invalidate_nvme_smart_cache() -> None:
    global _nvme_smart_cache
    _nvme_smart_cache = (0.0, {})


def enrich_memory_spec(spec: dict) -> dict:
    """Add brand/kit/label from dmidecode sticks when PART_DB is not used."""
    sticks = spec.get("sticks") or []
    if not sticks:
        return spec

    mfrs = sorted({s.get("manufacturer", "").strip() for s in sticks if s.get("manufacturer")})
    parts = [s.get("part", "").strip() for s in sticks if s.get("part")]
    if mfrs and not spec.get("manufacturer"):
        spec["manufacturer"] = mfrs[0] if len(mfrs) == 1 else mfrs[0]

    if parts and not spec.get("part"):
        spec["part"] = parts[0]

    if not spec.get("kit") and parts:
        spec["kit"] = parts[0][:48]

    mts = spec.get("configured_mts") or spec.get("speed_mts") or 0
    total = spec.get("total_gb") or 0
    channels = spec.get("channels") or 2
    mfr = spec.get("manufacturer") or ""
    part = spec.get("part") or ""

    if spec.get("confidence") == "exact" and mfr and mts and total:
        per = sticks[0].get("size_gb") if sticks else total // max(channels, 1)
        spec["label"] = f"{mfr} {part or 'DDR5'} · DDR5-{mts} · {channels}×{per}GB"
    elif mfr and not spec.get("label", "").startswith(mfr):
        spec["label"] = f"{mfr} · {spec.get('label', 'System RAM')}"

    return spec


_display_refresh_cache: tuple[float, float | None] = (0.0, None)


def primary_display_refresh_hz(max_age_sec: float = 120.0) -> float | None:
    """Primary monitor refresh rate (Hz) from xrandr; cached briefly."""
    global _display_refresh_cache
    import time as _time

    now = _time.time()
    if now - _display_refresh_cache[0] < max_age_sec and _display_refresh_cache[1]:
        return _display_refresh_cache[1]

    hz: float | None = None
    try:
        out = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if " connected " not in line:
                    continue
                primary = "primary" in line
                if not primary and hz is not None:
                    continue
                m = re.search(r"(\d+(?:\.\d+)?)\*\+?\s*$", line)
                if m:
                    hz = float(m.group(1))
                    if primary:
                        break
            if hz is None:
                for line in out.stdout.splitlines():
                    m = re.search(r"(\d+(?:\.\d+)?)\*\+?\s*$", line)
                    if m:
                        hz = float(m.group(1))
                        break
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass

    _display_refresh_cache = (now, hz)
    return hz


# CTA-861 HDR static metadata extended tag (EDID).
_EDID_EXT_TAG_HDR_STATIC = 6
# DRM Colorspace enum values commonly used for HDR output (AMD/Intel).
_DRM_COLORSPACE_HDR = frozenset({9, 10})  # BT2020_RGB, BT2020_YCC

_display_hdr_cache: tuple[float, dict] = (0.0, {})


def _edid_hdr_static(edid: bytes) -> dict:
    """Parse CTA-861 HDR Static Metadata Data Block from raw EDID bytes."""
    out: dict = {
        "capable": False,
        "eotf_mask": 0,
        "max_nits": None,
        "max_fall_nits": None,
    }
    if not edid or len(edid) < 128:
        return out
    # Walk 128-byte extension blocks for CTA-861 (tag 0x02).
    off = 128
    while off + 4 <= len(edid):
        if edid[off] != 0x02:
            off += 128
            continue
        dtd_start = edid[off + 2]
        p = off + 4
        end = off + dtd_start if dtd_start else off + 127
        end = min(end, len(edid))
        while p < end:
            header = edid[p]
            btag = header >> 5
            blen = header & 0x1F
            payload = edid[p + 1 : p + 1 + blen]
            p += 1 + blen
            if btag != 7 or not payload:
                continue
            if payload[0] != _EDID_EXT_TAG_HDR_STATIC:
                continue
            eotf = payload[1] if len(payload) > 1 else 0
            out["eotf_mask"] = eotf
            # bit0 traditional SDR, bit1 traditional HDR, bit2 PQ (ST.2084), bit3 HLG
            out["capable"] = bool(eotf & 0b1110)
            if len(payload) > 3 and payload[3]:
                out["max_nits"] = round(50.0 * (2.0 ** (payload[3] / 32.0)), 1)
            if len(payload) > 4 and payload[4]:
                out["max_fall_nits"] = round(50.0 * (2.0 ** (payload[4] / 32.0)), 1)
            return out
        off += 128
    return out


def _drm_connected_hdr_state() -> dict:
    """Read Colorspace / HDR_OUTPUT_METADATA from the first connected DRM connector."""
    import ctypes
    import ctypes.util

    result: dict = {
        "connector": None,
        "colorspace": 0,
        "colorspace_name": "Default",
        "hdr_metadata_blob": 0,
        "active": False,
        "max_bpc": None,
    }
    libname = ctypes.util.find_library("drm")
    if not libname:
        return result
    lib = ctypes.CDLL(libname)

    class drmModeRes(ctypes.Structure):
        _fields_ = [
            ("count_fbs", ctypes.c_int),
            ("fbs", ctypes.POINTER(ctypes.c_uint32)),
            ("count_crtcs", ctypes.c_int),
            ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
            ("count_connectors", ctypes.c_int),
            ("connectors", ctypes.POINTER(ctypes.c_uint32)),
            ("count_encoders", ctypes.c_int),
            ("encoders", ctypes.POINTER(ctypes.c_uint32)),
            ("min_width", ctypes.c_uint32),
            ("max_width", ctypes.c_uint32),
            ("min_height", ctypes.c_uint32),
            ("max_height", ctypes.c_uint32),
        ]

    class drmModeModeInfo(ctypes.Structure):
        _fields_ = [
            ("clock", ctypes.c_uint32),
            ("hdisplay", ctypes.c_uint16),
            ("hsync_start", ctypes.c_uint16),
            ("hsync_end", ctypes.c_uint16),
            ("htotal", ctypes.c_uint16),
            ("hskew", ctypes.c_uint16),
            ("vdisplay", ctypes.c_uint16),
            ("vsync_start", ctypes.c_uint16),
            ("vsync_end", ctypes.c_uint16),
            ("vtotal", ctypes.c_uint16),
            ("vscan", ctypes.c_uint16),
            ("vrefresh", ctypes.c_uint32),
            ("flags", ctypes.c_uint32),
            ("type", ctypes.c_uint32),
            ("name", ctypes.c_char * 32),
        ]

    class drmModeConnector(ctypes.Structure):
        _fields_ = [
            ("connector_id", ctypes.c_uint32),
            ("encoder_id", ctypes.c_uint32),
            ("connector_type", ctypes.c_uint32),
            ("connector_type_id", ctypes.c_uint32),
            ("connection", ctypes.c_uint32),
            ("mmWidth", ctypes.c_uint32),
            ("mmHeight", ctypes.c_uint32),
            ("subpixel", ctypes.c_uint32),
            ("count_modes", ctypes.c_int),
            ("modes", ctypes.POINTER(drmModeModeInfo)),
            ("count_props", ctypes.c_int),
            ("props", ctypes.POINTER(ctypes.c_uint32)),
            ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
            ("count_encoders", ctypes.c_int),
            ("encoders", ctypes.POINTER(ctypes.c_uint32)),
        ]

    class drmModePropertyEnum(ctypes.Structure):
        _fields_ = [("value", ctypes.c_uint64), ("name", ctypes.c_char * 32)]

    class drmModePropertyRes(ctypes.Structure):
        _fields_ = [
            ("prop_id", ctypes.c_uint32),
            ("flags", ctypes.c_uint32),
            ("name", ctypes.c_char * 32),
            ("count_values", ctypes.c_int),
            ("values", ctypes.POINTER(ctypes.c_uint64)),
            ("count_enums", ctypes.c_int),
            ("enums", ctypes.POINTER(drmModePropertyEnum)),
            ("count_blobs", ctypes.c_int),
            ("blob_ids", ctypes.POINTER(ctypes.c_uint32)),
        ]

    lib.drmModeGetResources.argtypes = [ctypes.c_int]
    lib.drmModeGetResources.restype = ctypes.POINTER(drmModeRes)
    lib.drmModeFreeResources.argtypes = [ctypes.POINTER(drmModeRes)]
    lib.drmModeGetConnectorCurrent.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeGetConnectorCurrent.restype = ctypes.POINTER(drmModeConnector)
    lib.drmModeGetConnector.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeGetConnector.restype = ctypes.POINTER(drmModeConnector)
    lib.drmModeFreeConnector.argtypes = [ctypes.POINTER(drmModeConnector)]
    lib.drmModeGetProperty.argtypes = [ctypes.c_int, ctypes.c_uint32]
    lib.drmModeGetProperty.restype = ctypes.POINTER(drmModePropertyRes)
    lib.drmModeFreeProperty.argtypes = [ctypes.POINTER(drmModePropertyRes)]

    type_names = {
        1: "VGA",
        10: "DP",
        11: "HDMI-A",
        12: "HDMI-B",
        14: "eDP",
        15: "DSI",
        16: "VIRTUAL",
        17: "DSI",
        18: "DPI",
        19: "Writeback",
        20: "SPI",
        21: "USB",
    }

    for card in sorted(Path("/dev/dri").glob("card*")):
        try:
            fd = os.open(card, os.O_RDWR | os.O_CLOEXEC)
        except OSError:
            continue
        found: dict | None = None
        try:
            res_ptr = lib.drmModeGetResources(fd)
            if not res_ptr:
                continue
            res = res_ptr.contents
            try:
                for i in range(res.count_connectors):
                    cid = res.connectors[i]
                    conn_ptr = lib.drmModeGetConnectorCurrent(fd, cid)
                    if not conn_ptr:
                        conn_ptr = lib.drmModeGetConnector(fd, cid)
                    if not conn_ptr:
                        continue
                    conn = conn_ptr.contents
                    if conn.connection != 1:  # DRM_MODE_CONNECTED
                        lib.drmModeFreeConnector(conn_ptr)
                        continue
                    ctype = type_names.get(conn.connector_type, f"type{conn.connector_type}")
                    result["connector"] = f"{ctype}-{conn.connector_type_id}"
                    cs_val = 0
                    cs_name = "Default"
                    hdr_blob = 0
                    max_bpc = None
                    for j in range(conn.count_props):
                        prop_ptr = lib.drmModeGetProperty(fd, conn.props[j])
                        if not prop_ptr:
                            continue
                        prop = prop_ptr.contents
                        name = prop.name.decode(errors="replace")
                        val = int(conn.prop_values[j])
                        if name == "Colorspace":
                            cs_val = val
                            for k in range(prop.count_enums):
                                if int(prop.enums[k].value) == val:
                                    cs_name = prop.enums[k].name.decode(errors="replace")
                                    break
                        elif name == "HDR_OUTPUT_METADATA":
                            hdr_blob = val
                        elif name == "max bpc":
                            max_bpc = val
                        lib.drmModeFreeProperty(prop_ptr)
                    result["colorspace"] = cs_val
                    result["colorspace_name"] = cs_name
                    result["hdr_metadata_blob"] = hdr_blob
                    result["max_bpc"] = max_bpc
                    # Active when compositor set HDR static metadata blob, or BT.2020 colorspace.
                    result["active"] = bool(hdr_blob) or cs_val in _DRM_COLORSPACE_HDR
                    lib.drmModeFreeConnector(conn_ptr)
                    found = dict(result)
                    break
            finally:
                lib.drmModeFreeResources(res_ptr)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        if found is not None:
            return found
    return result


def _edid_for_connector(connector: str | None) -> bytes:
    """Load EDID bytes for a DRM connector name like DP-1, preferring connected outputs."""
    drm_root = Path("/sys/class/drm")
    candidates: list[Path] = []
    if connector:
        for p in drm_root.glob(f"card*-{connector}"):
            candidates.append(p)
    if not candidates:
        for p in sorted(drm_root.glob("card*-*")):
            status = p / "status"
            if status.is_file() and status.read_text(errors="ignore").strip() == "connected":
                candidates.append(p)
    for p in candidates:
        edid_path = p / "edid"
        if edid_path.is_file():
            try:
                data = edid_path.read_bytes()
                if data:
                    return data
            except OSError:
                continue
    return b""


def primary_display_hdr(max_age_sec: float = 30.0) -> dict:
    """Primary connected display HDR capability and live state.

    Returns keys used by rule packs under ``display.*``:
      capable, active, connector, colorspace_name, max_nits, max_fall_nits,
      desktop_toggle (bool — whether the session compositor exposes a known HDR switch).
    """
    global _display_hdr_cache
    import time as _time

    now = _time.time()
    if now - _display_hdr_cache[0] < max_age_sec and _display_hdr_cache[1]:
        return dict(_display_hdr_cache[1])

    # Default empty state — not capable, not active.
    state: dict = {
        "capable": False,
        "active": False,
        "connector": None,
        "colorspace_name": "Default",
        "max_nits": None,
        "max_fall_nits": None,
        "desktop": (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":")[0],
        "desktop_toggle": False,
        "summary": "unknown",
    }

    try:
        drm = _drm_connected_hdr_state()
        state["connector"] = drm.get("connector")
        state["colorspace_name"] = drm.get("colorspace_name") or "Default"
        state["active"] = bool(drm.get("active"))

        edid = _edid_for_connector(state["connector"])
        hdr = _edid_hdr_static(edid)
        state["capable"] = bool(hdr.get("capable"))
        state["max_nits"] = hdr.get("max_nits")
        state["max_fall_nits"] = hdr.get("max_fall_nits")

        # COSMIC (and most non-KDE/GNOME-nightly sessions) do not yet expose a
        # stable desktop HDR toggle via cosmic-randr / Settings.
        desktop = (state["desktop"] or "").lower()
        if "kde" in desktop or "plasma" in desktop:
            state["desktop_toggle"] = True  # System Settings → Display → HDR
        else:
            state["desktop_toggle"] = False

        if not state["capable"]:
            state["summary"] = "not_capable"
        elif state["active"]:
            state["summary"] = "on"
        else:
            state["summary"] = "off"
    except Exception:
        # Never break the metrics sampler for display probing.
        state["summary"] = "probe_error"

    _display_hdr_cache = (now, state)
    return dict(state)


def _read_os_release() -> dict[str, str]:
    """Parse /etc/os-release (and Pop's copy) into a key/value map."""
    out: dict[str, str] = {}
    for path in (Path("/etc/os-release"), Path("/etc/pop-os/os-release")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            out[key] = val
        if out:
            break
    return out


def _read_dmi(name: str) -> str:
    try:
        return Path(f"/sys/class/dmi/id/{name}").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# Process names that identify a live graphical session (ordered by specificity).
_DE_PROCESS_HINTS: tuple[tuple[str, str, str], ...] = (
    # id, display label, match substring in /proc/*/comm or cmdline basename
    ("cosmic", "COSMIC", "cosmic-comp"),
    ("cosmic", "COSMIC", "cosmic-session"),
    ("kde", "KDE Plasma", "plasmashell"),
    ("kde", "KDE Plasma", "kwin_wayland"),
    ("kde", "KDE Plasma", "kwin_x11"),
    ("gnome", "GNOME", "gnome-shell"),
    ("cinnamon", "Cinnamon", "cinnamon"),
    ("mate", "MATE", "mate-session"),
    ("xfce", "XFCE", "xfce4-session"),
    ("budgie", "Budgie", "budgie-panel"),
    ("sway", "Sway", "sway"),
    ("hyprland", "Hyprland", "Hyprland"),
    ("i3", "i3", "i3"),
)


def _proc_names() -> set[str]:
    """Basenames of running processes (cheap /proc walk)."""
    names: set[str] = set()
    try:
        for ent in Path("/proc").iterdir():
            if not ent.name.isdigit():
                continue
            try:
                comm = (ent / "comm").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if comm:
                names.add(comm)
    except OSError:
        pass
    return names


def _loginctl_active_desktop(user: str | None = None) -> dict:
    """Best-effort active seat session Desktop/Type for this user."""
    out: dict = {"desktop": None, "type": None, "active": False}
    if not shutil.which("loginctl"):
        return out
    try:
        listing = subprocess.check_output(
            ["loginctl", "list-sessions", "--no-legend"],
            text=True,
            timeout=1.5,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError):
        return out
    want_user = user or os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    best: dict | None = None
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        sid, _uid, uname = parts[0], parts[1], parts[2]
        if want_user and uname != want_user:
            continue
        try:
            raw = subprocess.check_output(
                [
                    "loginctl",
                    "show-session",
                    sid,
                    "-p",
                    "Desktop",
                    "-p",
                    "Type",
                    "-p",
                    "Active",
                    "-p",
                    "State",
                    "-p",
                    "Remote",
                ],
                text=True,
                timeout=1.0,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        props = {}
        for pline in raw.splitlines():
            if "=" in pline:
                k, _, v = pline.partition("=")
                props[k] = v.strip()
        if props.get("Remote", "").lower() in ("yes", "true", "1"):
            continue
        state = (props.get("State") or "").lower()
        active = (props.get("Active") or "").lower() in ("yes", "true", "1")
        desktop = (props.get("Desktop") or "").strip()
        stype = (props.get("Type") or "").strip().lower() or None
        # Prefer active graphical sessions
        score = 0
        if active:
            score += 4
        if state == "active":
            score += 2
        if stype in ("wayland", "x11", "mir"):
            score += 2
        if desktop:
            score += 1
        cand = {"desktop": desktop or None, "type": stype, "active": active, "_score": score}
        if best is None or cand["_score"] > best["_score"]:
            best = cand
    if best:
        best.pop("_score", None)
        return best
    return out


def _normalize_de_id(raw: str | None) -> tuple[str | None, str | None]:
    """Map free-form desktop strings to (id, label)."""
    if not raw:
        return None, None
    s = raw.strip().lower()
    if not s:
        return None, None
    # Colon-separated XDG_CURRENT_DESKTOP lists (e.g. ubuntu:GNOME)
    tokens = [t.strip() for t in re.split(r"[:;,\s]+", s) if t.strip()]
    joined = " ".join(tokens)
    rules: list[tuple[str, str, tuple[str, ...]]] = [
        ("cosmic", "COSMIC", ("cosmic",)),
        ("kde", "KDE Plasma", ("kde", "plasma")),
        ("gnome", "GNOME", ("gnome",)),
        ("cinnamon", "Cinnamon", ("cinnamon", "x-cinnamon")),
        ("mate", "MATE", ("mate",)),
        ("xfce", "XFCE", ("xfce",)),
        ("budgie", "Budgie", ("budgie",)),
        ("sway", "Sway", ("sway",)),
        ("hyprland", "Hyprland", ("hyprland",)),
        ("i3", "i3", ("i3",)),
        ("lxqt", "LXQt", ("lxqt",)),
        ("unity", "Unity", ("unity",)),
    ]
    for de_id, label, keys in rules:
        if any(k in joined or k in tokens for k in keys):
            return de_id, label
    # Unknown but present — surface raw first token
    pretty = tokens[0].upper() if tokens else raw.strip()
    return "other", pretty


def detect_running_desktop() -> dict:
    """Detect the *running* DE/compositor — not merely installed configs.

    Priority:
      1. Live compositor/session processes (/proc)
      2. loginctl active seat session
      3. Environment (XDG_CURRENT_DESKTOP / DESKTOP_SESSION) — last resort;
         systemd user services often inherit a stale or empty env.
    """
    procs = _proc_names()
    from_proc_id: str | None = None
    from_proc_label: str | None = None
    for de_id, label, needle in _DE_PROCESS_HINTS:
        if needle in procs:
            from_proc_id, from_proc_label = de_id, label
            break

    login = _loginctl_active_desktop()
    from_login_id, from_login_label = _normalize_de_id(login.get("desktop"))

    env_raw = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("XDG_SESSION_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    )
    from_env_id, from_env_label = _normalize_de_id(env_raw)

    session_type = (
        login.get("type")
        or (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        or None
    )
    if session_type == "":
        session_type = None

    # Process evidence wins (kwin vs cosmic-comp is definitive).
    if from_proc_id:
        de_id, de_label, source = from_proc_id, from_proc_label, "process"
    elif from_login_id:
        de_id, de_label, source = from_login_id, from_login_label, "loginctl"
    elif from_env_id:
        de_id, de_label, source = from_env_id, from_env_label, "environ"
    else:
        de_id, de_label, source = None, None, None

    cosmic_cfg = (Path.home() / ".config" / "cosmic").is_dir()
    is_cosmic = de_id == "cosmic"
    # Config on disk ≠ active session (very common: Cosmic daily, KDE for gaming).
    cosmic_available = cosmic_cfg or is_cosmic

    detail = None
    if session_type in ("wayland", "x11"):
        detail = session_type.capitalize()
    title_bits = [de_label or "Unknown desktop"]
    if session_type:
        title_bits.append(session_type)
    title_bits.append(f"via {source}" if source else "undetected")
    if cosmic_available and not is_cosmic:
        title_bits.append("COSMIC also installed")

    return {
        "id": de_id,
        "name": de_label,
        "detail": detail,
        "session_type": session_type,
        "source": source,
        "is_cosmic": is_cosmic,
        "cosmic_available": cosmic_available,
        "xdg_current_desktop": os.environ.get("XDG_CURRENT_DESKTOP") or None,
        "loginctl_desktop": login.get("desktop"),
        "title": " · ".join(title_bits),
    }


def _kernel_badge_detail(release: str) -> str:
    """Shorten uname -r for the badge while keeping Pop build numbers."""
    # 7.0.11-76070011-generic → 7.0.11-76070011
    detail = re.sub(r"-(generic|amd64|x86_64)$", "", release, flags=re.I)
    if len(detail) > 22:
        # Fall back to major.minor.patch only if still huge
        head = release.split("-", 1)[0]
        return head or detail[:22]
    return detail


def _mesa_pkg_version() -> tuple[str | None, str | None, str | None]:
    """Return (raw_version, short_display, package_name) from dpkg/rpm."""
    pkgs = (
        "mesa-vulkan-drivers",
        "mesa-libgallium",
        "libgl1-mesa-dri",
        "mesa-common-dev",
    )
    if shutil.which("dpkg-query"):
        for pkg in pkgs:
            try:
                # Newline per arch so multi-arch installs don't concatenate versions
                raw = subprocess.check_output(
                    ["dpkg-query", "-W", "-f=${Version}\\n", pkg],
                    text=True,
                    timeout=2,
                    stderr=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, OSError, FileNotFoundError):
                continue
            # First non-empty arch line
            raw = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
            if not raw:
                continue
            # 26.1.6~kisak1~n → 26.1.6 (+ flavor in title/detail)
            short = re.split(r"[~+]", raw, maxsplit=1)[0]
            return raw, short, pkg
    if shutil.which("rpm"):
        for pkg in ("mesa-vulkan-drivers", "mesa-libGL", "mesa-dri-drivers"):
            try:
                raw = subprocess.check_output(
                    ["rpm", "-q", "--qf", "%{VERSION}", pkg],
                    text=True,
                    timeout=2,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except (subprocess.SubprocessError, OSError, FileNotFoundError):
                continue
            if raw and "not installed" not in raw.lower():
                short = re.split(r"[~+]", raw, maxsplit=1)[0]
                return raw, short, pkg
    return None, None, None


def _mesa_glx_version() -> tuple[str | None, str | None]:
    """Fallback: glxinfo -B 'Version: x.y.z' when packages are unavailable."""
    if not shutil.which("glxinfo"):
        return None, None
    env = os.environ.copy()
    # Prefer existing display; skip if none (headless/service)
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        return None, None
    try:
        out = subprocess.check_output(
            ["glxinfo", "-B"],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except (subprocess.SubprocessError, OSError):
        return None, None
    m = re.search(r"^\s*Version:\s*([\d.]+)", out, re.M)
    if not m:
        # OpenGL core profile version string sometimes embeds Mesa
        m = re.search(r"Mesa\s+([\d.]+)", out)
    if not m:
        return None, None
    ver = m.group(1)
    return ver, ver


def detect_mesa() -> dict:
    """Mesa graphics stack version for host chrome (AMD/Intel gaming path)."""
    raw, short, pkg = _mesa_pkg_version()
    source = "package" if raw else None
    if not raw:
        raw, short = _mesa_glx_version()
        source = "glxinfo" if raw else None
    # Extra flavor from package epoch/revision (kisak, etc.)
    flavor = None
    if raw and "~" in raw:
        # 26.1.6~kisak1~n → kisak1
        flavor = raw.split("~", 1)[1].split("~", 1)[0] or None
    return {
        "version": short or raw,
        "version_raw": raw,
        "package": pkg,
        "flavor": flavor,
        "source": source,
        "present": bool(raw),
    }


def platform_identity() -> dict:
    """Pop!_OS / System76 / running-DE host identity for dashboard chrome.

    Desktop detection reflects the *active* session (process/loginctl), not
    merely that COSMIC config exists on disk.
    """
    osr = _read_os_release()
    pretty = osr.get("PRETTY_NAME") or osr.get("NAME") or "Linux"
    name = osr.get("NAME") or pretty
    version = osr.get("VERSION") or osr.get("VERSION_ID") or ""
    version_id = osr.get("VERSION_ID") or ""
    os_id = (osr.get("ID") or "").lower()
    id_like = (osr.get("ID_LIKE") or "").lower()
    is_pop = os_id == "pop" or "pop" in name.lower() or "pop!_os" in pretty.lower()

    vendor = _read_dmi("sys_vendor") or _read_dmi("board_vendor")
    product = _read_dmi("product_name")
    product_version = _read_dmi("product_version")
    board = _read_dmi("board_name")
    is_s76 = "system76" in vendor.lower() or "system76" in product.lower()

    model_short = product
    if product_version and product_version.lower() not in (product or "").lower():
        model_short = product or product_version

    desktop = detect_running_desktop()
    is_cosmic = bool(desktop.get("is_cosmic"))

    kernel = ""
    try:
        kernel = os.uname().release
    except OSError:
        pass

    mesa = detect_mesa()

    badges: list[dict] = []
    if is_pop:
        badges.append(
            {
                "id": "pop",
                "label": "Pop!_OS",
                "detail": version or version_id or None,
                "title": pretty,
            }
        )
    elif pretty:
        badges.append(
            {
                "id": "linux",
                "label": name.split()[0] if name else "Linux",
                "detail": version_id or version or None,
                "title": pretty,
            }
        )

    if is_s76:
        badges.append(
            {
                "id": "system76",
                "label": "System76",
                "detail": model_short or None,
                "title": " · ".join(
                    p for p in (vendor or "System76", model_short, product_version) if p
                ),
            }
        )

    # Running DE badge — always surface when known (KDE, COSMIC, GNOME, …)
    if desktop.get("id") and desktop.get("name"):
        de_id = desktop["id"]
        badge_id = de_id if de_id in ("cosmic", "kde", "gnome", "other") else "de"
        # Map well-known ids to CSS classes we style; others use generic .de
        if de_id not in ("cosmic", "kde", "gnome"):
            badge_id = "de"
        detail = desktop.get("detail")
        title = desktop.get("title") or desktop["name"]
        if desktop.get("cosmic_available") and not is_cosmic:
            title = f"{title} · COSMIC installed (not active)"
        badges.append(
            {
                "id": badge_id,
                "label": desktop["name"],
                "detail": detail,
                "title": title,
                "de_id": de_id,
            }
        )
    elif desktop.get("cosmic_available"):
        badges.append(
            {
                "id": "cosmic",
                "label": "COSMIC",
                "detail": "installed",
                "title": "COSMIC config present — not the active session",
            }
        )

    # Kernel + Mesa — gaming stack versions gamers care about for bug reports
    if kernel:
        badges.append(
            {
                "id": "kernel",
                "label": "Kernel",
                "detail": _kernel_badge_detail(kernel),
                "title": f"Linux {kernel}",
            }
        )
    if mesa.get("present") and mesa.get("version"):
        title_bits = [f"Mesa {mesa.get('version_raw') or mesa['version']}"]
        if mesa.get("package"):
            title_bits.append(mesa["package"])
        if mesa.get("flavor"):
            title_bits.append(mesa["flavor"])
        if mesa.get("source"):
            title_bits.append(f"via {mesa['source']}")
        detail = mesa["version"]
        if mesa.get("flavor") and "kisak" in (mesa.get("flavor") or "").lower():
            detail = f"{mesa['version']} kisak"
        badges.append(
            {
                "id": "mesa",
                "label": "Mesa",
                "detail": detail,
                "title": " · ".join(title_bits),
            }
        )

    return {
        "os": {
            "id": os_id or None,
            "name": name,
            "pretty": pretty,
            "version": version,
            "version_id": version_id or None,
            "is_pop": is_pop,
            "id_like": id_like or None,
        },
        "vendor": {
            "name": vendor or None,
            "product": product or None,
            "product_version": product_version or None,
            "board": board or None,
            "model_short": model_short or None,
            "is_system76": is_s76,
        },
        "desktop": desktop,
        "kernel": kernel or None,
        "mesa": mesa,
        "badges": badges,
        "is_pop": is_pop,
        "is_system76": is_s76,
        "is_cosmic": is_cosmic,
    }
