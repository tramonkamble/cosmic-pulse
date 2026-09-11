# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Pulse Index scores come from the published Tom's Hardware snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.benchmarks import CPU_ALIASES, CPU_TIERS, _match_tier, hardware_comparison
from cosmic_pulse.hardware_profiles import match_gpu_sku
from cosmic_pulse.league_index import memory_tier_score


def _snap() -> dict:
    return {
        "cpu": {"overall_pct": 8.0},
        "gpu": {"discrete": {"busy_pct": 6.0, "vram_est_gbps": 12.0, "mem_busy_pct": 3.0}},
        "bandwidth": {"memory": {"dram_est_gbps": 9.0, "dram_util_pct": 11.0}},
    }


def test_xtx_is_toms_1440p_raster() -> None:
    sku = match_gpu_sku("XFX Speedster MERC 310 RX 7900 XTX")
    assert sku is not None
    assert abs(float(sku["score"]) - 73.1) < 0.05
    assert sku.get("score_estimated") is False


def test_4090_below_5090() -> None:
    a = match_gpu_sku("GeForce RTX 4090")
    b = match_gpu_sku("GeForce RTX 5090")
    assert a and b
    assert a["score"] < b["score"]
    assert abs(float(b["score"]) - 100.0) < 0.05


def test_7900x_below_7800x3d_for_gaming() -> None:
    x = _match_tier("AMD Ryzen 9 7900X 12-Core Processor", CPU_TIERS, CPU_ALIASES)
    x3d = _match_tier("AMD Ryzen 7 7800X3D 8-Core Processor", CPU_TIERS, CPU_ALIASES)
    assert abs(float(x["score"]) - 69.3) < 0.1
    assert abs(float(x3d["score"]) - 85.6) < 0.1
    assert x["score"] < x3d["score"]


def test_memory_score_vs_ddr5_6000() -> None:
    assert memory_tier_score(96.0) == 100.0
    assert memory_tier_score(76.8) == 80.0
    assert memory_tier_score(0) == 0.0


def test_this_kit_composite_not_inflated() -> None:
    cmp = hardware_comparison(
        "AMD Ryzen 9 7900X 12-Core Processor",
        "RX 7900 XTX",
        {"peak_gbps": 96.0, "configured_mts": 6000, "channels": 2, "label": "DDR5-6000"},
        _snap(),
        gpu_info={"label": "XFX · RX 7900 XTX", "maker": "XFX"},
    )
    # 0.4*69.3 + 0.45*73.1 + 0.15*100 ≈ 74.1
    assert 72 <= cmp["composite_tier"] <= 77
    assert cmp["composite_rank"] in ("B", "A")
    assert cmp["cpu"]["tier_score"] < 80
    assert cmp["gpu"]["tier_score"] < 80
    assert cmp["sources"]["gpu"]["source"].startswith("Tom's Hardware")
    assert "cpu-hierarchy" in cmp["sources"]["cpu"]["url"]


def run_all() -> None:
    test_xtx_is_toms_1440p_raster()
    test_4090_below_5090()
    test_7900x_below_7800x3d_for_gaming()
    test_memory_score_vs_ddr5_6000()
    test_this_kit_composite_not_inflated()
    print("test_league_index: ok")


if __name__ == "__main__":
    run_all()
