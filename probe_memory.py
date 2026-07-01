#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""One-shot RAM probe — run with sudo to cache exact DIMM specs for the dashboard."""

import json
import re
import subprocess
import sys
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".memory_cache.json"

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
}


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
        populated.append({
            "size_gb": gb,
            "mts": mts,
            "type": s.get("Type", "DDR5"),
            "manufacturer": s.get("Manufacturer", ""),
            "part": s.get("Part Number", "").strip(),
            "locator": s.get("Locator", ""),
        })

    total_gb = sum(x["size_gb"] for x in populated)
    mts_vals = [x["mts"] for x in populated if x["mts"]]
    mts = mts_vals[0] if mts_vals else 0
    channels = 2 if len(populated) >= 2 else 1
    peak = round(mts * channels * 64 / 8 / 1000, 1) if mts else 0
    label = f"DDR5-{mts} {channels}×{populated[0]['size_gb']}GB" if populated else "Unknown"

    mfrs = sorted({s.get("manufacturer", "").strip() for s in populated if s.get("manufacturer")})
    parts = [s.get("part", "").strip() for s in populated if s.get("part")]
    manufacturer = mfrs[0] if len(mfrs) == 1 else (mfrs[0] if mfrs else None)
    part = parts[0] if parts else None
    per = populated[0]["size_gb"] if populated else 0
    rich_label = label
    if manufacturer and mts and per:
        rich_label = f"{manufacturer} {part or 'DDR5'} · DDR5-{mts} · {channels}×{per}GB"

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
        "type": populated[0].get("type", "DDR5") if populated else "DDR5",
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
    # Generic desktop: DDR5 dual-channel estimate when dmidecode is unavailable.
    mts = 5600
    channels = 2
    sticks = 2 if total_gb <= 64 else 4
    peak = round(mts * channels * 64 / 8 / 1000, 1)
    return {
        "source": "inferred",
        "confidence": "estimated",
        "model": model,
        "sticks": [{"size_gb": total_gb // sticks, "mts": mts, "type": "DDR5"}] * sticks,
        "total_gb": total_gb,
        "channels": channels,
        "configured_mts": mts,
        "speed_mts": mts,
        "peak_gbps": peak,
        "label": f"DDR5-{mts} dual · {total_gb}GB (estimated)",
        "type": "DDR5",
        "note": "Run: sudo python3 probe_memory.py — for exact SPD speed",
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
            spec = parse_dmidecode(raw)
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
            print("For exact speed: sudo python3 probe_memory.py", file=sys.stderr)

    CACHE.write_text(json.dumps(spec, indent=2))
    print(json.dumps(spec, indent=2))
    print(f"\nCached → {CACHE}")


if __name__ == "__main__":
    main()