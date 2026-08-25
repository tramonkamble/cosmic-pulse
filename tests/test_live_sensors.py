# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Live lab sensor coalescing — GPU engines, CCD pick, DRAM estimate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import _engine_pct, memory_bandwidth


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


def run_all() -> None:
    test_engine_pct_prefers_any_live_counter()
    test_dram_idle_not_inflated_by_minor_faults()
    print("test_live_sensors: ok")


if __name__ == "__main__":
    run_all()
