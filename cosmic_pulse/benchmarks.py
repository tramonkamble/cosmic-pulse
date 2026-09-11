# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Reference hardware tiers for live comparison (gaming / simulation workloads)."""

from __future__ import annotations

import re

from .hardware_profiles import GPU_ALIASES, gpu_tier_list
from .league_index import apply_cpu_scores, league_meta, memory_tier_score

# Scores overwritten from cosmic_pulse/data/league_index.json (Tom's Hardware).
CPU_TIERS: list[dict] = apply_cpu_scores(
    [
        {"name": "Ryzen 5 5600X", "score": 54, "class": "mid"},
        {"name": "Ryzen 5 7600X", "score": 66, "class": "mid"},
        {"name": "Ryzen 9 7900X", "score": 69, "class": "mid"},
        {"name": "Ryzen 9 7900X3D", "score": 77, "class": "upper"},
        {"name": "Ryzen 7 5800X3D", "score": 70, "class": "upper"},
        {"name": "Ryzen 7 7700X", "score": 71, "class": "upper"},
        {"name": "Ryzen 9 7950X", "score": 71, "class": "upper"},
        {"name": "Core i7-13700K", "score": 76, "class": "upper"},
        {"name": "Core i9-14900K", "score": 78, "class": "upper"},
        {"name": "Ryzen 5 7600X3D", "score": 81, "class": "upper"},
        {"name": "Ryzen 7 7800X3D", "score": 86, "class": "enthusiast"},
        {"name": "Ryzen 7 9800X3D", "score": 97, "class": "flagship"},
        {"name": "Ryzen 7 9850X3D", "score": 100, "class": "flagship"},
        {"name": "Threadripper 9970X", "score": 72, "class": "workstation"},
    ]
)

GPU_TIERS: list[dict] = gpu_tier_list()

MEM_TIERS: list[dict] = [
    {"name": "DDR4-3200 dual", "mts": 3200, "channels": 2, "peak_gbps": 51.2, "class": "legacy"},
    {"name": "DDR5-4800 dual", "mts": 4800, "channels": 2, "peak_gbps": 76.8, "class": "entry"},
    {"name": "DDR5-5200 dual", "mts": 5200, "channels": 2, "peak_gbps": 83.2, "class": "mid"},
    {"name": "DDR5-5600 dual", "mts": 5600, "channels": 2, "peak_gbps": 89.6, "class": "upper"},
    {
        "name": "DDR5-6000 dual",
        "mts": 6000,
        "channels": 2,
        "peak_gbps": 96.0,
        "class": "enthusiast",
    },
    {
        "name": "G.Skill Flare X5 6000",
        "mts": 6000,
        "channels": 2,
        "peak_gbps": 96.0,
        "class": "enthusiast",
    },
    {
        "name": "DDR5-6400 dual",
        "mts": 6400,
        "channels": 2,
        "peak_gbps": 102.4,
        "class": "enthusiast",
    },
    {"name": "DDR5-7200 dual", "mts": 7200, "channels": 2, "peak_gbps": 115.2, "class": "flagship"},
]

# Composite reference builds for "vs" bars (same published index as the SKU table).
REFERENCE_BUILDS = {
    "average_pc": {"label": "Typical 1440p PC", "cpu": 66.0, "gpu": 46.5, "mem": 80.0},
    "enthusiast": {"label": "Enthusiast build", "cpu": 85.6, "gpu": 73.1, "mem": 100.0},
    "flagship": {"label": "Flagship 2026", "cpu": 100.0, "gpu": 100.0, "mem": 100.0},
}

CPU_ALIASES = {
    "9850x3d": "Ryzen 7 9850X3D",
    "9800x3d": "Ryzen 7 9800X3D",
    "7900x3d": "Ryzen 9 7900X3D",
    "7900x": "Ryzen 9 7900X",
    "7950x": "Ryzen 9 7950X",
    "7700x": "Ryzen 7 7700X",
    "7600x3d": "Ryzen 5 7600X3D",
    "7600x": "Ryzen 5 7600X",
    "7800x3d": "Ryzen 7 7800X3D",
    "14900k": "Core i9-14900K",
    "13700k": "Core i7-13700K",
}


def dram_peak_gbps(mts: int, channels: int = 2) -> float:
    return round(mts * channels * 64 / 8 / 1000, 1)


def _match_tier(name: str, tiers: list[dict], aliases: dict[str, str]) -> dict:
    low = name.lower()
    for key, canonical in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        if key in low:
            low = canonical.lower()
            break
    for t in tiers:
        if t["name"].lower() == low:
            return t
    ordered = sorted(tiers, key=lambda t: -len(t["name"]))
    for t in ordered:
        tn = t["name"].lower()
        if tn in low or low in tn:
            return t
    best = tiers[0]
    for t in tiers:
        if any(part in low for part in t["name"].lower().split()):
            best = t
    return best


def cpu_identity(cpu_model: str) -> dict:
    raw = (cpu_model or "").strip()
    brand = "AMD" if "amd" in raw.lower() else "Intel" if "intel" in raw.lower() else None
    short = re.sub(r"^(AMD|Intel)\s+", "", raw, flags=re.I)
    short = re.sub(r"\s+\d+-Core Processor$", "", short, flags=re.I).strip()
    label = f"{brand} · {short}" if brand and short else raw
    return {"brand": brand, "model": short or raw, "label": label, "raw": raw}


def memory_identity(mem_spec: dict) -> dict:
    brand = mem_spec.get("manufacturer") or mem_spec.get("brand")
    kit = mem_spec.get("kit")
    label = mem_spec.get("label") or (f"{brand} {kit}".strip() if brand or kit else "System RAM")
    return {
        "brand": brand,
        "kit": kit,
        "label": label,
        "part": mem_spec.get("part"),
        "profiles": mem_spec.get("profiles"),
    }


_S76_PRODUCTS = (
    "thelio",
    "meerkat",
    "lemp",
    "lemur",
    "galago",
    "oryx",
    "darter",
    "pangolin",
    "bonobo",
    "serval",
    "addax",
    "kudu",
)

# DMI placeholders — DIY boards and unfinished firmware dump these.
_DMI_JUNK = frozenset(
    {
        "",
        "unknown",
        "none",
        "n/a",
        "na",
        "null",
        "not specified",
        "not available",
        "default string",
        "to be filled by o.e.m.",
        "to be filled by o.e.m",
        "system product name",
        "system version",
        "system manufacturer",
        "chassis manufacturer",
        "o.e.m.",
        "oem",
        "undefined",
        "empty",
    }
)

# Chassis OEMs (laptops / prebuilts). Motherboard houses are not these.
_CHASSIS_OEMS: tuple[tuple[str, str], ...] = (
    ("system76", "System76"),
    ("alienware", "Alienware"),
    ("dell", "Dell"),
    ("framework", "Framework"),
    ("lenovo", "Lenovo"),
    ("hewlett-packard", "HP"),
    ("hp inc", "HP"),
    ("microsoft", "Microsoft"),
    ("razer", "Razer"),
    ("acer", "Acer"),
    ("starlabs", "Star Labs"),
    ("star labs", "Star Labs"),
    ("tuxedo", "Tuxedo"),
    ("slimbook", "Slimbook"),
)

_BOARD_VENDOR_RE = re.compile(
    r"asustek|\basus\b|micro-star|\bmsi\b|gigabyte|asrock|biostar|supermicro",
    re.I,
)

# Chipset / board SKUs — personal builds, not a factory chassis.
_BOARD_SKU_RE = re.compile(
    r"\b([abxzwh]\d{3}e?\b|aorus|tomahawk|proart|crosshair|"
    r"strix [abxz]\d|tuf gaming [abxz]|gaming (x|wifi|plus|pro)\b|"
    r"mpg |mag |meg )",
    re.I,
)

_LAPTOP_RE = re.compile(
    r"zephyrus|zenbook|vivobook|expertbook|\bflow\b|katana|raider|"
    r"stealth|vector|titan|\bsword\b|prestige|modern|summit|"
    r"tuf gaming [af]\d|rog strix g\d",
    re.I,
)

_BOARD_VENDOR_BRAND = (
    ("asustek", "ASUS"),
    ("asus", "ASUS"),
    ("micro-star", "MSI"),
    ("msi", "MSI"),
    ("gigabyte", "Gigabyte"),
    ("asrock", "ASRock"),
)


def _dmi_text(value: str) -> str:
    """Strip firmware placeholders and trailing parenthetical junk."""
    text = (value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip(" -")
    if text.lower() in _DMI_JUNK:
        return ""
    return text


def _looks_system76(hay: str) -> bool:
    low = hay.lower()
    if "system76" in low:
        return True
    for name in _S76_PRODUCTS:
        if low.startswith(name) or f" {name}" in low or f"{name}-" in low:
            return True
    return False


def _oem_brand(hay: str) -> str | None:
    low = f" {hay.lower()} "
    if re.search(r"\bapple\b", hay, re.I):
        return "Apple"
    for needle, brand in _CHASSIS_OEMS:
        if needle in low:
            return brand
    return None


def _board_house_brand(vendor: str) -> str | None:
    low = vendor.lower()
    for needle, brand in _BOARD_VENDOR_BRAND:
        if needle in low:
            return brand
    return None


def chassis_identity(
    machine: str,
    hostname: str = "",
    board_vendor: str = "",
    board_name: str = "",
) -> dict:
    """Name the box: System76 / Dell-class OEM / desktop (DIY or unknown).

    ``kind`` is ``system76``, ``oem``, or ``desktop``. Motherboard makers
    (ASUS/MSI/…) with a board SKU are desktops, not a chassis brand.
    """
    vendor = _dmi_text(board_vendor)
    board = _dmi_text(board_name)
    raw_in = (machine or "").strip()
    host = _dmi_text(hostname)
    product = _dmi_text(raw_in) or host
    hay = " ".join(p for p in (vendor, product, board, host) if p)

    brand: str | None = None
    model = product or board or host
    kind = "desktop"

    if _looks_system76(hay):
        brand = "System76"
        kind = "system76"
        model = product or board or host or "System76"
    elif oem := _oem_brand(hay):
        brand = oem
        kind = "oem"
        model = product or board or host or oem
    elif _LAPTOP_RE.search(hay) and (house := _board_house_brand(vendor)):
        brand = house
        kind = "oem"
        model = product or board or host or house
    else:
        kind = "desktop"
        brand = None
        if _BOARD_SKU_RE.search(product) or _BOARD_SKU_RE.search(board) or _BOARD_VENDOR_RE.search(
            vendor
        ):
            model = board or product or host or "Custom PC"
        else:
            model = product or board or host or "Desktop"

    if brand == "System76" and model:
        # "thelio-major-b4-n2" stays; drop a redundant System76 prefix.
        if model.lower().startswith("system76 "):
            model = model[9:].strip()

    label = f"{brand} · {model}" if brand and model else (model or raw_in or host)
    return {
        "brand": brand,
        "model": model,
        "label": label,
        "raw": raw_in or host,
        "vendor": vendor or None,
        "kind": kind,
    }


def rank_label(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def percentile(score: int, tiers: list[dict]) -> int:
    scores = sorted(t["score"] for t in tiers)
    below = sum(1 for s in scores if s < score)
    return min(99, max(1, int(100 * below / max(1, len(scores) - 1))))


def hardware_comparison(
    cpu_model: str,
    gpu_model: str,
    mem_spec: dict,
    snap: dict,
    *,
    gpu_info: dict | None = None,
    machine: str = "",
    hostname: str = "",
    board_vendor: str = "",
    board_name: str = "",
) -> dict:
    cpu_t = _match_tier(cpu_model, CPU_TIERS, CPU_ALIASES)
    gpu_t = _match_tier(gpu_model, GPU_TIERS, GPU_ALIASES)
    cpu_id = cpu_identity(cpu_model)
    mem_id = memory_identity(mem_spec)
    chassis_id = chassis_identity(
        machine, hostname, board_vendor=board_vendor, board_name=board_name
    )
    gi = gpu_info or {}
    gpu_maker = gi.get("maker") or gi.get("partner")
    gpu_board = gi.get("board")
    gpu_label = gi.get("label") or (
        f"{gpu_maker} · {gpu_t['name']}" if gpu_maker else gpu_t["name"]
    )

    mem_mts = mem_spec.get("configured_mts") or mem_spec.get("speed_mts") or 5600
    mem_ch = mem_spec.get("channels") or 2
    mem_peak = mem_spec.get("peak_gbps") or dram_peak_gbps(mem_mts, mem_ch)
    mem_t = min(MEM_TIERS, key=lambda t: abs(t["peak_gbps"] - mem_peak))

    cpu_pct = snap["cpu"]["overall_pct"]
    gpu_pct = snap["gpu"]["discrete"].get("busy_pct") or 0
    vram_gbps = snap["gpu"]["discrete"].get("vram_est_gbps") or 0
    vram_busy = snap["gpu"]["discrete"].get("mem_busy_pct") or 0
    dram_est = snap.get("bandwidth", {}).get("memory", {}).get("dram_est_gbps") or 0
    dram_util = snap.get("bandwidth", {}).get("memory", {}).get("dram_util_pct") or 0

    refs = REFERENCE_BUILDS
    avg = refs["average_pc"]
    enth = refs["enthusiast"]
    flag = refs["flagship"]

    def vs(ref_score: float, yours: float) -> int:
        ref = float(ref_score or 0)
        you = float(yours or 0)
        return round((you - ref) / ref * 100) if ref else 0

    # Live extraction: how much of *your* hardware you're using right now.
    cpu_live = round(cpu_pct, 1)
    gpu_live = round(gpu_pct, 1)
    vram_bw_live_pct = round(vram_busy, 1)
    dram_live_pct = round(dram_util, 1)

    # Session index: weighted live util × tier (capped 100).
    session_index = round(
        min(
            100,
            (cpu_live * 0.35 * cpu_t["score"] / 100)
            + (gpu_live * 0.45 * gpu_t["score"] / 100)
            + (dram_live_pct * 0.20 * mem_t["peak_gbps"] / 96),
        ),
        1,
    )

    mem_score = memory_tier_score(mem_peak)
    composite_tier = round(
        cpu_t["score"] * 0.4 + gpu_t["score"] * 0.45 + mem_score * 0.15, 1
    )
    meta = league_meta()

    return {
        "session_index": session_index,
        "composite_tier": composite_tier,
        "composite_rank": rank_label(int(composite_tier)),
        "sources": {
            "gpu": meta.get("gpu") or {},
            "cpu": meta.get("cpu") or {},
            "memory": meta.get("memory") or {},
        },
        "chassis": chassis_id,
        "cpu": {
            "name": cpu_t["name"],
            "detected": cpu_model,
            "brand": cpu_id["brand"],
            "label": cpu_id["label"],
            "tier_score": cpu_t["score"],
            "tier_rank": rank_label(cpu_t["score"]),
            "percentile": percentile(cpu_t["score"], CPU_TIERS),
            "live_pct": cpu_live,
            "vs_avg_pct": vs(avg["cpu"], cpu_t["score"]),
            "vs_enthusiast_pct": vs(enth["cpu"], cpu_t["score"]),
            "vs_flagship_pct": vs(flag["cpu"], cpu_t["score"]),
            "headroom_pct": round(max(0, 100 - cpu_live), 1),
        },
        "gpu": {
            "name": gpu_t["name"],
            "detected": gpu_model,
            "brand": gi.get("brand") or "AMD",
            "maker": gpu_maker,
            "board": gpu_board,
            "label": gpu_label,
            "tier_score": gpu_t["score"],
            "tier_rank": rank_label(gpu_t["score"]),
            "percentile": percentile(gpu_t["score"], GPU_TIERS),
            "live_pct": gpu_live,
            "vram_gbps_live": vram_gbps,
            "vram_gbps_peak": gpu_t["vram_gbps"],
            "vram_bw_busy_pct": vram_bw_live_pct,
            "vs_avg_pct": vs(avg["gpu"], gpu_t["score"]),
            "vs_enthusiast_pct": vs(enth["gpu"], gpu_t["score"]),
            "vs_flagship_pct": vs(flag["gpu"], gpu_t["score"]),
        },
        "memory": {
            "name": mem_spec.get("label") or mem_t["name"],
            "detected": mem_spec,
            "brand": mem_id["brand"],
            "kit": mem_id["kit"],
            "label": mem_id["label"],
            "tier_score": mem_score,
            "tier_rank": rank_label(int(mem_score)),
            "peak_gbps": mem_peak,
            "live_gbps_est": dram_est,
            "live_pressure_pct": dram_live_pct,
            "vs_avg_pct": vs(avg["mem"], mem_score),
            "vs_enthusiast_pct": vs(enth["mem"], mem_score),
            "vs_flagship_pct": vs(flag["mem"], mem_score),
        },
        "references": refs,
    }
