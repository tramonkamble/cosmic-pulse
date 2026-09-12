#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""One-shot RAM probe — run with sudo to cache exact DIMM specs for the dashboard."""

import json
import re
import subprocess
import sys
from pathlib import Path

def probe_script_path() -> Path:
    """Absolute path to this file — used by sudo / the dashboard hint."""
    return Path(__file__).resolve()


def memory_cache_path() -> Path:
    """Same ``.memory_cache.json`` ``collectors.load_memory_spec()`` reads.

    Must not live next to this module (``cosmic_pulse/.memory_cache.json``) —
    that file is never loaded after the package move.
    """
    try:
        from .paths import data_dir
    except ImportError:
        app_root = Path(__file__).resolve().parent.parent
        if str(app_root) not in sys.path:
            sys.path.insert(0, str(app_root))
        from cosmic_pulse.paths import data_dir

    return data_dir() / ".memory_cache.json"

_BLANK_MFR = {
    "",
    "unknown",
    "not specified",
    "none",
    "to be filled by o.e.m.",
    "oem",
    "null",
    "jedec",
}

# DMI / JEDEC manufacturer strings → display brand.
MFR_ALIASES: tuple[tuple[str, str], ...] = (
    ("gskill international", "G.Skill"),
    ("g.skill", "G.Skill"),
    ("gskill", "G.Skill"),
    ("corsair", "Corsair"),
    ("kingston", "Kingston"),
    ("crucial", "Crucial"),
    ("micron", "Micron"),
    ("samsung", "Samsung"),
    ("sk hynix", "SK hynix"),
    ("hynix", "SK hynix"),
    ("teamgroup", "TeamGroup"),
    ("team group", "TeamGroup"),
    ("patriot", "Patriot"),
    ("adata", "ADATA"),
    ("xpg", "ADATA"),
    ("silicon power", "Silicon Power"),
    ("thermaltake", "Thermaltake"),
    ("geil", "GeIL"),
    ("mushkin", "Mushkin"),
    ("oloy", "OLOy"),
    ("pny", "PNY"),
    ("apacer", "Apacer"),
    ("lexar", "Lexar"),
    ("klevv", "Klevv"),
    ("v-color", "V-Color"),
    ("vcolor", "V-Color"),
    ("timetec", "Timetec"),
    ("acer", "Acer"),
    ("predator", "Acer"),
    ("gigabyte", "Gigabyte"),
    ("aorus", "Gigabyte"),
    ("corsair memory", "Corsair"),
)

# Part-number prefixes when DMI manufacturer is blank. Longer keys first.
PART_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("F5-6000J3038F16G", "G.Skill", "Flare X5"),
    ("F5-6000", "G.Skill", "DDR5-6000"),
    ("F5-", "G.Skill", "DDR5"),
    ("F4-", "G.Skill", "Ripjaws"),
    ("CMK32GX5", "Corsair", "Vengeance"),
    ("CMK", "Corsair", "Vengeance"),
    ("CMH", "Corsair", "Dominator"),
    ("CMT", "Corsair", "Dominator"),
    ("CMW", "Corsair", "Vengeance RGB"),
    ("KF560", "Kingston", "Fury Beast"),
    ("KF5", "Kingston", "Fury"),
    ("KF4", "Kingston", "Fury"),
    ("CT16G48", "Crucial", "Pro"),
    ("CT16G56", "Crucial", "Pro"),
    ("CT32G48", "Crucial", "Pro"),
    ("CT2K", "Crucial", "Pro"),
    ("CT16G", "Crucial", "DDR"),
    ("CT32G", "Crucial", "DDR"),
    ("CT8G", "Crucial", "DDR"),
    ("BL16G", "Crucial", "Ballistix"),
    ("BL", "Crucial", "Ballistix"),
    ("FF3D532", "TeamGroup", "T-Create"),
    ("FF3D", "TeamGroup", "T-Create"),
    ("TFRD", "TeamGroup", "T-Force"),
    ("TFBD", "TeamGroup", "T-Force"),
    ("AX5U6000", "ADATA", "XPG Lancer"),
    ("AX5U", "ADATA", "XPG"),
    ("AX4U", "ADATA", "XPG"),
    ("PVVR532", "Patriot", "Viper Venom"),
    ("PVVR", "Patriot", "Viper"),
    ("PVB", "Patriot", "Viper"),
    ("PVS", "Patriot", "Viper"),
    ("SP005GB", "Silicon Power", "XPOWER"),
    ("SP032GB", "Silicon Power", "XPOWER"),
    ("MD16G", "PNY", "DDR"),
    ("LM16G", "Lexar", "Thor"),
    ("KD48G", "Klevv", "Bolt"),
    ("AHB", "Acer", "Predator"),
)

# Known modules — keyed by sticker part number (single-DIMM SKU).
PART_DB: dict[str, dict] = {
    "F5-6000J3038F16G": {
        "manufacturer": "G.Skill",
        "kit": "Flare X5",
        "kit_sku": "F5-6000J3038F16GX2-FX5",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL30-38-38-96",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
    "CMK32GX5M2B6000C30": {
        "manufacturer": "Corsair",
        "kit": "Vengeance",
        "kit_sku": "CMK32GX5M2B6000C30",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL30",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
    "KF560C36-16": {
        "manufacturer": "Kingston",
        "kit": "Fury Beast",
        "kit_sku": "KF560C36-16",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL36",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
    "CT16G48C40U5": {
        "manufacturer": "Crucial",
        "kit": "Pro",
        "kit_sku": "CT16G48C40U5",
        "mts": 4800,
        "spd_mts": 4800,
        "timings": "CL40",
        "profiles": "JEDEC",
        "size_gb": 16,
    },
    "PVVR532G600C30": {
        "manufacturer": "Patriot",
        "kit": "Viper Venom",
        "kit_sku": "PVVR532G600C30",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL30",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
    "FF3D532G6000HC38ADC01": {
        "manufacturer": "TeamGroup",
        "kit": "T-Create Expert",
        "kit_sku": "FF3D532G6000HC38ADC01",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL38",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
    "AX5U6000C3016G-BCLARBK": {
        "manufacturer": "ADATA",
        "kit": "XPG Lancer",
        "kit_sku": "AX5U6000C3016G-BCLARBK",
        "mts": 6000,
        "spd_mts": 4800,
        "timings": "CL30",
        "profiles": "AMD EXPO / Intel XMP 3.0",
        "size_gb": 16,
    },
}


def normalize_manufacturer(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if _is_blank_mfr(s):
        return None
    if re.fullmatch(r"[0-9A-Fa-f]{4}", s):
        return None
    low = s.lower()
    for needle, name in MFR_ALIASES:
        if needle in low:
            return name
    return s


def lookup_part_prefix(part: str | None) -> dict | None:
    if not part:
        return None
    key = part.strip().upper()
    for prefix, mfr, kit in PART_PREFIXES:
        if key.startswith(prefix.upper()):
            return {"manufacturer": mfr, "kit": kit, "sku": part.strip()}
    return None


def _is_blank_mfr(value: str | None) -> bool:
    return (value or "").strip().lower() in _BLANK_MFR


def lookup_part(part: str | None) -> dict | None:
    if not part:
        return None
    key = part.strip().upper()
    for sku, info in PART_DB.items():
        if sku.upper() in key or key in sku.upper():
            return {**info, "sku": sku}
    return None


def apply_part_db(spec: dict) -> dict:
    """Fill brand/kit from PART_DB without overwriting live DMI speed."""
    if not spec:
        return spec
    part = (spec.get("part") or "").strip()
    if not part:
        for stick in spec.get("sticks") or []:
            if stick.get("part"):
                part = str(stick["part"]).strip()
                break
    info = lookup_part(part)
    prefix = None if info else lookup_part_prefix(part)
    spec["manufacturer"] = normalize_manufacturer(spec.get("manufacturer"))
    for stick in spec.get("sticks") or []:
        stick["manufacturer"] = normalize_manufacturer(stick.get("manufacturer")) or ""

    ram_type = spec.get("type") or "DDR"
    if not info and prefix:
        if not spec.get("manufacturer"):
            spec["manufacturer"] = prefix["manufacturer"]
        if not spec.get("kit") or spec.get("kit") == part:
            spec["kit"] = prefix["kit"]
        for stick in spec.get("sticks") or []:
            if not stick.get("manufacturer"):
                stick["manufacturer"] = prefix["manufacturer"]
        mts = int(spec.get("configured_mts") or spec.get("speed_mts") or 0)
        sticks = spec.get("sticks") or []
        n = len(sticks) or 2
        channels = spec.get("channels") or (2 if n >= 2 else 1)
        per = sticks[0].get("size_gb") if sticks else 0
        mfr = spec.get("manufacturer")
        kit = spec.get("kit")
        if mfr and mts and per:
            spec["label"] = f"{mfr} {kit} · {ram_type}-{mts} · {channels}×{per}GB"
        return spec

    if not info:
        mts = int(spec.get("configured_mts") or spec.get("speed_mts") or 0)
        sticks = spec.get("sticks") or []
        n = len(sticks) or 2
        channels = spec.get("channels") or (2 if n >= 2 else 1)
        per = sticks[0].get("size_gb") if sticks else 0
        mfr = spec.get("manufacturer")
        if mfr and mts and per:
            spec["label"] = f"{mfr} {part or ram_type} · {ram_type}-{mts} · {channels}×{per}GB"
        return spec

    sticks = spec.get("sticks") or []
    seen_loc: dict[str, int] = {}
    for i, stick in enumerate(sticks):
        loc = stick.get("locator") or f"DIMM {i + 1}"
        bank = stick.get("bank") or ""
        if loc in seen_loc:
            stick["locator"] = f"{loc} ({bank})" if bank and bank != loc else f"{loc} #{i + 1}"
        seen_loc.setdefault(loc, i)
    n = len(sticks) or 2
    channels = spec.get("channels") or (2 if n >= 2 else 1)
    per = sticks[0].get("size_gb") if sticks else info["size_gb"]
    configured = int(spec.get("configured_mts") or spec.get("speed_mts") or 0)
    rated = int(info["mts"])
    spec["manufacturer"] = info["manufacturer"]
    spec["kit"] = info["kit"]
    spec["part"] = info.get("sku") or part
    spec["kit_sku"] = info.get("kit_sku")
    spec["timings"] = info.get("timings")
    spec["profiles"] = info.get("profiles")
    spec["rated_mts"] = rated
    spec["spd_mts"] = info.get("spd_mts")
    if configured and rated and configured + 50 < rated:
        spec["label"] = (
            f"{info['manufacturer']} {info['kit']} · DDR5-{configured} (kit {rated}) · {channels}×{per}GB"
        )
        spec["note"] = (
            f"Kit rated DDR5-{rated} {info.get('profiles') or 'EXPO/XMP'}; "
            f"firmware is running JEDEC {configured} MT/s"
        )
        spec["expo_active"] = False
    else:
        show = configured or rated
        spec["label"] = f"{info['manufacturer']} {info['kit']} · DDR5-{show} · {channels}×{per}GB"
        spec["expo_active"] = bool(configured)
        spec.pop("note", None)
    for stick in sticks:
        stick["manufacturer"] = info["manufacturer"]
        stick["rated_mts"] = rated
        stick["spd_mts"] = info.get("spd_mts")
        if not (stick.get("part") or "").strip():
            stick["part"] = info.get("sku")
    return spec


def parse_dmidecode(text: str) -> dict:
    sticks = []
    cur: dict = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Memory Device"):
            if cur:
                sticks.append(cur)
            cur = {}
        elif ":" in s:
            k, v = [x.strip() for x in s.split(":", 1)]
            cur[k] = v
    if cur:
        sticks.append(cur)

    populated = []
    for s in sticks:
        size = s.get("Size", "")
        if not size or "No Module" in size or "Unknown" in size:
            continue
        m = re.search(r"(\d+)\s*GB", size)
        gb = int(m.group(1)) if m else 0
        speed = s.get("Configured Memory Speed") or s.get("Speed") or ""
        mts_m = re.search(r"(\d+)\s*MT/s", speed) or re.search(r"(\d+)\s*MHz", speed)
        mts = int(mts_m.group(1)) if mts_m else 0
        mfr = normalize_manufacturer(s.get("Manufacturer")) or ""
        populated.append(
            {
                "size_gb": gb,
                "mts": mts,
                "type": s.get("Type", "DDR5"),
                "manufacturer": mfr,
                "part": (s.get("Part Number") or "").strip(),
                "locator": (s.get("Locator") or "").strip(),
                "bank": (s.get("Bank Locator") or "").strip(),
            }
        )

    seen_loc: dict[str, int] = {}
    for i, stick in enumerate(populated):
        loc = stick.get("locator") or f"DIMM {i + 1}"
        bank = stick.get("bank") or ""
        if loc in seen_loc:
            stick["locator"] = f"{loc} ({bank})" if bank and bank != loc else f"{loc} #{i + 1}"
        seen_loc.setdefault(loc, i)

    total_gb = sum(x["size_gb"] for x in populated)
    mts_vals = [x["mts"] for x in populated if x["mts"]]
    mts = mts_vals[0] if mts_vals else 0
    channels = 2 if len(populated) >= 2 else 1
    peak = round(mts * channels * 64 / 8 / 1000, 1) if mts else 0
    ram_type = populated[0].get("type") or "DDR" if populated else "DDR"
    ram_type = ram_type if ram_type.upper().startswith("DDR") else "DDR"
    label = f"{ram_type}-{mts} {channels}×{populated[0]['size_gb']}GB" if populated else "Unknown"

    mfrs = sorted({s.get("manufacturer", "").strip() for s in populated if s.get("manufacturer")})
    parts = [s.get("part", "").strip() for s in populated if s.get("part")]
    manufacturer = mfrs[0] if len(mfrs) == 1 else (mfrs[0] if mfrs else None)
    part = parts[0] if parts else None
    per = populated[0]["size_gb"] if populated else 0
    rich_label = label
    if manufacturer and mts and per:
        rich_label = f"{manufacturer} {part or ram_type} · {ram_type}-{mts} · {channels}×{per}GB"

    return {
        "source": "dmidecode",
        "confidence": "exact",
        "sticks": populated,
        "total_gb": total_gb,
        "channels": channels,
        "configured_mts": mts,
        "speed_mts": mts,
        "peak_gbps": peak,
        "label": rich_label,
        "type": populated[0].get("type", "DDR") if populated else "DDR",
        "manufacturer": manufacturer,
        "part": part,
        "kit": part,
    }


def infer_fallback() -> dict:
    mem_kb = int(Path("/proc/meminfo").read_text().split("MemTotal:", 1)[1].split()[0])
    total_raw = mem_kb / 1024 / 1024
    common = [16, 32, 64, 128]
    total_gb = min(common, key=lambda x: abs(x - total_raw))
    product = Path("/sys/class/dmi/id/product_version")
    model = product.read_text().strip() if product.exists() else ""
    # Generic desktop: capacity from /proc; speed unknown without DMI.
    channels = 2
    sticks = 2 if total_gb <= 64 else 4
    return {
        "source": "inferred",
        "confidence": "estimated",
        "model": model,
        "sticks": [{"size_gb": total_gb // sticks, "mts": 0, "type": "DDR"}] * sticks,
        "total_gb": total_gb,
        "channels": channels,
        "configured_mts": 0,
        "speed_mts": 0,
        "peak_gbps": 0,
        "label": f"{total_gb}GB system RAM (estimated)",
        "type": "DDR",
        "note": f"Run: sudo python3 {probe_script_path()} — for exact SPD speed",
    }


def spec_from_part(part: str, sticks: int = 2) -> dict | None:
    key = part.strip().upper()
    for sku, info in PART_DB.items():
        if sku.upper() in key or key in sku.upper():
            channels = 2 if sticks >= 2 else 1
            total = info["size_gb"] * sticks
            mts = info["mts"]
            peak = round(mts * channels * 64 / 8 / 1000, 1)
            stick_list = [
                {
                    "size_gb": info["size_gb"],
                    "mts": mts,
                    "spd_mts": info.get("spd_mts"),
                    "type": "DDR5",
                    "manufacturer": info["manufacturer"],
                    "part": sku,
                    "timings": info.get("timings", "").replace("CL", ""),
                }
                for _ in range(sticks)
            ]
            return {
                "source": "user_part_number",
                "confidence": "exact",
                "manufacturer": info["manufacturer"],
                "kit": info["kit"],
                "part": sku,
                "kit_sku": info.get("kit_sku"),
                "sticks": stick_list,
                "total_gb": total,
                "channels": channels,
                "configured_mts": mts,
                "speed_mts": mts,
                "spd_mts": info.get("spd_mts"),
                "peak_gbps": peak,
                "timings": info.get("timings"),
                "profiles": info.get("profiles"),
                "label": f"{info['manufacturer']} {info['kit']} · DDR5-{mts} · {sticks}×{info['size_gb']}GB",
                "type": "DDR5",
            }
    return None


def main():
    spec = None
    if len(sys.argv) > 1:
        spec = spec_from_part(sys.argv[1])
    if sys.platform == "linux" and not spec:
        try:
            raw = subprocess.check_output(
                ["dmidecode", "-t", "memory"], text=True, timeout=5, stderr=subprocess.DEVNULL
            )
            spec = apply_part_db(parse_dmidecode(raw))
            if not spec.get("sticks"):
                spec = None
        except (subprocess.SubprocessError, OSError, PermissionError):
            spec = None

    if not spec:
        spec = infer_fallback()
        if not sys.stdin.isatty():
            pass
        elif spec["confidence"] != "exact":
            print("Could not read DMI (need root). Wrote estimated spec.", file=sys.stderr)
            print(f"For exact speed: sudo python3 {probe_script_path()}", file=sys.stderr)

    cache = memory_cache_path()
    cache.write_text(json.dumps(spec, indent=2))
    print(json.dumps(spec, indent=2))
    print(f"\nCached → {cache}")


if __name__ == "__main__":
    main()
