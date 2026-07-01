# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""GPU thermal behavior — profiles, junction UI classes, throttle detection."""

from __future__ import annotations

from typing import Any

from hardware_profiles import (
    FAN_CURVE_ARCHITECTURES,
    infer_gpu_model,
    profile_for_model,
)

__all__ = (
    "FAN_CURVE_ARCHITECTURES",
    "gpu_thermal_state",
    "infer_gpu_model",
    "junction_ui_class",
    "profile_for_model",
)


def gpu_thermal_state(
    g: dict[str, Any],
    profile: dict[str, Any] | None,
    session_peak_mhz: float | int | None = None,
) -> dict[str, Any]:
    """Classify live GPU thermals: by-design band vs actual throttling."""
    prof = profile or profile_for_model("GPU")
    junc = g.get("junction_c")
    gfx = g.get("gfx_mhz")
    busy = (g.get("busy_pct") or 0) >= 40
    throttle_c = prof.get("throttle_c", 110)
    info_high_c = prof.get("info_high_c")
    fan_help = prof.get("fan_curve_helpful", True)
    boost = prof.get("boost_mhz") or 0
    peak = max(float(session_peak_mhz or 0), float(boost))

    throttling = False
    if gfx and peak >= 800 and busy:
        throttling = float(gfx) < peak * 0.90

    by_design = (
        not fan_help
        and junc is not None
        and info_high_c is not None
        and junc >= info_high_c
        and not throttling
    )

    return {
        "throttling": throttling,
        "by_design": by_design,
        "session_peak_mhz": round(peak) if peak else None,
        "info_high_c": info_high_c,
        "fan_curve_helpful": fan_help,
    }


def junction_ui_class(
    junction: float | int | None,
    profile: dict[str, Any] | None,
    thermal_state: dict[str, Any] | None = None,
) -> str:
    """CSS severity suffix for junction display ('', ' info', ' warn', ' hot')."""
    if junction is None:
        return ""
    prof = profile or profile_for_model("GPU")
    state = thermal_state or {}
    if state.get("throttling"):
        return " hot"
    if state.get("by_design"):
        return " info"
    hot = prof.get("hot_c", 100)
    warm = prof.get("warm_c")
    if junction >= hot:
        return " hot"
    if warm is not None and junction >= warm:
        return " warn"
    return ""