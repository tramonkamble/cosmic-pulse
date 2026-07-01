# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""GPU architecture thermal profiles — junction limits vary by design."""

from __future__ import annotations

import re
import subprocess
from typing import Any

# Architectures that commonly benefit from a custom fan curve before junction climbs.
FAN_CURVE_ARCHITECTURES = (
    "RDNA2 (RX 6000 series)",
    "RDNA1 / Polaris (RX 5000 and older)",
    "NVIDIA GeForce (RTX 20/30/40)",
)

_ARCHITECTURES: dict[str, dict[str, Any]] = {
    "rdna3": {
        "arch": "rdna3",
        "label": "RDNA3",
        "models": (
            "RX 7900 XTX", "RX 7900 XT", "RX 7800 XT", "RX 7700 XT",
            "RX 7600 XT", "RX 7600",
        ),
        "warm_c": None,
        "hot_c": 110,
        "throttle_c": 110,
        "fan_curve_helpful": False,
        "design_note": (
            "RDNA3 (RX 7000) uses junction as the throttle sensor and is designed to run "
            "near its thermal limit under load. Junction readings around 95–108°C are normal — "
            "not a sign you need a fan curve."
        ),
        "fan_curve_note": (
            "Fan-curve tuning helps most on RDNA2, Polaris, and NVIDIA cards that target lower "
            "junction temps. RDNA3 usually does not need this unless you are hitting the throttle."
        ),
    },
    "rdna2": {
        "arch": "rdna2",
        "label": "RDNA2",
        "models": (
            "RX 6950 XT", "RX 6900 XT", "RX 6800 XT", "RX 6800", "RX 6700 XT",
            "RX 6650 XT", "RX 6600 XT", "RX 6600", "RX 6500 XT",
        ),
        "warm_c": 92,
        "hot_c": 105,
        "throttle_c": 110,
        "fan_curve_helpful": True,
        "design_note": "RDNA2 junction above ~92°C under sustained load often benefits from airflow or a fan curve.",
        "fan_curve_note": (
            "RDNA2 cards often gain headroom from a steeper fan curve in CoreCtrl before junction "
            "approaches 105°C."
        ),
    },
    "nvidia": {
        "arch": "nvidia",
        "label": "NVIDIA",
        "models": (
            "RTX 4090", "RTX 4080", "RTX 4070", "RTX 4060",
            "RTX 3090", "RTX 3080", "RTX 3070", "RTX 3060",
            "GTX 1660", "GTX 1080",
        ),
        "warm_c": 83,
        "hot_c": 90,
        "throttle_c": 93,
        "fan_curve_helpful": True,
        "design_note": "NVIDIA hotspot/junction above ~83°C under load is a good time to review fan curve or case airflow.",
        "fan_curve_note": (
            "GeForce cards often benefit from a custom fan curve (MSI Afterburner, CoolerControl, "
            "or vendor tool) before hotspot temps climb."
        ),
    },
}

_DEFAULT: dict[str, Any] = {
    "arch": "default",
    "label": "GPU",
    "warm_c": 90,
    "hot_c": 100,
    "throttle_c": 105,
    "fan_curve_helpful": True,
    "design_note": "High junction under load may warrant better airflow, a fan curve, or lower graphics settings.",
    "fan_curve_note": (
        f"Custom fan curves help most on: {', '.join(FAN_CURVE_ARCHITECTURES)}."
    ),
}


def _normalize_model(model: str) -> str:
    return re.sub(r"\s+", " ", (model or "").strip().upper())


def profile_for_model(model: str) -> dict[str, Any]:
    """Return thermal profile dict for a detected GPU model string."""
    norm = _normalize_model(model)
    if not norm:
        return {**_DEFAULT, "model": model or "GPU"}

    for spec in _ARCHITECTURES.values():
        for name in spec["models"]:
            if _normalize_model(name) in norm or norm in _normalize_model(name):
                return {
                    **spec,
                    "model": model,
                    "fan_curve_architectures": FAN_CURVE_ARCHITECTURES,
                }

    if "NVIDIA" in norm or "GEFORCE" in norm or "RTX" in norm or "GTX" in norm:
        return {**_ARCHITECTURES["nvidia"], "model": model, "fan_curve_architectures": FAN_CURVE_ARCHITECTURES}

    if "RADEON" in norm or "RX " in norm or "AMD" in norm:
        return {**_ARCHITECTURES["rdna2"], "model": model, "fan_curve_architectures": FAN_CURVE_ARCHITECTURES}

    return {**_DEFAULT, "model": model, "fan_curve_architectures": FAN_CURVE_ARCHITECTURES}


def infer_gpu_model() -> str:
    """Best-effort GPU model string (matches server detect_gpu_spec heuristics)."""
    model = "RX 7900 XT"
    try:
        out = subprocess.check_output(["lspci", "-v"], text=True, stderr=subprocess.DEVNULL, timeout=3)
        blob = out.upper()
        for name in (
            "7900 XTX", "7900 XT", "7800 XT", "7700 XT", "7600 XT",
            "6900 XT", "6800 XT", "RTX 4090", "RTX 4080", "RTX 4070",
        ):
            if name in blob:
                if name.startswith("RTX"):
                    return f"GeForce {name}"
                return f"RX {name}"
    except (subprocess.SubprocessError, OSError, ValueError):
        pass
    return model


def junction_ui_class(junction: float | int | None, profile: dict[str, Any] | None) -> str:
    """CSS severity suffix for junction display ('', ' warn', ' hot')."""
    if junction is None:
        return ""
    prof = profile or _DEFAULT
    hot = prof.get("hot_c", 100)
    warm = prof.get("warm_c")
    if junction >= hot:
        return " hot"
    if warm is not None and junction >= warm:
        return " warn"
    return ""