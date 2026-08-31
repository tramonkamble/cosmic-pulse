# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Live lab sensor coalescing — GPU engines, CCD pick, DRAM estimate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import _engine_pct, _parse_hwmon_tree, memory_bandwidth


def test_engine_pct_prefers_any_live_counter():
    assert _engine_pct(0, 8) == 8.0
    assert _engine_pct(50, 0) == 50.0
    assert _engine_pct(None, 8) == 8.0
    assert _engine_pct(90, 40) == 90.0
    assert _engine_pct(0, 0) == 0.0
    assert _engine_pct(None, None) is None


def test_dram_idle_not_inflated_by_minor_faults():
    vm = mock.Mock(percent=36.0, buffers=0, cached=0, active=8 * 1024**3)
    vmstat = {
        "pgfault_per_s": 80_000,
        "pgmajfault_per_s": 0,
        "refault_file_per_s": 0,
        "refault_anon_per_s": 0,
    }
    psi = {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0}
    with (
        mock.patch("server.psutil.virtual_memory", return_value=vm),
        mock.patch("server.swap_rates", return_value={"in_kbps": 0.0, "out_kbps": 0.0}),
        mock.patch("server.vmstat_rates", return_value=vmstat),
        mock.patch("server.psi_read", return_value=psi),
    ):
        bw = memory_bandwidth(cpu_pct=5.0, game_cpu_pct=0.0)
    # ~2% from CPU + ~5% from RAM residency — not the old 22% fault churn.
    assert bw["dram_util_pct"] < 15
    assert bw["dram_est_gbps"] < 20


def test_hwmon_parse_k10_and_amdgpu():
    import tempfile

    root = Path(tempfile.mkdtemp())
    k10 = root / "hwmon6"
    k10.mkdir()
    (k10 / "name").write_text("k10temp\n")
    (k10 / "temp1_input").write_text("64750\n")
    (k10 / "temp1_label").write_text("Tctl\n")
    (k10 / "temp3_input").write_text("64750\n")
    (k10 / "temp3_label").write_text("Tccd1\n")
    gpu = root / "hwmon4"
    gpu.mkdir()
    (gpu / "name").write_text("amdgpu\n")
    (gpu / "temp1_input").write_text("45000\n")
    (gpu / "temp1_label").write_text("edge\n")
    (gpu / "temp2_input").write_text("49000\n")
    (gpu / "temp2_label").write_text("junction\n")
    (gpu / "fan1_input").write_text("568\n")
    (gpu / "fan1_label").write_text("fan1\n")
    (gpu / "power1_average").write_text("23000000\n")
    (gpu / "power1_label").write_text("PPT\n")
    out = _parse_hwmon_tree(root)
    assert out["k10temp:Tctl"] == 64.8 or abs(out["k10temp:Tctl"] - 64.8) < 0.1
    assert "Tccd1" in "".join(out.keys())
    assert any(k.endswith(":edge") and v == 45.0 for k, v in out.items())
    assert any(k.endswith(":junction") and v == 49.0 for k, v in out.items())
    assert any("PPT" in k and abs(float(v) - 23.0) < 0.2 for k, v in out.items())


def run_all() -> None:
    test_engine_pct_prefers_any_live_counter()
    test_dram_idle_not_inflated_by_minor_faults()
    test_hwmon_parse_k10_and_amdgpu()
    print("test_live_sensors: ok")


if __name__ == "__main__":
    run_all()
