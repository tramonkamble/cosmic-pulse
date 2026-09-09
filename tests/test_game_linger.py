# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Game detection linger — hold card through brief PID gaps."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games import (
    GAME_LINGER_SEC,
    primary_active_game_with_linger,
    reset_game_linger,
)


def _game(appid: str = "570", *, cpu: float = 40.0) -> dict:
    return {
        "id": appid,
        "name": "Example",
        "running": True,
        "primary_name": "game.exe",
        "primary_pid": 12345,
        "cpu_pct": cpu,
        "rss_mb": 900.0,
        "tree_rss_mb": 1200.0,
        "proc_count": 3,
        "procs": [],
    }


def test_linger_holds_after_pid_gone():
    reset_game_linger()
    live_state = {"570": _game()}
    assert primary_active_game_with_linger(live_state, now=100.0)["primary_pid"] == 12345

    empty_state: dict = {}
    held = primary_active_game_with_linger(empty_state, now=105.0)
    assert held is not None
    assert held["running"] is True
    assert held["lingering"] is True
    assert held["id"] == "570"
    assert held["primary_pid"] is None
    assert held["linger_remaining_sec"] == 5.0


def test_linger_expires_after_timeout():
    reset_game_linger()
    primary_active_game_with_linger({"570": _game()}, now=0.0)
    assert primary_active_game_with_linger({}, now=GAME_LINGER_SEC - 0.1) is not None
    assert primary_active_game_with_linger({}, now=GAME_LINGER_SEC + 0.1) is None


def test_linger_clears_when_new_live_game():
    reset_game_linger()
    primary_active_game_with_linger({"570": _game()}, now=0.0)
    other = primary_active_game_with_linger({"440": _game("440", cpu=80)}, now=2.0)
    assert other is not None
    assert other["id"] == "440"
    assert other.get("lingering") is None


if __name__ == "__main__":
    test_linger_holds_after_pid_gone()
    test_linger_expires_after_timeout()
    test_linger_clears_when_new_live_game()
    print("all ok")
