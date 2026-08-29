# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Hardware graph/dial scale persistence."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pulse_config as pc


def _with_tmp_config(fn):
    orig = pc.CONFIG_PATH
    tmp = Path(tempfile.mkdtemp()) / ".pulse_config.json"
    pc.CONFIG_PATH = tmp
    pc.invalidate_config_cache()
    try:
        return fn(tmp)
    finally:
        pc.CONFIG_PATH = orig
        pc.invalidate_config_cache()


def test_defaults_include_cpu_temp_max():
    def inner(_tmp):
        cfg = pc.load_config()
        assert cfg["hw_scales"]["cpu_temp_max_c"] == 105
        assert cfg["hw_scales"]["cpu_temp_min_c"] == 30
        assert pc.get_hw_scales()["gpu_power_max_w"] == 355
    _with_tmp_config(inner)


def test_cpu_temp_max_clamped_and_saved():
    def inner(tmp):
        cfg = pc.save_config(hw_scales={"cpu_temp_max_c": 95})
        assert cfg["hw_scales"]["cpu_temp_max_c"] == 95
        too_high = pc.save_config(hw_scales={"cpu_temp_max_c": 999})
        assert too_high["hw_scales"]["cpu_temp_max_c"] == 120
        data = json.loads(tmp.read_text())
        assert data["hw_scales"]["cpu_temp_max_c"] == 120
        assert data["hw_scales"]["cpu_temp_min_c"] == 30
    _with_tmp_config(inner)


def test_temp_min_stays_below_max():
    def inner(_tmp):
        cfg = pc.save_config(hw_scales={"cpu_temp_max_c": 60, "cpu_temp_min_c": 55})
        assert cfg["hw_scales"]["cpu_temp_max_c"] == 60
        assert cfg["hw_scales"]["cpu_temp_min_c"] <= 50
    _with_tmp_config(inner)


def run_all() -> None:
    test_defaults_include_cpu_temp_max()
    test_cpu_temp_max_clamped_and_saved()
    test_temp_min_stays_below_max()
    print("test_hw_scales: ok")


if __name__ == "__main__":
    run_all()
