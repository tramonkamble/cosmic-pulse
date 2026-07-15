# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Auto-resolve guidance tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guidance_auto import (
    AUTO_RESOLVE_CLEAR_SEC,
    CLEAR_SINCE_KEY,
    DIAG_BACKED_INSIGHTS,
    seed_clear_timers,
    tick_auto_resolve,
)


def test_auto_resolve_after_sustained_clear():
    resolved: list[str] = []
    history = [
        {
            "insight_id": "swap-thrash",
            "title": "Swap thrash",
            "condition_live": False,
        }
    ]
    now = 1000.0
    tick_auto_resolve(history, set(), set(), set(), now, resolved.append)
    assert CLEAR_SINCE_KEY in history[0]
    assert not resolved

    tick_auto_resolve(
        history,
        set(),
        set(),
        set(),
        now + AUTO_RESOLVE_CLEAR_SEC - 1,
        resolved.append,
    )
    assert not resolved

    tick_auto_resolve(
        history,
        set(),
        set(),
        set(),
        now + AUTO_RESOLVE_CLEAR_SEC,
        resolved.append,
    )
    assert resolved == ["swap-thrash"]
    assert CLEAR_SINCE_KEY not in history[0]


def test_seed_clear_timers_uses_last_seen():
    history = [{"insight_id": "cpu-governor-powersave", "last_seen": 100.0}]
    assert seed_clear_timers(history, set(), set(), set(), 200.0)
    assert history[0][CLEAR_SINCE_KEY] == 100.0
    resolved: list[str] = []
    tick_auto_resolve(
        history,
        set(),
        set(),
        set(),
        100.0 + AUTO_RESOLVE_CLEAR_SEC,
        resolved.append,
    )
    assert resolved == ["cpu-governor-powersave"]


def test_auto_resolve_skips_when_live_again():
    resolved: list[str] = []
    history = [
        {
            "insight_id": "gpu-thermal-warn",
            "title": "GPU hot",
            CLEAR_SINCE_KEY: 500.0,
        }
    ]
    tick_auto_resolve(
        history,
        {"gpu-thermal-warn"},
        set(),
        set(),
        500.0 + AUTO_RESOLVE_CLEAR_SEC + 10,
        resolved.append,
    )
    assert not resolved
    assert CLEAR_SINCE_KEY not in history[0]


def test_fresh_active_ids_cached_once_per_tick():
    calls = 0

    def fresh() -> set[str]:
        nonlocal calls
        calls += 1
        return {"game-libs-missing"}

    history = [
        {"insight_id": iid, CLEAR_SINCE_KEY: 0.0}
        for iid in ("game-libs-missing", "steam-disk-low", "vulkan-broken")
        if iid in DIAG_BACKED_INSIGHTS
    ]
    tick_auto_resolve(
        history,
        set(),
        set(),
        set(),
        AUTO_RESOLVE_CLEAR_SEC + 1,
        lambda _iid: None,
        fresh_active_ids=fresh,
    )
    assert calls == 1


def test_seed_clear_timers_tolerates_invalid_last_seen():
    history = [{"insight_id": "swap-thrash", "last_seen": ""}]
    now = 500.0
    assert seed_clear_timers(history, set(), set(), set(), now)
    assert history[0][CLEAR_SINCE_KEY] == now


def test_auto_resolve_tolerates_invalid_clear_since():
    resolved: list[str] = []
    history = [{"insight_id": "swap-thrash", CLEAR_SINCE_KEY: "not-a-ts"}]
    tick_auto_resolve(history, set(), set(), set(), 1000.0, resolved.append)
    assert not resolved
    assert history[0][CLEAR_SINCE_KEY] == 1000.0


def test_auto_resolve_skips_state_verified_insights():
    resolved: list[str] = []
    history = [{"insight_id": "proton-wayland-launch-fix", CLEAR_SINCE_KEY: 0.0}]
    tick_auto_resolve(
        history,
        set(),
        set(),
        set(),
        AUTO_RESOLVE_CLEAR_SEC + 5,
        resolved.append,
    )
    assert not resolved
    assert CLEAR_SINCE_KEY not in history[0]


def test_auto_resolve_skips_resolved_and_suppressed():
    resolved: list[str] = []
    history = [
        {"insight_id": "a", CLEAR_SINCE_KEY: 0.0},
        {"insight_id": "b", CLEAR_SINCE_KEY: 0.0},
    ]
    tick_auto_resolve(
        history,
        set(),
        {"a"},
        {"b"},
        AUTO_RESOLVE_CLEAR_SEC + 1,
        resolved.append,
    )
    assert not resolved


if __name__ == "__main__":
    test_auto_resolve_after_sustained_clear()
    test_seed_clear_timers_uses_last_seen()
    test_auto_resolve_skips_when_live_again()
    test_auto_resolve_skips_resolved_and_suppressed()
    print("all ok")
