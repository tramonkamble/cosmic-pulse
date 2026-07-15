# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Steam launch-option and Proton session detection tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games import launch_has_wayland_fix, proc_uses_proton, steam_launch_options
from rule_packs import eval_condition, evaluate_rule_packs


def _snap(**overrides) -> dict:
    base = {
        "ts": 1_700_000_000.0,
        "gpu": {"discrete": {"busy_pct": 50, "vram_pct": 40, "mem_busy_pct": 20}},
        "memory": {"swap_pct": 0},
        "bandwidth": {"memory": {"pgmajfault_per_s": 0, "psi_avg10": 0, "swap_out_kbps": 0}},
        "cpu": {"overall_pct": 30, "temps": {"ccd": [45, 46]}},
        "game_totals": {"running": False, "game_id": None},
        "stutter": {"score": 0, "session": {"events": 0}},
        "load_phase": {
            "phase": "idle",
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


def test_launch_has_wayland_fix_detects_override():
    assert launch_has_wayland_fix(
        "PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%"
    )
    assert launch_has_wayland_fix("SDL_VIDEODRIVER=x11 %command%")
    assert not launch_has_wayland_fix("")
    assert not launch_has_wayland_fix("%command%")


def test_steam_launch_options_reads_localconfig(monkeypatch, tmp_path):
    import games

    cfg = tmp_path / "userdata" / "12345" / "config"
    cfg.mkdir(parents=True)
    (cfg / "localconfig.vdf").write_text(
        '''
"UserLocalConfigStore"
{
    "Software"
    {
        "Valve"
        {
            "Steam"
            {
                "Apps"
                {
                    "3041230"
                    {
                        "LaunchOptions"		"PROTON_ENABLE_WAYLAND=0 %command%"
                    }
                }
            }
        }
    }
}
'''
    )
    monkeypatch.setattr(games, "steam_root", lambda: tmp_path)
    games._LOCALCONFIG_CACHE = (0.0, "")
    assert "PROTON_ENABLE_WAYLAND=0" in steam_launch_options("3041230")
    assert steam_launch_options("999999") == ""


def test_proton_wayland_rule_fires_when_gated(monkeypatch):
    import rule_packs

    monkeypatch.setattr(rule_packs, "session_is_wayland", lambda: True)
    monkeypatch.setattr(
        rule_packs,
        "game_session_launch_metrics",
        lambda appid, primary_pid=None: {
            "proton": True,
            "wayland_fix_missing": True,
            "launch_options": "",
        },
    )
    snap = _snap(
        game_totals={
            "running": True,
            "game_id": "3041230",
            "game_name": "Windrose",
            "primary_pid": 999999,
        },
    )
    hints, emitted = evaluate_rule_packs(snap, {}, {"governor": "performance"})
    assert "proton-wayland-launch-fix" in emitted
    hit = next(h for h in hints if h["insight_id"] == "proton-wayland-launch-fix")
    assert hit["level"] == "info"
    assert hit["bucket"] == "steam"
    assert "3041230" in hit["games"]


def test_proton_wayland_rule_skips_when_fix_present(monkeypatch):
    import rule_packs

    monkeypatch.setattr(rule_packs, "session_is_wayland", lambda: True)
    monkeypatch.setattr(
        rule_packs,
        "game_session_launch_metrics",
        lambda appid, primary_pid=None: {
            "proton": True,
            "wayland_fix_missing": False,
            "launch_options": "SDL_VIDEODRIVER=x11 %command%",
        },
    )
    snap = _snap(
        game_totals={
            "running": True,
            "game_id": "3041230",
            "primary_pid": 999999,
        },
    )
    _, emitted = evaluate_rule_packs(snap, {}, {"governor": "performance"})
    assert "proton-wayland-launch-fix" not in emitted


def test_proc_uses_proton_self_process():
    import os

    assert proc_uses_proton(os.getpid()) is False


def test_eval_condition_session_game_metrics():
    metrics = {
        "session": {"wayland": True},
        "game": {"running": True, "proton": True, "wayland_fix_missing": True},
    }
    assert eval_condition({"metric": "session.wayland", "eq": True}, metrics)
    assert eval_condition(
        {
            "all": [
                {"metric": "session.wayland", "eq": True},
                {"metric": "game.proton", "eq": True},
                {"metric": "game.wayland_fix_missing", "eq": True},
            ],
        },
        metrics,
    )

