# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Game session scoring — exit-trim drops quit/teardown hitching."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse import game_performance as gp
from cosmic_pulse import pulse_config as pc


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


def _snap(
    ts: float,
    *,
    running: bool = True,
    game_id: str = "730",
    hitch: bool = False,
    hitch_ms: float = 80.0,
    score: float = 8.0,
    cpu: float = 20.0,
    gpu: float = 50.0,
) -> dict:
    return {
        "ts": ts,
        "stutter": {
            "score": score,
            "smoothness": 100.0 - score,
            "event": hitch,
            "est_ms": hitch_ms if hitch else 0.0,
        },
        "game_totals": {
            "running": running,
            "game_id": game_id if running else None,
            "game_name": "Test Game",
            "cpu_pct": cpu,
        },
        "gpu": {"discrete": {"busy_pct": gpu}},
        "memory": {"pct": 40.0},
    }


def _play(tracker: gp.GameSessionTracker, n: int, t0: float = 1_000.0, hitch_last: int = 0) -> list:
    saved: list[dict] = []
    with mock.patch.object(gp, "LOAD_GRACE_SEC", 0):
        for i in range(n):
            in_tail = hitch_last > 0 and i >= n - hitch_last
            tracker.tick(
                _snap(
                    t0 + i,
                    hitch=in_tail,
                    hitch_ms=90.0,
                    score=40.0 if in_tail else 6.0,
                ),
                save_session=saved.append,
            )
        tracker.tick(_snap(t0 + n, running=False), save_session=saved.append)
    return saved


def test_exit_trim_drops_quit_hitches():
    tracker = gp.GameSessionTracker()
    with mock.patch.object(gp, "get_session_exit_trim_sec", return_value=10):
        saved = _play(tracker, 60, hitch_last=10)
    assert len(saved) == 1
    row = saved[0]
    assert row["hitch_events"] == 0
    assert row["sample_count"] == 50
    assert row["exit_trim_sec"] == 10.0
    assert row["duration_sec"] == 49.0
    assert row["rating"] >= 85


def test_exit_trim_off_keeps_quit_hitches():
    tracker = gp.GameSessionTracker()
    with mock.patch.object(gp, "get_session_exit_trim_sec", return_value=0):
        saved = _play(tracker, 60, hitch_last=10)
    assert len(saved) == 1
    row = saved[0]
    assert row["hitch_events"] == 10
    assert row["sample_count"] == 60
    assert "exit_trim_sec" not in row
    assert row["rating"] < 85


def test_short_session_keeps_min_samples():
    tracker = gp.GameSessionTracker()
    with mock.patch.object(gp, "get_session_exit_trim_sec", return_value=10):
        saved = _play(tracker, 16, hitch_last=10)
    assert len(saved) == 1
    row = saved[0]
    assert row["sample_count"] == gp.MIN_SESSION_SAMPLES
    assert row["exit_trim_sec"] == 1.0


def test_config_clamps_exit_trim():
    def inner(_tmp):
        assert pc.get_session_exit_trim_sec() == 10
        assert pc.save_config(session_exit_trim_sec=10)["session_exit_trim_sec"] == 10
        assert pc.save_config(session_exit_trim_sec=0)["session_exit_trim_sec"] == 0
        assert pc.save_config(session_exit_trim_sec=99)["session_exit_trim_sec"] == 30
        assert pc.save_config(session_exit_trim_sec=-4)["session_exit_trim_sec"] == 0
        assert pc.save_config(session_exit_trim_sec="nope")["session_exit_trim_sec"] == 10
    _with_tmp_config(inner)


def run_all() -> None:
    test_exit_trim_drops_quit_hitches()
    test_exit_trim_off_keeps_quit_hitches()
    test_short_session_keeps_min_samples()
    test_config_clamps_exit_trim()
    print("test_game_performance: ok")


if __name__ == "__main__":
    run_all()
