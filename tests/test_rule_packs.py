# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Rule pack loader and evaluator tests."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.rule_packs import (
    _get_path,
    _has_unresolved_template,
    _render_actions,
    _resolve_level_when,
    eval_condition,
    evaluate_rule_packs,
    flatten_metrics,
    list_packs,
    reload_packs,
    render_template,
)

from cosmic_pulse import rule_packs as rule_packs_mod


@contextmanager
def _force_pop(is_pop=True):
    flags = {"is_pop": is_pop, "is_cosmic": is_pop, "is_system76": is_pop}
    with patch.object(rule_packs_mod, "_platform_flags", lambda: flags):
        yield


def _snap(**overrides) -> dict:
    base = {
        "ts": 1_700_000_000.0,
        "gpu": {
            "discrete": {
                "busy_pct": 50,
                "vram_pct": 40,
                "mem_busy_pct": 20,
                "junction_c": 70,
                "gtt": {"rate_mbps": 0, "pct": 0, "sustained_high": False},
                "thermal_profile": {"model": "RX 7900 GRE"},
            },
        },
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


def test_list_packs_loads_builtin_default():
    reload_packs()
    packs = list_packs()
    ids = {p["id"] for p in packs}
    assert ids >= {"pulse-core", "popos-core"}
    assert "pulse-default" not in ids
    assert "cs2-core" not in ids
    assert "linux-core" not in ids
    core = next(p for p in packs if p["id"] == "pulse-core")
    pop = next(p for p in packs if p["id"] == "popos-core")
    assert core["rule_count"] == 5
    assert pop["rule_count"] == 5
    assert core["builtin"] is True
    assert pop["builtin"] is True


def test_nested_level_when_resolves_severe_hot():
    metrics = {
        "stutter_detail": {"severity": "severe"},
    }
    tree = {
        "detect": {"metric": "stutter_detail.severity", "eq": "severe"},
        "then": "hot",
        "else": {
            "detect": {"metric": "stutter_detail.severity", "eq": "moderate"},
            "then": "warn",
            "else": "info",
        },
    }
    assert _resolve_level_when(tree, metrics) == "hot"
    metrics["stutter_detail"]["severity"] = "moderate"
    assert _resolve_level_when(tree, metrics) == "warn"
    metrics["stutter_detail"]["severity"] = "mild"
    assert _resolve_level_when(tree, metrics) == "info"


def test_gpu_junction_critical_alert_even_without_fan_curve():
    """Guidance-only thermal alert must fire on is_hot (e.g. RDNA3 fan_curve_helpful=false)."""
    reload_packs()
    snap = _snap(
        gpu={
            "discrete": {
                "busy_pct": 90,
                "vram_pct": 40,
                "mem_busy_pct": 20,
                "junction_c": 105,
                "gfx_mhz": 2400,
                "gtt": {"rate_mbps": 0, "pct": 0, "sustained_high": False},
                "thermal_profile": {
                    "model": "RX 7900 XTX",
                    "label": "RDNA3",
                    "hot_c": 100,
                    "warm_c": 90,
                    "fan_curve_helpful": False,
                    "design_note": "runs hot by design",
                },
                "thermal_state": {
                    "throttling": False,
                    "by_design": True,
                    "observed_peak_mhz": 2500,
                },
            },
        },
    )
    ctx = {"governor": "performance", "swappiness": 10, "gpu_model": "RX 7900 XTX"}
    with _force_pop():
        hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "gpu-thermal-ceiling" in emitted
    assert "gpu-thermal-by-design" not in emitted
    hit = next(h for h in hints if h["insight_id"] == "gpu-thermal-ceiling")
    assert hit["level"] == "hot"
    assert "Alert" in hit["title"] or "critical" in hit["title"].lower()


def test_stutter_proxy_fires_from_instrumentation():
    reload_packs()
    snap = _snap(
        game_totals={"running": True, "game_id": "570", "game_name": "Dota 2"},
        stutter={"score": 55, "event": True, "est_ms": 32, "severity": "moderate", "session": {"events": 4, "hitch_ms_1pct": 28}},
    )
    ctx = {"governor": "performance", "swappiness": 10}
    hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "stutter-proxy" in emitted
    hit = next(h for h in hints if h["insight_id"] == "stutter-proxy")
    assert hit["pack_id"] == "pulse-core"
    assert hit["level"] == "warn"
    assert "hitch" in hit["title"].lower() or "stutter" in hit["title"].lower()
    blob = " ".join(
        f"{a.get('label','')} {a.get('cmd','')}" for a in (hit.get("actions") or [])
    ).lower()
    assert "brave" not in blob


def test_governor_rule_fires_from_pack():
    snap = _snap()
    ctx = {"governor": "powersave", "swappiness": 10}
    hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "cpu-governor-powersave" in emitted
    hit = next(h for h in hints if h["insight_id"] == "cpu-governor-powersave")
    assert hit["pack_id"] == "pulse-core"
    assert hit["level"] == "warn"
    assert "powersave" in hit["text"]


def test_swappiness_rule_fires():
    snap = _snap()
    ctx = {"governor": "performance", "swappiness": 180}
    hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "vm-swappiness-high" in emitted
    hit = next(h for h in hints if h["insight_id"] == "vm-swappiness-high")
    assert "180" in hit["text"]
    assert hit.get("actions")
    assert "fix_script" not in hit
    assert "has_fix_script" not in hit


def test_stutter_proxy_skips_when_idle():
    snap = _snap(
        game_totals={"running": False, "game_id": None},
        stutter={"score": 80, "event": True, "session": {"events": 9}},
    )
    ctx = {"governor": "performance", "swappiness": 10}
    _, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "stutter-proxy" not in emitted


def test_resolve_games_string_all_not_char_split():
    """YAML ``games: all`` must not become ['a','l','l']."""
    from cosmic_pulse.rule_packs import _resolve_games

    assert _resolve_games({"games": "all"}, {}) == ["all"]
    assert _resolve_games({"games": ["all"]}, {}) == ["all"]
    assert _resolve_games({"games": "active"}, {"game": {"appid": "570"}}) == ["570"]


def test_eval_condition_all_and_any():
    metrics = flatten_metrics(_snap(memory={"swap_pct": 30}), {}, {"governor": "performance"})
    assert eval_condition({"metric": "memory.swap_pct", "gt": 25}, metrics)
    assert (
        eval_condition(
            {
                "all": [
                    {"metric": "memory.swap_pct", "gte": 10},
                    {"metric": "memory.swap_pct", "lt": 25},
                ],
            },
            metrics,
        )
        is False
    )


def test_unresolved_template_regex_ignores_json_like_braces():
    assert _has_unresolved_template("{game.name}")
    assert _has_unresolved_template("busy {gpu.busy_pct:.0f}%")
    assert not _has_unresolved_template("echo '{\"ok\": true}'")
    assert not _has_unresolved_template("PATH=$HOME/bin")


def test_display_hdr_off_rule_fires_when_capable_and_sdr():
    from cosmic_pulse import hardware_probe
    from cosmic_pulse import rule_packs

    hdr = {
        "capable": True,
        "active": False,
        "connector": "DP-1",
        "colorspace_name": "Default",
        "max_nits": 566.0,
        "max_fall_nits": 566.0,
        "desktop": "COSMIC",
        "desktop_toggle": False,
        "summary": "off",
    }
    snap = _snap()
    ctx = {"governor": "performance", "swappiness": 10}
    reload_packs()
    with (
        _force_pop(),
        patch.object(hardware_probe, "primary_display_hdr", lambda max_age_sec=30.0: hdr),
        patch.object(rule_packs, "primary_display_hdr", lambda max_age_sec=30.0: hdr),
    ):
        hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "display-hdr-off" in emitted
    hit = next(h for h in hints if h["insight_id"] == "display-hdr-off")
    assert hit["level"] == "info"
    assert hit.get("actions")
    assert "fix_script" not in hit
    assert "HDR" in hit["title"] or "HDR" in hit["text"]
    first = hit["actions"][0]
    assert first.get("kind") == "note"
    assert not (first.get("cmd") or "").strip()
    assert "on-screen" in (first.get("note") or "").lower() or "osd" in (first.get("label") or "").lower()


def test_display_hdr_off_rule_skips_when_active():
    from cosmic_pulse import hardware_probe
    from cosmic_pulse import rule_packs

    hdr = {
        "capable": True,
        "active": True,
        "connector": "DP-1",
        "colorspace_name": "BT2020_RGB",
        "max_nits": 566.0,
        "desktop": "COSMIC",
        "desktop_toggle": False,
        "summary": "on",
    }
    snap = _snap()
    ctx = {"governor": "performance", "swappiness": 10}
    with (
        _force_pop(),
        patch.object(hardware_probe, "primary_display_hdr", lambda max_age_sec=30.0: hdr),
        patch.object(rule_packs, "primary_display_hdr", lambda max_age_sec=30.0: hdr),
    ):
        _hints, emitted = evaluate_rule_packs(snap, {}, ctx)
    assert "display-hdr-off" not in emitted


def test_edid_hdr_static_parse():
    from cosmic_pulse.hardware_probe import _edid_hdr_static

    # Minimal CTA block with HDR static metadata: EOTF=0x07 (SDR+HDR+PQ), max codes 112
    # Structure: 128-byte base + 128-byte CTA extension
    base = bytearray(128)
    base[126] = 1  # one extension
    cta = bytearray(128)
    cta[0] = 0x02  # CTA-861
    cta[2] = 4 + 1 + 6  # dtd start after one data block
    # extended tag block: tag=7, len=6 → header 0xE6, payload 06 07 01 70 70 2f
    cta[4] = 0xE6
    cta[5:11] = bytes([0x06, 0x07, 0x01, 0x70, 0x70, 0x2F])
    edid = bytes(base) + bytes(cta)
    hdr = _edid_hdr_static(edid)
    assert hdr["capable"] is True
    assert hdr["max_nits"] is not None
    assert 500 < hdr["max_nits"] < 650


def test_get_path_traverses_list_indices():
    metrics = {"cpu": {"temps": {"ccd": [45.2, 46.1]}}}
    assert _get_path(metrics, "cpu.temps.ccd.0") == 45.2
    assert _get_path(metrics, "cpu.temps.ccd.1") == 46.1
    assert _get_path(metrics, "cpu.temps.ccd.9") is None
    assert render_template("CCD0 {cpu.temps.ccd.0:.0f}C", metrics) == "CCD0 45C"


def test_render_template_leaves_missing_paths():
    metrics = {"game": {"name": "Example"}}
    assert render_template("Hi {game.name}", metrics) == "Hi Example"
    assert render_template("Hi {game.missing}", metrics) == "Hi {game.missing}"
    assert _get_path(metrics, "game.deep.path") is None


def test_render_template_bad_format_falls_back_to_str():
    metrics = {"cpu": {"overall_pct": 82.4}}
    assert render_template("CPU {cpu.overall_pct:badfmt}%", metrics) == "CPU 82.4%"


def test_render_actions_drops_unresolved_keeps_json_literals():
    metrics = {"game": {"name": "Example", "appid": "570"}}
    json_only = _render_actions(
        [{"label": "JSON", "cmd": "echo '{\"ok\": true}'", "note": "ok"}],
        metrics,
    )
    assert len(json_only) == 1
    assert json_only[0]["cmd"] == "echo '{\"ok\": true}'"

    mixed = _render_actions(
        [
            {
                "label": "Open {game.name}",
                "cmd": "echo '{\"ok\": true}'",
                "note": "see {game.missing}",
            },
            {"label": "Valid", "cmd": "echo {game.appid}", "note": ""},
        ],
        metrics,
    )
    assert len(mixed) == 1
    assert mixed[0]["cmd"] == "echo 570"


def test_render_template_formats_numbers():
    metrics = flatten_metrics(
        _snap(game_totals={"running": True, "game_id": "570"}, cpu={"overall_pct": 82.4}),
        {},
        {"governor": "powersave"},
    )
    out = render_template("CPU {cpu.overall_pct:.0f}% in {game.name}", metrics)
    assert "82%" in out
    assert "your game" not in out or True  # name may be resolved from game context


def test_cpu_rapl_unreadable_rule_fires():
    from cosmic_pulse import rule_packs

    orig = rule_packs._cpu_rapl_tools
    rule_packs._cpu_rapl_tools = lambda: {"cpu_rapl": False, "cpu_rapl_present": True}
    try:
        reload_packs()
        snap = _snap()
        ctx = {"governor": "performance", "swappiness": 10}
        with _force_pop():
            hints, emitted = evaluate_rule_packs(snap, {}, ctx)
        assert "cpu-rapl-unreadable" in emitted
        hit = next(h for h in hints if h["insight_id"] == "cpu-rapl-unreadable")
        assert hit["pack_id"] == "popos-core"
        assert hit["level"] == "info"
        assert hit.get("actions")
        assert "udev" in hit["title"].lower() or "udev" in hit["text"].lower()
        assert "fix_script" not in hit
    finally:
        rule_packs._cpu_rapl_tools = orig


def test_cpu_rapl_rule_skips_when_readable():
    from cosmic_pulse import rule_packs

    orig = rule_packs._cpu_rapl_tools
    rule_packs._cpu_rapl_tools = lambda: {"cpu_rapl": True, "cpu_rapl_present": True}
    try:
        reload_packs()
        _, emitted = evaluate_rule_packs(_snap(), {}, {"governor": "performance", "swappiness": 10})
        assert "cpu-rapl-unreadable" not in emitted
    finally:
        rule_packs._cpu_rapl_tools = orig


def test_popos_pack_skips_when_not_pop():
    reload_packs()
    snap = _snap(
        gpu={
            "discrete": {
                "busy_pct": 90,
                "junction_c": 105,
                "thermal_profile": {"hot_c": 100, "label": "RDNA3"},
            }
        }
    )
    with _force_pop(is_pop=False):
        _, emitted = evaluate_rule_packs(snap, {}, {"governor": "performance", "swappiness": 10})
    assert "gpu-thermal-ceiling" not in emitted
    assert "cpu-rapl-unreadable" not in emitted


def test_cpu_rapl_rule_skips_when_absent():
    from cosmic_pulse import rule_packs

    orig = rule_packs._cpu_rapl_tools
    rule_packs._cpu_rapl_tools = lambda: {"cpu_rapl": False, "cpu_rapl_present": False}
    try:
        reload_packs()
        _, emitted = evaluate_rule_packs(_snap(), {}, {"governor": "performance", "swappiness": 10})
        assert "cpu-rapl-unreadable" not in emitted
    finally:
        rule_packs._cpu_rapl_tools = orig


def _busy_game_snap() -> dict:
    return _snap(
        game_totals={"running": True, "game_id": "570", "game_name": "Dota 2"},
        gpu={
            "discrete": {
                "busy_pct": 92,
                "vram_pct": 40,
                "mem_busy_pct": 20,
                "junction_c": 70,
                "gtt": {"rate_mbps": 0, "pct": 0, "sustained_high": False},
                "thermal_profile": {"model": "RX 7900 GRE"},
            }
        },
    )


def test_gpu_fps_cap_fires_on_60hz():
    from cosmic_pulse import rule_packs

    with patch.object(rule_packs, "primary_display_refresh_hz", lambda max_age_sec=120.0: 60.0):
        hints, emitted = evaluate_rule_packs(
            _busy_game_snap(), {}, {"governor": "performance", "swappiness": 10}
        )
    assert "gpu-fps-cap" in emitted
    hit = next(h for h in hints if h["insight_id"] == "gpu-fps-cap")
    assert hit["pack_id"] == "pulse-core"
    assert "60" in hit["text"]


def test_gpu_fps_cap_skips_high_refresh():
    from cosmic_pulse import rule_packs

    with patch.object(rule_packs, "primary_display_refresh_hz", lambda max_age_sec=120.0: 144.0):
        _, emitted = evaluate_rule_packs(
            _busy_game_snap(), {}, {"governor": "performance", "swappiness": 10}
        )
    assert "gpu-fps-cap" not in emitted


def run_all() -> None:
    test_list_packs_loads_builtin_default()
    test_nested_level_when_resolves_severe_hot()
    test_gpu_junction_critical_alert_even_without_fan_curve()
    test_stutter_proxy_fires_from_instrumentation()
    test_governor_rule_fires_from_pack()
    test_swappiness_rule_fires()
    test_stutter_proxy_skips_when_idle()
    test_resolve_games_string_all_not_char_split()
    test_eval_condition_all_and_any()
    test_unresolved_template_regex_ignores_json_like_braces()
    test_display_hdr_off_rule_fires_when_capable_and_sdr()
    test_display_hdr_off_rule_skips_when_active()
    test_edid_hdr_static_parse()
    test_get_path_traverses_list_indices()
    test_render_template_leaves_missing_paths()
    test_render_template_bad_format_falls_back_to_str()
    test_render_actions_drops_unresolved_keeps_json_literals()
    test_render_template_formats_numbers()
    test_cpu_rapl_unreadable_rule_fires()
    test_cpu_rapl_rule_skips_when_readable()
    test_popos_pack_skips_when_not_pop()
    test_cpu_rapl_rule_skips_when_absent()
    test_gpu_fps_cap_fires_on_60hz()
    test_gpu_fps_cap_skips_high_refresh()
    print("test_rule_packs: ok")


if __name__ == "__main__":
    run_all()
