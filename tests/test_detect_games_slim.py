# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Unit tests for slim Steam process snapshot filters."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games import (
    _cmd_has_appid_hint,
    _extract_appids_from_cmd,
    _is_overlay_proc,
    _worth_enriching,
    invalidate_detect_games_cache,
)


def test_cmd_has_appid_hint_gates_regex():
    assert _cmd_has_appid_hint("reaper SteamLaunch AppId=730 --")
    assert _cmd_has_appid_hint("/steamapps/compatdata/949230/pfx")
    assert _cmd_has_appid_hint("gameoverlayui -gameid 570 -pid 1234")
    assert not _cmd_has_appid_hint("/usr/lib/systemd/systemd --user")
    assert not _cmd_has_appid_hint("")


def test_extract_appids_from_cmd():
    active: set[str] = set()
    assert _extract_appids_from_cmd("AppId=730 -- something", active)
    assert "730" in active
    active.clear()
    assert _extract_appids_from_cmd("Z:\\steamapps\\compatdata\\949230\\pfx", active)
    assert "949230" in active
    active.clear()
    assert not _extract_appids_from_cmd("firefox --no-remote", active)
    assert not active


def test_worth_enriching_keeps_games_drops_helpers():
    assert _worth_enriching("Cities2.exe", "C:\\foo\\Cities2.exe")
    assert _worth_enriching(
        "factorio",
        "/home/u/.steam/steam/steamapps/common/Factorio/bin/x64/factorio",
    )
    assert _worth_enriching(
        "MyGame",
        "/home/u/.local/share/Steam/steamapps/common/Game/MyGame",
    )
    # Launch helpers — AppID discovery only, not metered
    assert not _worth_enriching("reaper", "reaper SteamLaunch AppId=730 --")
    assert not _worth_enriching("steamwebhelper", "/path/steamwebhelper --type=renderer")
    assert not _worth_enriching("systemd", "/lib/systemd/systemd --user")
    assert not _worth_enriching("kworker/0:0", "")
    assert not _worth_enriching("gameoverlayui", "gameoverlayui -gameid 730 -pid 1")


def test_is_overlay_proc():
    assert _is_overlay_proc("gameoverlayui")
    assert _is_overlay_proc("gameoverlayui.x86_64")
    assert not _is_overlay_proc("cs2.exe")


def test_invalidate_clears_empty_snapshot_cache():
    # Smoke: should not raise
    invalidate_detect_games_cache()
