"""Reference hardware tiers for live comparison (gaming / simulation workloads)."""

from __future__ import annotations

import re

# Tier score 0-100 = approximate relative strength for city-builder / AAA gaming.
CPU_TIERS: list[dict] = [
    {"name": "Ryzen 5 5600X", "score": 42, "class": "mid"},
    {"name": "Ryzen 5 7600X", "score": 58, "class": "mid"},
    {"name": "Ryzen 7 5800X3D", "score": 62, "class": "mid"},
    {"name": "Ryzen 7 7700X", "score": 68, "class": "upper"},
    {"name": "Ryzen 7 7800X3D", "score": 74, "class": "upper"},
    {"name": "Ryzen 9 7900X", "score": 82, "class": "enthusiast"},
    {"name": "Ryzen 9 7950X", "score": 88, "class": "enthusiast"},
    {"name": "Core i7-13700K", "score": 80, "class": "enthusiast"},
    {"name": "Core i9-14900K", "score": 90, "class": "flagship"},
    {"name": "Threadripper 9970X", "score": 98, "class": "workstation"},
]

GPU_TIERS: list[dict] = [
    {"name": "GTX 1660 Super", "score": 22, "vram_gbps": 192, "class": "entry"},
    {"name": "RTX 3060 12GB", "score": 38, "vram_gbps": 360, "class": "mid"},
    {"name": "RX 6700 XT", "score": 48, "vram_gbps": 384, "class": "mid"},
    {"name": "RTX 4070", "score": 58, "vram_gbps": 504, "class": "upper"},
    {"name": "RX 7800 XT", "score": 66, "vram_gbps": 624, "class": "upper"},
    {"name": "RTX 4070 Ti Super", "score": 70, "vram_gbps": 672, "class": "upper"},
    {"name": "RX 7900 XT", "score": 76, "vram_gbps": 800, "class": "enthusiast"},
    {"name": "RX 7900 XTX", "score": 85, "vram_gbps": 960, "class": "enthusiast"},
    {"name": "RTX 4080 Super", "score": 82, "vram_gbps": 736, "class": "enthusiast"},
    {"name": "RTX 4090", "score": 92, "vram_gbps": 1008, "class": "flagship"},
    {"name": "RTX 5090", "score": 100, "vram_gbps": 1792, "class": "flagship"},
]

MEM_TIERS: list[dict] = [
    {"name": "DDR4-3200 dual", "mts": 3200, "channels": 2, "peak_gbps": 51.2, "class": "legacy"},
    {"name": "DDR5-4800 dual", "mts": 4800, "channels": 2, "peak_gbps": 76.8, "class": "entry"},
    {"name": "DDR5-5200 dual", "mts": 5200, "channels": 2, "peak_gbps": 83.2, "class": "mid"},
    {"name": "DDR5-5600 dual", "mts": 5600, "channels": 2, "peak_gbps": 89.6, "class": "upper"},
    {"name": "DDR5-6000 dual", "mts": 6000, "channels": 2, "peak_gbps": 96.0, "class": "enthusiast"},
    {"name": "G.Skill Flare X5 6000", "mts": 6000, "channels": 2, "peak_gbps": 96.0, "class": "enthusiast"},
    {"name": "DDR5-6400 dual", "mts": 6400, "channels": 2, "peak_gbps": 102.4, "class": "enthusiast"},
    {"name": "DDR5-7200 dual", "mts": 7200, "channels": 2, "peak_gbps": 115.2, "class": "flagship"},
]

# Composite reference builds for "vs" bars.
REFERENCE_BUILDS = {
    "average_pc": {"label": "Avg gaming PC", "cpu": 58, "gpu": 48, "mem": 83.2},
    "enthusiast": {"label": "Enthusiast build", "cpu": 88, "gpu": 82, "mem": 96.0},
    "flagship": {"label": "Flagship 2025", "cpu": 98, "gpu": 100, "mem": 115.2},
}

CPU_ALIASES = {
    "7900x": "Ryzen 9 7900X",
    "7950x": "Ryzen 9 7950X",
    "7700x": "Ryzen 7 7700X",
    "7600x": "Ryzen 5 7600X",
    "7800x3d": "Ryzen 7 7800X3D",
    "14900k": "Core i9-14900K",
    "13700k": "Core i7-13700K",
}

GPU_ALIASES = {
    "7900 xtx": "RX 7900 XTX",
    "7900 xt": "RX 7900 XT",
    "7800 xt": "RX 7800 XT",
    "4070 ti": "RTX 4070 Ti Super",
    "4080": "RTX 4080 Super",
    "4090": "RTX 4090",
    "5090": "RTX 5090",
    "3060": "RTX 3060 12GB",
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
    label = mem_spec.get("label") or (
        f"{brand} {kit}".strip() if brand or kit else "System RAM"
    )
    return {
        "brand": brand,
        "kit": kit,
        "label": label,
        "part": mem_spec.get("part"),
        "profiles": mem_spec.get("profiles"),
    }


def chassis_identity(machine: str, hostname: str = "") -> dict:
    raw = (machine or hostname or "").strip()
    brand = None
    model = raw
    if raw.lower().startswith("thelio"):
        brand = "System76"
        model = raw.split("(")[0].strip()
    elif "system76" in raw.lower():
        brand = "System76"
    label = f"{brand} · {model}" if brand else raw
    return {"brand": brand, "model": model, "label": label, "raw": raw}


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
) -> dict:
    cpu_t = _match_tier(cpu_model, CPU_TIERS, CPU_ALIASES)
    gpu_t = _match_tier(gpu_model, GPU_TIERS, GPU_ALIASES)
    cpu_id = cpu_identity(cpu_model)
    mem_id = memory_identity(mem_spec)
    chassis_id = chassis_identity(machine, hostname)
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

    def vs(ref_score: int, yours: int) -> int:
        return round((yours - ref_score) / ref_score * 100) if ref_score else 0

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

    composite_tier = round(cpu_t["score"] * 0.4 + gpu_t["score"] * 0.45 + min(100, mem_peak / 1.15) * 0.15, 1)

    return {
        "session_index": session_index,
        "composite_tier": composite_tier,
        "composite_rank": rank_label(int(composite_tier)),
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
            "tier_score": round(min(100, mem_peak / 1.15), 1),
            "tier_rank": rank_label(int(min(100, mem_peak / 1.15))),
            "peak_gbps": mem_peak,
            "live_gbps_est": dram_est,
            "live_pressure_pct": dram_live_pct,
            "vs_avg_pct": vs(avg["mem"], mem_peak),
            "vs_enthusiast_pct": vs(enth["mem"], mem_peak),
            "vs_flagship_pct": vs(flag["mem"], mem_peak),
        },
        "references": refs,
    }