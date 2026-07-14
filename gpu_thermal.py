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


def _junction_for_clock_throttle(prof: dict[str, Any]) -> float | None:
    """Min junction (°C) before a clock drop counts as thermal throttling."""
    if prof.get("fan_curve_helpful") is False and prof.get("info_high_c") is not None:
        return float(prof["info_high_c"])
    if prof.get("warm_c") is not None:
        return float(prof["warm_c"])
    hot = prof.get("hot_c", 100)
    return float(hot) - 8


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
    info_high_c = prof.get("info_high_c")
    fan_help = prof.get("fan_curve_helpful", True)
    observed_peak = float(session_peak_mhz or 0)
    # Per-game observed peak only — do not compare against SKU boost (causes false
    # positives when light games run below max clocks at cool junction temps).
    ref_peak = observed_peak if observed_peak >= 800 else 0.0
    junc_thresh = _junction_for_clock_throttle(prof)

    throttling = False
    if (
        gfx
        and ref_peak >= 800
        and busy
        and junc is not None
        and junc_thresh is not None
        and float(junc) >= junc_thresh
        and float(gfx) < ref_peak * 0.90
    ):
        throttling = True

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
        "session_peak_mhz": round(ref_peak) if ref_peak else None,
        "observed_peak_mhz": round(observed_peak) if observed_peak else None,
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
