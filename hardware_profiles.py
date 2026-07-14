# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Unified hardware profiles — GPU families, SKU tiers, thermal behavior, detection."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

# Architecture families: thermal semantics and fix-tool hints (no per-rig hardcoding).
GPU_FAMILIES: dict[str, dict[str, Any]] = {
    "rdna3": {
        "id": "rdna3",
        "label": "RDNA3",
        "vendor": "amd",
        "primary_temp": "junction",
        "warm_c": None,
        "info_high_c": 95,
        "hot_c": 110,
        "throttle_c": 110,
        "fan_curve_helpful": False,
        "fix_tools": ("corectrl",),
        "design_note": (
            "RDNA3 (RX 7000) uses junction as the throttle sensor and is designed to run "
            "near its thermal limit under load. Junction readings around 95–108°C are normal — "
            "not a sign you need a fan curve."
        ),
        "fan_curve_note": (
            "Fan-curve tuning helps most on RDNA2, Polaris, and NVIDIA cards that target lower "
            "junction temps. RDNA3 usually does not need this unless you are hitting the throttle."
        ),
        "default_vram_gbps": 624.0,
    },
    "rdna2": {
        "id": "rdna2",
        "label": "RDNA2",
        "vendor": "amd",
        "primary_temp": "junction",
        "warm_c": 92,
        "hot_c": 105,
        "throttle_c": 110,
        "fan_curve_helpful": True,
        "fix_tools": ("corectrl",),
        "design_note": (
            "RDNA2 junction above ~92°C under sustained load often benefits from airflow or a fan curve."
        ),
        "fan_curve_note": (
            "RDNA2 cards often gain headroom from a steeper fan curve in CoreCtrl before junction "
            "approaches 105°C."
        ),
        "default_vram_gbps": 384.0,
    },
    "rdna1": {
        "id": "rdna1",
        "label": "RDNA1",
        "vendor": "amd",
        "primary_temp": "junction",
        "warm_c": 90,
        "hot_c": 100,
        "throttle_c": 110,
        "fan_curve_helpful": True,
        "fix_tools": ("corectrl",),
        "design_note": (
            "RDNA1 (RX 5000) targets lower junction temps than RDNA3. Above ~90°C under load, "
            "check airflow or a CoreCtrl fan curve."
        ),
        "fan_curve_note": (
            "RX 5700-class cards respond well to a custom fan curve before junction climbs past 100°C."
        ),
        "default_vram_gbps": 448.0,
    },
    "polaris": {
        "id": "polaris",
        "label": "Polaris / GCN",
        "vendor": "amd",
        "primary_temp": "edge",
        "warm_c": 78,
        "hot_c": 88,
        "throttle_c": 95,
        "fan_curve_helpful": True,
        "fix_tools": ("corectrl",),
        "design_note": (
            "Polaris-era cards (RX 500/400 series) throttle on edge temp more than junction. "
            "Traditional fixed-core behavior — a steeper fan curve is often worthwhile above ~78°C edge."
        ),
        "fan_curve_note": (
            "Polaris cards use simpler fixed boost behavior; CoreCtrl fan curves are the main lever "
            "before edge temp passes ~85°C."
        ),
        "default_vram_gbps": 256.0,
    },
    "nvidia": {
        "id": "nvidia",
        "label": "NVIDIA GeForce",
        "vendor": "nvidia",
        "primary_temp": "hotspot",
        "warm_c": 83,
        "hot_c": 90,
        "throttle_c": 93,
        "fan_curve_helpful": True,
        "fix_tools": ("coolercontrol", "afterburner"),
        "design_note": (
            "NVIDIA hotspot/junction above ~83°C under load is a good time to review fan curve or case airflow."
        ),
        "fan_curve_note": (
            "GeForce cards often benefit from a custom fan curve (CoolerControl, MSI Afterburner, "
            "or vendor tool) before hotspot temps climb."
        ),
        "default_vram_gbps": 360.0,
    },
    "default": {
        "id": "default",
        "label": "GPU",
        "vendor": None,
        "primary_temp": "junction",
        "warm_c": 90,
        "hot_c": 100,
        "throttle_c": 105,
        "fan_curve_helpful": True,
        "fix_tools": ("corectrl", "coolercontrol"),
        "design_note": (
            "High junction under load may warrant better airflow, a fan curve, or lower graphics settings."
        ),
        "fan_curve_note": None,
        "default_vram_gbps": 400.0,
    },
}

# SKU table: league tier + VRAM peak + pattern matching. Sorted at load by pattern length.
GPU_SKUS: list[dict[str, Any]] = [
    {
        "name": "RX 7900 XTX",
        "family": "rdna3",
        "score": 85,
        "vram_gbps": 960,
        "class": "enthusiast",
        "patterns": ("7900 XTX", "7900XTX"),
        "boost_mhz": 2500,
    },
    {
        "name": "RX 7900 XT",
        "family": "rdna3",
        "score": 76,
        "vram_gbps": 800,
        "class": "enthusiast",
        "patterns": ("7900 XT", "7900XT"),
        "boost_mhz": 2400,
    },
    {
        "name": "RX 7800 XT",
        "family": "rdna3",
        "score": 66,
        "vram_gbps": 624,
        "class": "upper",
        "patterns": ("7800 XT", "7800XT"),
    },
    {
        "name": "RX 7700 XT",
        "family": "rdna3",
        "score": 60,
        "vram_gbps": 432,
        "class": "upper",
        "patterns": ("7700 XT", "7700XT"),
    },
    {
        "name": "RX 7600 XT",
        "family": "rdna3",
        "score": 52,
        "vram_gbps": 288,
        "class": "mid",
        "patterns": ("7600 XT", "7600XT"),
    },
    {
        "name": "RX 7600",
        "family": "rdna3",
        "score": 46,
        "vram_gbps": 288,
        "class": "mid",
        "patterns": ("RX 7600",),
    },
    {
        "name": "RX 6950 XT",
        "family": "rdna2",
        "score": 72,
        "vram_gbps": 576,
        "class": "enthusiast",
        "patterns": ("6950 XT", "6950XT"),
    },
    {
        "name": "RX 6900 XT",
        "family": "rdna2",
        "score": 70,
        "vram_gbps": 512,
        "class": "enthusiast",
        "patterns": ("6900 XT", "6900XT"),
    },
    {
        "name": "RX 6800 XT",
        "family": "rdna2",
        "score": 64,
        "vram_gbps": 512,
        "class": "upper",
        "patterns": ("6800 XT", "6800XT"),
    },
    {
        "name": "RX 6800",
        "family": "rdna2",
        "score": 58,
        "vram_gbps": 512,
        "class": "upper",
        "patterns": ("RX 6800",),
    },
    {
        "name": "RX 6700 XT",
        "family": "rdna2",
        "score": 48,
        "vram_gbps": 384,
        "class": "mid",
        "patterns": ("6700 XT", "6700XT"),
    },
    {
        "name": "RX 6650 XT",
        "family": "rdna2",
        "score": 42,
        "vram_gbps": 280,
        "class": "mid",
        "patterns": ("6650 XT", "6650XT"),
    },
    {
        "name": "RX 6600 XT",
        "family": "rdna2",
        "score": 40,
        "vram_gbps": 256,
        "class": "mid",
        "patterns": ("6600 XT", "6600XT"),
    },
    {
        "name": "RX 6600",
        "family": "rdna2",
        "score": 36,
        "vram_gbps": 224,
        "class": "mid",
        "patterns": ("RX 6600",),
    },
    {
        "name": "RX 6500 XT",
        "family": "rdna2",
        "score": 28,
        "vram_gbps": 144,
        "class": "entry",
        "patterns": ("6500 XT", "6500XT"),
    },
    {
        "name": "RX 5700 XT",
        "family": "rdna1",
        "score": 44,
        "vram_gbps": 448,
        "class": "mid",
        "patterns": ("5700 XT", "5700XT"),
    },
    {
        "name": "RX 5700",
        "family": "rdna1",
        "score": 40,
        "vram_gbps": 448,
        "class": "mid",
        "patterns": ("RX 5700",),
    },
    {
        "name": "RX 5600 XT",
        "family": "rdna1",
        "score": 34,
        "vram_gbps": 288,
        "class": "mid",
        "patterns": ("5600 XT", "5600XT"),
    },
    {
        "name": "RX 580",
        "family": "polaris",
        "score": 24,
        "vram_gbps": 256,
        "class": "entry",
        "patterns": ("RX 580", "RADEON RX 580"),
    },
    {
        "name": "RX 570",
        "family": "polaris",
        "score": 20,
        "vram_gbps": 224,
        "class": "entry",
        "patterns": ("RX 570",),
    },
    {
        "name": "RX 480",
        "family": "polaris",
        "score": 18,
        "vram_gbps": 256,
        "class": "entry",
        "patterns": ("RX 480",),
    },
    {
        "name": "RTX 5090",
        "family": "nvidia",
        "score": 100,
        "vram_gbps": 1792,
        "class": "flagship",
        "patterns": ("RTX 5090", "5090"),
    },
    {
        "name": "RTX 4090",
        "family": "nvidia",
        "score": 92,
        "vram_gbps": 1008,
        "class": "flagship",
        "patterns": ("RTX 4090", "4090"),
    },
    {
        "name": "RTX 4080 Super",
        "family": "nvidia",
        "score": 82,
        "vram_gbps": 736,
        "class": "enthusiast",
        "patterns": ("RTX 4080 SUPER", "4080 SUPER", "RTX 4080", "4080"),
    },
    {
        "name": "RTX 4070 Ti Super",
        "family": "nvidia",
        "score": 70,
        "vram_gbps": 672,
        "class": "upper",
        "patterns": ("4070 TI SUPER", "4070 TI", "4070TI"),
    },
    {
        "name": "RTX 4070",
        "family": "nvidia",
        "score": 58,
        "vram_gbps": 504,
        "class": "upper",
        "patterns": ("RTX 4070",),
    },
    {
        "name": "RTX 4060",
        "family": "nvidia",
        "score": 44,
        "vram_gbps": 272,
        "class": "mid",
        "patterns": ("RTX 4060", "4060"),
    },
    {
        "name": "RTX 3090",
        "family": "nvidia",
        "score": 78,
        "vram_gbps": 936,
        "class": "enthusiast",
        "patterns": ("RTX 3090", "3090"),
    },
    {
        "name": "RTX 3080",
        "family": "nvidia",
        "score": 68,
        "vram_gbps": 760,
        "class": "upper",
        "patterns": ("RTX 3080", "3080"),
    },
    {
        "name": "RTX 3070",
        "family": "nvidia",
        "score": 54,
        "vram_gbps": 448,
        "class": "upper",
        "patterns": ("RTX 3070", "3070"),
    },
    {
        "name": "RTX 3060 12GB",
        "family": "nvidia",
        "score": 38,
        "vram_gbps": 360,
        "class": "mid",
        "patterns": ("RTX 3060", "3060"),
    },
    {
        "name": "GTX 1660 Super",
        "family": "nvidia",
        "score": 22,
        "vram_gbps": 192,
        "class": "entry",
        "patterns": ("1660 SUPER", "GTX 1660", "1660"),
    },
    {
        "name": "GTX 1080",
        "family": "nvidia",
        "score": 26,
        "vram_gbps": 320,
        "class": "entry",
        "patterns": ("GTX 1080", "1080 TI", "1080TI"),
    },
]

GPU_ALIASES: dict[str, str] = {
    "7900 xtx": "RX 7900 XTX",
    "7900 xt": "RX 7900 XT",
    "7800 xt": "RX 7800 XT",
    "7700 xt": "RX 7700 XT",
    "4070 ti": "RTX 4070 Ti Super",
    "4080": "RTX 4080 Super",
    "4090": "RTX 4090",
    "5090": "RTX 5090",
    "3060": "RTX 3060 12GB",
    "5700 xt": "RX 5700 XT",
    "6800 xt": "RX 6800 XT",
    "6900 xt": "RX 6900 XT",
}

_PATTERN_INDEX: list[tuple[str, dict[str, Any]]] | None = None


def _fan_curve_architectures() -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for fam in GPU_FAMILIES.values():
        if not fam.get("fan_curve_helpful"):
            continue
        label = fam.get("label", "")
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return tuple(labels)


FAN_CURVE_ARCHITECTURES = _fan_curve_architectures()

# Per-family fix tooling — used by fix_scripts, apply_fix, and tuning_actions.
FIX_TOOL_SPECS: dict[str, dict[str, str]] = {
    "corectrl": {
        "binary": "corectrl",
        "label": "CoreCtrl",
        "install": "sudo apt install corectrl",
        "note": "AMD fan curve GUI — best on RDNA2, RDNA1, and Polaris",
    },
    "coolercontrol": {
        "binary": "coolercontrol",
        "label": "CoolerControl",
        "install": "See https://docs.coolercontrol.org — distro packages or AppImage",
        "note": "Linux fan control for NVIDIA and some AMD boards",
    },
    "afterburner": {
        "binary": "",
        "label": "MSI Afterburner",
        "install": "Windows dual-boot or vendor tool — on Linux use CoolerControl",
        "note": "NVIDIA fan curves on Windows; on Linux prefer CoolerControl",
    },
}


def iter_fix_tools(profile: dict[str, Any]) -> tuple[str, ...]:
    tools = profile.get("fix_tools")
    if tools:
        return tuple(tools)
    vendor = profile.get("vendor")
    if vendor == "nvidia":
        return ("coolercontrol", "afterburner")
    if vendor == "amd":
        return ("corectrl",)
    return ("corectrl", "coolercontrol")


def primary_fix_tool(profile: dict[str, Any]) -> str | None:
    for tool in iter_fix_tools(profile):
        spec = FIX_TOOL_SPECS.get(tool)
        if spec and spec.get("binary") and shutil.which(spec["binary"]):
            return tool
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().upper())


def _pattern_index() -> list[tuple[str, dict[str, Any]]]:
    global _PATTERN_INDEX
    if _PATTERN_INDEX is not None:
        return _PATTERN_INDEX
    rows: list[tuple[str, dict[str, Any]]] = []
    for sku in GPU_SKUS:
        for pat in sku.get("patterns", ()):
            rows.append((_normalize(pat), sku))
    rows.sort(key=lambda r: -len(r[0]))
    _PATTERN_INDEX = rows
    return rows


def _infer_vendor(text: str) -> str | None:
    norm = _normalize(text)
    if "NVIDIA" in norm or "GEFORCE" in norm or "10DE:" in norm:
        return "nvidia"
    if "RADEON" in norm or "AMD" in norm or "1002:" in norm or "RX " in norm:
        return "amd"
    return None


def _infer_family_from_text(text: str, sku: dict[str, Any] | None) -> str:
    if sku:
        return sku["family"]
    norm = _normalize(text)
    vendor = _infer_vendor(text)
    if vendor == "nvidia" or "RTX" in norm or "GTX" in norm:
        return "nvidia"
    if any(p in norm for p in ("7900", "7800", "7700", "7600", "RX 7")):
        return "rdna3"
    if any(p in norm for p in ("6900", "6800", "6700", "6650", "6600", "6500", "RX 6")):
        return "rdna2"
    if any(p in norm for p in ("5700", "5600", "5500", "RX 5")) and "XT" in norm:
        return "rdna1"
    if any(p in norm for p in ("580", "570", "480", "POLARIS")):
        return "polaris"
    if vendor == "amd":
        return "rdna2"
    return "default"


def match_gpu_sku(text: str) -> dict[str, Any] | None:
    """Return best SKU match from probe text (longest pattern wins)."""
    norm = _normalize(text)
    if not norm:
        return None
    for alias_key, canonical in sorted(GPU_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias_key in norm.lower():
            norm = _normalize(canonical)
            break
    for pat, sku in _pattern_index():
        if pat in norm:
            return sku
    return None


def merge_gpu_profile(
    *,
    model: str,
    sku: dict[str, Any] | None,
    family_id: str,
) -> dict[str, Any]:
    """Merge SKU tier data with family thermal/behavior fields."""
    family = GPU_FAMILIES.get(family_id) or GPU_FAMILIES["default"]
    name = sku["name"] if sku else model
    profile: dict[str, Any] = {
        "arch": family["id"],
        "family": family["id"],
        "label": family["label"],
        "vendor": family.get("vendor"),
        "model": model,
        "name": name,
        "primary_temp": family.get("primary_temp", "junction"),
        "warm_c": family.get("warm_c"),
        "info_high_c": family.get("info_high_c"),
        "hot_c": family.get("hot_c"),
        "throttle_c": family.get("throttle_c"),
        "fan_curve_helpful": family.get("fan_curve_helpful", True),
        "fix_tools": family.get("fix_tools", ()),
        "design_note": family.get("design_note", ""),
        "fan_curve_note": family.get("fan_curve_note")
        or (f"Custom fan curves help most on: {', '.join(FAN_CURVE_ARCHITECTURES)}."),
        "fan_curve_architectures": FAN_CURVE_ARCHITECTURES,
    }
    if sku:
        profile.update(
            {
                "tier_score": sku["score"],
                "score": sku["score"],
                "vram_gbps": sku["vram_gbps"],
                "class": sku.get("class", "mid"),
                "boost_mhz": sku.get("boost_mhz"),
            }
        )
    else:
        profile.update(
            {
                "tier_score": None,
                "score": None,
                "vram_gbps": family.get("default_vram_gbps", 400.0),
                "class": None,
            }
        )
    return profile


def resolve_gpu(text: str, *, fallback_model: str | None = None) -> dict[str, Any]:
    """Resolve full GPU profile from any probe string (lspci, glxinfo, model name)."""
    sku = match_gpu_sku(text)
    family_id = _infer_family_from_text(text, sku)
    model = sku["name"] if sku else (fallback_model or _guess_model_label(text, family_id))
    return merge_gpu_profile(model=model, sku=sku, family_id=family_id)


def _guess_model_label(text: str, family_id: str) -> str:
    vendor = _infer_vendor(text)
    family = GPU_FAMILIES.get(family_id) or GPU_FAMILIES["default"]
    if vendor == "nvidia":
        return "NVIDIA GeForce GPU"
    if vendor == "amd":
        return f"AMD Radeon ({family['label']})"
    return "Discrete GPU"


def profile_for_model(model: str) -> dict[str, Any]:
    """Thermal + behavior profile for a known or guessed model string."""
    return resolve_gpu(model, fallback_model=model or "GPU")


def gpu_tier_list() -> list[dict[str, Any]]:
    """League comparison tiers derived from the SKU table."""
    return [
        {
            "name": s["name"],
            "score": s["score"],
            "vram_gbps": s["vram_gbps"],
            "class": s.get("class", "mid"),
            "family": s["family"],
        }
        for s in GPU_SKUS
    ]


def junction_ui_class(junction: float | int | None, profile: dict[str, Any] | None) -> str:
    """CSS severity suffix for junction display ('', ' warn', ' hot')."""
    if junction is None:
        return ""
    prof = profile or merge_gpu_profile(model="GPU", sku=None, family_id="default")
    hot = prof.get("hot_c", 100)
    warm = prof.get("warm_c")
    if junction >= hot:
        return " hot"
    if warm is not None and junction >= warm:
        return " warn"
    return ""


def discrete_gpu_pci() -> str:
    """PCI BDF for the discrete GPU (skip Raphael iGPU)."""
    try:
        out = subprocess.check_output(["lspci", "-D"], text=True, timeout=3)
        for line in out.splitlines():
            if "VGA" not in line:
                continue
            low = line.lower()
            if "1002:" in low and ("164e" in low or "raphael" in low):
                continue
            if "1002:" in low or "10de:" in low:
                return line.split()[0]
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return "0000:03:00.0"


def _gpu_relevant_text(text: str) -> str:
    """Keep VGA / GPU lines so SKU patterns do not match unrelated PCI devices."""
    lines: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(
            token in low
            for token in (
                "vga",
                "3d",
                "display",
                "radeon",
                "geforce",
                "nvidia",
                "amd/ati",
                "1002:",
                "10de:",
                "subsystem",
            )
        ):
            lines.append(line)
    return "\n".join(lines)


def _run_probe(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
    except (subprocess.SubprocessError, OSError, ValueError, FileNotFoundError):
        return ""


def detect_gpu_spec(pci: str | None = None) -> dict[str, Any]:
    """Detect discrete GPU model, partner board, VRAM peak, and full profile from the system."""
    pci = pci or discrete_gpu_pci()
    probe_chunks: list[str] = []
    maker: str | None = None
    board: str | None = None
    brand = "AMD"

    detail = _run_probe(["lspci", "-v", "-s", pci])
    if detail:
        probe_chunks.append(detail)
        for line in detail.splitlines():
            if not line.strip().startswith("Subsystem:"):
                continue
            sub = line.split(":", 1)[1].strip()
            bracket = re.search(r"\[([^\]]+)\]", sub)
            if bracket:
                board = bracket.group(1)
            partner = sub.split("[")[0].strip()
            m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)", partner)
            if m:
                maker = m.group(1)
            break

    probe_chunks.append(_run_probe(["lspci", "-v"]))
    probe_chunks.append(_run_probe(["glxinfo", "-B"]))

    combined = "\n".join(c for c in probe_chunks if c)
    gpu_text = _gpu_relevant_text(combined) or combined
    if _infer_vendor(gpu_text) == "nvidia":
        brand = "NVIDIA"

    profile = resolve_gpu(gpu_text)
    model = profile["model"]
    label = f"{maker} · {model}" if maker else model

    return {
        "model": model,
        "brand": brand,
        "maker": maker,
        "board": board,
        "label": label,
        "vram_peak_gbps": profile.get("vram_gbps") or GPU_FAMILIES["default"]["default_vram_gbps"],
        "pci": pci,
        "family": profile.get("family"),
        "thermal_profile": profile,
        "tier_score": profile.get("tier_score"),
    }


def infer_gpu_model() -> str:
    """Best-effort GPU model string from live probes."""
    return detect_gpu_spec().get("model", "Discrete GPU")
