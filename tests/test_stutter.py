# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Stutter proxy and session rollup tests."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stutter import (
    _window_samples,
    attach_stutter,
    compute_stutter,
    effective_disk_io_wait,
    reset_stutter_state,
)


def _snap(
    *,
    ts: float | None = None,
    pgmaj: float = 0,
    game_id: str | None = None,
    running: bool = False,
) -> dict:
    return {
        "ts": ts if ts is not None else time.time(),
        "bandwidth": {"memory": {"pgmajfault_per_s": pgmaj, "psi_avg10": 0, "psi_io_avg10": 0}},
        "disk": {"write_mbps": 0},
        "memory": {"swap_pct": 0},
        "game_totals": {"game_id": game_id, "running": running},
    }


def test_ema_resets_on_game_change():
    reset_stutter_state()
    high = _snap(pgmaj=120, game_id="730", running=True)
    low = _snap(pgmaj=2, game_id="730", running=True)
    s1 = compute_stutter(high)["score"]
    s2 = compute_stutter(low)["score"]
    assert s2 < s1

    reset_stutter_state()
    other = _snap(pgmaj=2, game_id="440", running=True)
    fresh = compute_stutter(other)
    assert fresh["event"] is False


def test_window_samples_skips_old_history():
    now = 1000.0
    history = [
        {"ts": now - 400, "stutter": {"score": 99}},
        {"ts": now - 250, "stutter": {"score": 50}},
        {"ts": now - 10, "stutter": {"score": 10}},
    ]
    window = _window_samples(history, now, 300)
    assert len(window) == 2
    assert window[0]["stutter"]["score"] == 50


def test_session_stats_uses_short_span_for_rate():
    reset_stutter_state()
    now = 2000.0
    history = [
        {"ts": now - 60, "stutter": {"score": 40, "est_ms": 20, "event": True}},
        {"ts": now - 30, "stutter": {"score": 10, "est_ms": 5, "event": False}},
    ]
    snap = _snap(ts=now, pgmaj=0)
    attach_stutter(snap, history)
    sess = snap["stutter"]["session"]
    assert sess["events"] == 1
    assert sess["hitch_rate_per_min"] == 1.0


def test_effective_disk_io_wait_dampens_zram_psi():
    r = effective_disk_io_wait(
        psi_io=68,
        psi_mem=0,
        disk_busy_pct=2,
        disk_read_mbps=0,
        disk_write_mbps=0,
        cpu_iowait_pct=4.2,
    )
    assert r["zram_dominated"] is True
    assert r["io_wait_pct"] == 4.2


def test_effective_disk_io_wait_tracks_busy_disk():
    r = effective_disk_io_wait(
        psi_io=40,
        psi_mem=2,
        disk_busy_pct=55,
        disk_read_mbps=120,
        disk_write_mbps=30,
        cpu_iowait_pct=6,
    )
    assert r["zram_dominated"] is False
    assert r["io_wait_pct"] >= 40


def test_io_stall_uses_adjusted_wait_not_raw_psi():
    reset_stutter_state()
    snap = _snap(pgmaj=0)
    snap["bandwidth"]["memory"].update({"psi_io_avg10": 68, "io_wait_pct": 4.0})
    st = compute_stutter(snap)
    assert st["components"]["io_stall"] < 25


def test_attach_stutter_populates_session():
    reset_stutter_state()
    snap = _snap(pgmaj=5, game_id="730", running=True)
    attach_stutter(snap, [])
    assert "session" in snap["stutter"]
    assert snap["stutter"]["smoothness"] >= 0


if __name__ == "__main__":
    test_ema_resets_on_game_change()
    test_window_samples_skips_old_history()
    test_session_stats_uses_short_span_for_rate()
    test_effective_disk_io_wait_dampens_zram_psi()
    test_effective_disk_io_wait_tracks_busy_disk()
    test_io_stall_uses_adjusted_wait_not_raw_psi()
    test_attach_stutter_populates_session()
    print("all ok")
