# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Steam content_log health parsing — regression tests."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games import (
    _candidate_appids_for_proc,
    _prune_stale_cache,
    _SHADER_SIZE_CACHE,
    _SHADER_SIZE_TTL,
    _STEAM_HEALTH_CACHE,
    _STEAM_HEALTH_TTL,
    _tail_lines,
    clear_steam_health_caches,
    content_log_health,
    parse_content_log,
    steam_install_health,
    steam_update_needs_attention,
)


def test_cross_game_suspended_not_flagged():
    lines = [
        "[2026-07-06 22:22:12] AppID 453090 state changed : Fully Installed,App Running,",
        "[2026-07-06 22:22:12] AppID 730 scheduler finished : staying in schedule (result Suspended, state 0xe) ",
    ]
    corrupt, suspended = content_log_health("730", lines)
    assert not corrupt
    assert not suspended


def test_same_game_suspended_while_running():
    lines = [
        "[2026-07-02 15:51:13] AppID 730 state changed : Fully Installed,Update Queued,App Running,",
        "[2026-07-02 15:55:01] AppID 730 scheduler finished : staying in schedule (result Suspended, state 0xe) ",
    ]
    _, suspended = content_log_health("730", lines)
    assert suspended


def test_corrupt_cleared_after_finished_update():
    lines = [
        "[2026-07-02 15:51:16] AppID 730 state changed : Fully Installed,Update Queued,Files Corrupt,App Running,",
        "[2026-07-02 15:56:40] AppID 730 finished update, 6 mounted depots (BuildID 24014109) : 731 (...),",
        "[2026-07-02 15:56:42] AppID 730 scheduler finished : removed from schedule (result No Error, state 0xc) ",
    ]
    corrupt, _ = content_log_health("730", lines)
    assert not corrupt


def test_corrupt_active_without_clear():
    lines = [
        "[2026-07-02 15:51:16] AppID 730 state changed : Fully Installed,Update Queued,Files Corrupt,App Running,",
    ]
    corrupt, _ = content_log_health("730", lines)
    assert corrupt


def test_stale_manifest_after_success_not_pending():
    lines = [
        "[2026-07-06 22:04:35] AppID 252490 finished update, 2 mounted depots (BuildID 24069519) : ...",
        "[2026-07-06 22:04:38] AppID 252490 state changed : Fully Installed,",
    ]
    parsed = parse_content_log("252490", lines)
    assert parsed["manifest_pending_stale"]
    health = {
        "pending_download_bytes": 121_391_200,
        "pending_stage_bytes": 0,
        "manifest_pending_stale": True,
        "update_active": False,
        "update_delayed": False,
        "effective_pending_download_bytes": 0,
        "effective_pending_stage_bytes": 0,
    }
    assert not steam_update_needs_attention(health)


def test_update_delayed_not_urgent():
    lines = [
        "[2026-07-07 10:26:21] AppID 252490 state changed : Update Required,Fully Installed, (Update delayed for 70008 secs)",
    ]
    parsed = parse_content_log("252490", lines)
    assert parsed["update_delayed"]
    assert not parsed["update_active"]
    health = {
        "pending_download_bytes": 121_391_200,
        "pending_stage_bytes": 0,
        "update_delayed": True,
        "update_active": False,
        "manifest_pending_stale": False,
        "effective_pending_download_bytes": 121_391_200,
        "effective_pending_stage_bytes": 0,
    }
    assert not steam_update_needs_attention(health)


def test_missing_game_files_needs_attention():
    lines = [
        "[2026-07-05 20:38:54] AppID 2623190 state changed : Fully Installed,",
        "[2026-07-05 20:38:54] AppID 2623190 scheduler finished : removed from schedule (result Missing game files, state 0xc) ",
    ]
    parsed = parse_content_log("2623190", lines)
    assert parsed["missing_game_files"]
    health = {
        "missing_game_files": True,
        "update_delayed": False,
        "update_active": False,
        "effective_pending_download_bytes": 0,
        "effective_pending_stage_bytes": 0,
    }
    assert steam_update_needs_attention(health)


def test_tail_lines_reads_end_only():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "content_log.txt"
        log.write_text("old\n" * 5000 + "recent line\n")
        lines = _tail_lines(log, max_lines=5, tail_bytes=64)
        assert lines[-1] == "recent line"
        assert len(lines) <= 5


def test_candidate_appids_merges_cwd_when_cmd_matches_other():
    metas = {
        "730": {"installdir": "Counter-Strike Global Offensive"},
        "949230": {"installdir": "Cities Skylines II"},
    }
    env_cache: dict[int, str | None] = {}
    cwd_cache: dict[int, str | None] = {42: "/home/u/.steam/steamapps/common/Cities Skylines II"}
    cands = _candidate_appids_for_proc(
        "compatdata/730",
        42,
        "cities2.exe",
        {"730", "949230"},
        {},
        metas,
        env_cache,
        cwd_cache,
    )
    assert cands == {"730", "949230"}


def test_steam_health_cache_reuses_result():
    clear_steam_health_caches()
    first = steam_install_health("730", cache=True)
    second = steam_install_health("730", cache=True)
    assert first is second


def _health_blob(**overrides) -> dict:
    base = {
        "missing_game_files": False,
        "update_suspended_while_running": False,
        "update_delayed": False,
        "update_active": False,
        "manifest_pending_stale": False,
        "pending_download_bytes": 0,
        "pending_stage_bytes": 0,
    }
    base.update(overrides)
    return base


_MB = 1024**2


def test_steam_update_needs_attention_thresholds():
    cases = [
        ("idle small pending", _health_blob(pending_download_bytes=10 * _MB), False, False),
        ("idle large pending inactive", _health_blob(pending_download_bytes=25 * _MB), False, True),
        ("running small pending", _health_blob(pending_download_bytes=4 * _MB), True, False),
        ("running large pending", _health_blob(pending_download_bytes=6 * _MB), True, True),
        ("running large stage", _health_blob(pending_stage_bytes=8 * _MB), True, True),
        ("running active below threshold", _health_blob(pending_download_bytes=1 * _MB, update_active=True), True, False),
        ("stale manifest ignores counters", _health_blob(pending_download_bytes=200 * _MB, manifest_pending_stale=True), False, False),
        ("suspended while running", _health_blob(update_suspended_while_running=True), True, True),
    ]
    for label, health, running, expected in cases:
        got = steam_update_needs_attention(health, running=running)
        assert got is expected, label


def test_steam_caches_prune_stale_appids():
    clear_steam_health_caches()
    now = time.monotonic()
    _STEAM_HEALTH_CACHE["stale"] = (now - _STEAM_HEALTH_TTL - 1, {"appid": "stale"})
    _STEAM_HEALTH_CACHE["fresh"] = (now, {"appid": "fresh"})
    _SHADER_SIZE_CACHE["stale"] = (now - _SHADER_SIZE_TTL - 1, 99)
    _SHADER_SIZE_CACHE["fresh"] = (now, 42)
    _prune_stale_cache(_STEAM_HEALTH_CACHE, _STEAM_HEALTH_TTL, now=now)
    _prune_stale_cache(_SHADER_SIZE_CACHE, _SHADER_SIZE_TTL, now=now)
    assert "stale" not in _STEAM_HEALTH_CACHE
    assert "fresh" in _STEAM_HEALTH_CACHE
    assert "stale" not in _SHADER_SIZE_CACHE
    assert _SHADER_SIZE_CACHE["fresh"][1] == 42


def test_live_installed_games_not_false_positive():
    clear_steam_health_caches()
    for appid in ("730", "949230", "453090", "252490", "4704690"):
        health = steam_install_health(appid, cache=False)
        assert not health["files_corrupt"], appid
        assert not health["update_suspended_while_running"], appid
        assert not steam_update_needs_attention(health), appid


if __name__ == "__main__":
    test_cross_game_suspended_not_flagged()
    test_same_game_suspended_while_running()
    test_corrupt_cleared_after_finished_update()
    test_corrupt_active_without_clear()
    test_stale_manifest_after_success_not_pending()
    test_update_delayed_not_urgent()
    test_missing_game_files_needs_attention()
    test_tail_lines_reads_end_only()
    test_candidate_appids_merges_cwd_when_cmd_matches_other()
    test_steam_health_cache_reuses_result()
    test_live_installed_games_not_false_positive()
    print("all ok")
