# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic hardware discovery — portable across System76, generic Linux, and mixed GPU layouts."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# AMD Raphael / Phoenix integrated graphics PCI device IDs (uppercase hex).
_IGPU_PCI_IDS = frozenset({
    "1002:164E",  # Raphael iGPU
    "1002:15BF",  # Phoenix / Hawk Point
    "1002:1900",  # Van Gogh (Steam Deck class)
})

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
        for hint, name in _NVME_VENDOR_HINTS:
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
            for vendor in ("Samsung", "Toshiba", "Kioxia", "Western Digital", "Seagate", "Crucial", "Intel"):
                if vendor.lower() in ctrl.lower():
                    brand = vendor
                    break

        lb = lsblk.get(name, {})
        size = lb.get("size") or ""
        sensor_suffix = pci_to_sensor_suffix(pci_bdf) if pci_bdf else ""
        sensor_chip = f"nvme-pci-{sensor_suffix}" if sensor_suffix else ""

        drives.append({
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
        })

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
            cards.append({
                "card": entry.name,
                "device_path": device_path,
                "driver": driver,
                "pci_id": pci_id,
                "pci_bdf": pci_bdf,
                "sensor_suffix": pci_to_sensor_suffix(pci_bdf) if pci_bdf else "",
                "vram_bytes": _vram_bytes(device_path),
                "igpu": _is_igpu(pci_id),
            })

    igpu = next((c for c in cards if c["igpu"]), None)
    discrete_candidates = [c for c in cards if not c["igpu"]]
    discrete = None
    if discrete_candidates:
        discrete = max(discrete_candidates, key=lambda c: c["vram_bytes"])

    fallback_discrete = Path("/sys/class/drm/card1/device")
    fallback_igpu = Path("/sys/class/drm/card0/device")

    result = {
        "discrete": discrete or {
            "card": "card1",
            "device_path": fallback_discrete,
            "driver": "amdgpu",
            "pci_id": "",
            "pci_bdf": "",
            "sensor_suffix": "0300",
            "vram_bytes": 0,
            "igpu": False,
        },
        "igpu": igpu or {
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
        tiles.append({
            "id": f"nvme_{drive.get('name', i)}",
            "label": short,
            "value": temp,
            "unit": "°C",
            "kind": "temp",
            "hw": "storage",
            "drive": drive,
        })
    return tiles


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