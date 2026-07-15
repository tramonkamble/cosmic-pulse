# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic game context — pack overrides and fix-script kwargs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fix_scripts import get_fix_script
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


def test_game_overrides_loaded_from_default_pack():
    reload_game_pack_data()
    overrides = get_game_overrides()
    assert "730" in overrides
    assert "cs2.exe" in overrides["730"]["main_exe"]
    assert "949230" in overrides
    assert "cities2.exe" in overrides["949230"][
        "main_exe"
    ].__str__().lower() or "Cities2.exe".lower() in {
        x.lower() for x in overrides["949230"]["main_exe"]
    }


def test_lazy_dict_invalidates_on_reload():
    from games import reload_game_pack_data

    _ = GAME_OVERRIDES.get("730")
    GAME_OVERRIDES._cache = {"999": {"short": "STALE"}}
    reload_game_pack_data()
    assert "999" not in GAME_OVERRIDES
    assert "730" in GAME_OVERRIDES


def test_legacy_ids_from_pack():
    reload_game_pack_data()
    assert LEGACY_GAME_IDS.get("cities2") == "949230"


def test_fix_script_uses_active_appid_not_cs2_default():
    script = get_fix_script("game-files-corrupt", appid="570", game_name="Dota 2")
    assert "steam://validate/570" in script
    assert "Counter-Strike" not in script
    assert "730" not in script


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


def test_update_shader_script_without_appid():
    script = get_fix_script("game-update-pending", appid=None, game_name="Test Game")
    assert "No active AppID" in script
    assert "shadercache/<AppID>" in script
    assert "rm -rf" not in script.split("No active AppID")[1][:200]


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
    script = get_fix_script("game-libs-missing", lib_findings=findings, multilib=True)
    assert "libldap2" in script
    assert "add-architecture i386" in script


def test_running_game_scoped_fix_script_skips_stale_history():
    from tuning_actions import fix_script_for_insight

    snap = _snap(game_totals={"running": True, "game_id": "3041230", "game_name": "Windrose"})
    history = [
        {
            "insight_id": "game-files-corrupt",
            "fix_script": '# CS2 stale\nsteam://validate/730\nCounter-Strike 2',
        }
    ]
    script = fix_script_for_insight(
        "game-files-corrupt",
        snap,
        {},
        history=history,
    )
    assert "steam://validate/3041230" in script
    assert "Counter-Strike" not in script
    assert "steam://validate/730" not in script


def test_idle_game_scoped_fix_script_skips_stale_history():
    from tuning_actions import fix_script_for_insight

    snap = _snap(game_totals={"running": False, "game_id": None, "game_name": None})
    history = [
        {
            "insight_id": "game-files-corrupt",
            "fix_script": '# CS2 stale\nsteam://validate/730\nCounter-Strike 2',
        }
    ]
    script = fix_script_for_insight(
        "game-files-corrupt",
        snap,
        {},
        history=history,
    )
    assert "Counter-Strike" not in script
    assert "steam://validate/730" not in script
    assert "No active AppID" in script or "your game" in script


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

    assert normalize_game_id("cities2") == "949230"
    assert normalize_game_id("949230") == "949230"


def test_resolve_swappiness_script_non_empty():
    from rule_packs import resolve_fix_script_for_insight

    snap = _snap(game_totals={"running": False, "game_id": None})
    script = resolve_fix_script_for_insight(
        "vm-swappiness-high",
        snap,
        {},
        {"governor": "powersave", "swappiness": 180},
    )
    assert "180" in script
    assert "swappiness" in script.lower()


def test_rule_pack_game_fix_script_gets_appid():
    snap = _snap()
    snap["steam"] = {"files_corrupt": True}
    # Force corrupt signal via diag flatten — use running game with steam metrics
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
        assert "steam://validate/570" in (hit.get("fix_script") or "")
        assert "730" not in (hit.get("fix_script") or "")


if __name__ == "__main__":
    test_unresolved_template_actions_filtered()
    test_update_shader_script_without_appid()
    test_lazy_dict_invalidates_on_reload()
    test_game_overrides_loaded_from_default_pack()
    test_legacy_ids_from_pack()
    test_fix_script_uses_active_appid_not_cs2_default()
    test_game_context_kwargs_from_metrics()
    test_lib_apt_install_built_from_findings()
    test_running_game_scoped_fix_script_skips_stale_history()
    test_idle_game_scoped_fix_script_skips_stale_history()
    test_prefix_reset_requires_running_game()
    test_no_game_metrics_context()
    test_legacy_game_id_normalized()
    test_resolve_swappiness_script_non_empty()
    test_rule_pack_game_fix_script_gets_appid()
    print("all ok")
