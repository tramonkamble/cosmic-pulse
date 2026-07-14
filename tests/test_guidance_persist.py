# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Guidance persistence and issue view tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pulse_config
from issue_aggregate import build_issue_views


def test_config_cache_avoids_repeat_reads(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".pulse_config.json"
    cfg_path.write_text(
        json.dumps({"retention_days": 7, "suppressed_insights": [], "resolved_insights": []})
    )
    monkeypatch.setattr(pulse_config, "CONFIG_PATH", cfg_path)
    pulse_config.invalidate_config_cache()

    reads = 0
    original_read_text = Path.read_text

    def counting_read(self, *args, **kwargs):
        nonlocal reads
        if self == cfg_path:
            reads += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read)
    pulse_config.load_config()
    pulse_config.load_config()
    pulse_config.get_insight_pref_sets()
    assert reads == 1


def test_by_game_skips_idle_titles_without_issues():
    history = [
        {
            "insight_id": "cpu-governor-powersave",
            "level": "warn",
            "title": "CPU power-save",
            "text": "test",
            "games_seen": {"949230": time.time()},
            "last_seen": time.time(),
            "condition_live": True,
        }
    ]
    active = [history[0]]
    empty_prefs = (set(), set())
    with mock.patch("issue_aggregate.get_insight_pref_sets", return_value=empty_prefs):
        views = build_issue_views(
            active,
            history,
            ["730"],
            {"730": {"name": "CS2", "short": "CS2", "running": True}},
        )
        assert "730" in views["by_game"]
        assert "949230" in views["by_game"]
        assert views["by_game"]["949230"]["issue_count"] >= 1

        resolved_prefs = ({"cpu-governor-powersave"}, set())
        with mock.patch("issue_aggregate.get_insight_pref_sets", return_value=resolved_prefs):
            views_cleared = build_issue_views([], history, [], None)
        assert "949230" not in views_cleared["by_game"]


def test_running_flag_uses_normalized_ids():
    empty_prefs = (set(), set())
    with mock.patch("issue_aggregate.get_insight_pref_sets", return_value=empty_prefs):
        views = build_issue_views(
            [],
            [],
            ["949230"],
            {"949230": {"name": "Cities II", "short": "Cities", "running": True}},
        )
        assert views["by_game"]["949230"]["running"] is True


if __name__ == "__main__":
    test_by_game_skips_idle_titles_without_issues()
    test_running_flag_uses_normalized_ids()
    print("all ok (config cache test needs pytest)")
