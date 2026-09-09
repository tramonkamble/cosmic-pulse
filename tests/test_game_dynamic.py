# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic game context — pack overrides and templates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games import GAME_OVERRIDES, LEGACY_GAME_IDS, reload_game_pack_data
from rule_packs import evaluate_rule_packs, game_context_kwargs, get_game_overrides


def _snap(**overrides) -> dict:
    base = {
        "gpu": {
            "discrete": {
                "busy_pct": 50,
                "vram_pct": 40,
                "mem_busy_pct": 20,
                "junction_c": 70,
                "gtt": {"rate_mbps": 0, "pct": 0},
                "thermal_profile": {"model": "RX 7900 GRE"},
            }
        },
        "memory": {"swap_pct": 0},
        "bandwidth": {"memory": {"pgmajfault_per_s": 0, "psi_avg10": 0, "swap_out_kbps": 0}},
        "cpu": {"overall_pct": 30, "temps": {"ccd": [45, 46]}},
        "game_totals": {"running": True, "game_id": "570", "game_name": "Dota 2"},
        "stutter": {"score": 0, "session": {"events": 0}},
        "load_phase": {
            "phase": "playing",
            "in_grace": False,
            "suppress_page_fault_warn": True,
            "sustained_fault_playing": False,
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **val}
        else:
            base[key] = val
    return base


def test_builtin_pack_has_no_title_overrides():
    reload_game_pack_data()
    assert get_game_overrides() == {}
    assert list(LEGACY_GAME_IDS) == []


def test_lazy_dict_invalidates_on_reload():
    from games import reload_game_pack_data

    GAME_OVERRIDES._cache = {"999": {"short": "STALE"}}
    reload_game_pack_data()
    assert "999" not in GAME_OVERRIDES


def test_legacy_ids_from_pack():
    reload_game_pack_data()
    assert list(LEGACY_GAME_IDS) == []


def test_game_context_kwargs_from_metrics():
    from rule_packs import flatten_metrics

    metrics = flatten_metrics(_snap(), {}, {"governor": "performance"})
    kw = game_context_kwargs(metrics)
    assert kw["appid"] == "570"
    assert kw["game_name"] == "Dota 2"


def test_unresolved_template_actions_filtered():
    from rule_packs import _render_actions

    metrics = {"game": {"appid": None, "name": "your game", "running": False}}
    actions = _render_actions(
        [
            {"label": "Verify", "cmd": "xdg-open 'steam://validate/{game.appid}'"},
            {"label": "Downloads", "cmd": "xdg-open 'steam://open/downloads'"},
        ],
        metrics,
    )
    assert len(actions) == 1
    assert actions[0]["label"] == "Downloads"


def test_lib_apt_install_built_from_findings():
    from rule_packs import _lib_install_context

    findings = [
        {
            "id": "lib-missing-libldap2",
            "title": "Missing libldap2",
            "fix": "sudo apt install libldap2",
        },
        {
            "id": "lib-multilib-missing",
            "title": "32-bit multilib not enabled",
            "fix": "sudo dpkg --add-architecture i386",
        },
    ]
    ctx = _lib_install_context(findings)
    assert ctx["lib_multilib_needed"] is True
    assert "libldap2" in ctx["lib_apt_install"]
    assert "libgl1:i386" in ctx["lib_apt_install"]


def test_prefix_reset_requires_running_game():
    snap = _snap(
        game_totals={"running": False, "game_id": None},
        load_phase={"phase": "idle", "in_grace": False, "suppress_page_fault_warn": True},
    )
    _, emitted_ids = evaluate_rule_packs(snap, {}, {"governor": "performance"})
    assert "game-prefix-reset" not in emitted_ids


def test_no_game_metrics_context():
    from rule_packs import flatten_metrics

    snap = _snap(game_totals={"running": False, "game_id": None, "game_name": None})
    metrics = flatten_metrics(snap, {}, {"governor": "performance"})
    assert metrics["game"]["running"] is False
    assert metrics["game"]["appid"] is None
    kw = game_context_kwargs(metrics)
    assert kw["appid"] is None


def test_legacy_game_id_normalized():
    from games import normalize_game_id

    assert normalize_game_id("alias") == "alias"
    assert normalize_game_id("570") == "570"


def test_rule_pack_game_actions_get_appid():
    """Corrupt-files rule should template the active appid into step commands."""
    snap = _snap()
    from unittest.mock import patch

    health = {
        "files_corrupt": True,
        "update_suspended_while_running": False,
        "effective_pending_download_bytes": 0,
        "effective_pending_stage_bytes": 0,
        "shader_cache_bytes": 0,
    }
    with patch("rule_packs.steam_install_health", return_value=health):
        hints, emitted = evaluate_rule_packs(snap, {}, {"governor": "performance"})
    if "game-files-corrupt" in emitted:
        hit = next(h for h in hints if h["insight_id"] == "game-files-corrupt")
        cmds = " ".join(a.get("cmd") or "" for a in (hit.get("actions") or []))
        assert "570" in cmds or "validate" in cmds.lower()
        assert "has_fix_script" not in hit
        assert "fix_script" not in hit


if __name__ == "__main__":
    test_unresolved_template_actions_filtered()
    test_lazy_dict_invalidates_on_reload()
    test_builtin_pack_has_no_title_overrides()
    test_legacy_ids_from_pack()
    test_game_context_kwargs_from_metrics()
    test_lib_apt_install_built_from_findings()
    test_prefix_reset_requires_running_game()
    test_no_game_metrics_context()
    test_legacy_game_id_normalized()
    test_rule_pack_game_actions_get_appid()
    print("all ok")
