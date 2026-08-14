# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""MangoHud CSV discovery and summary tests."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mangohud_logs import (
    find_session_log,
    parse_mangohud_csv,
    summarize_for_session,
)


def _write_csv(path: Path, n: int = 60, fps_base: float = 100.0) -> None:
    lines = ["fps,frametime,cpu_load,gpu_load"]
    for i in range(n):
        fps = fps_base if i % 40 else fps_base * 0.4
        ft = 1000.0 / fps
        lines.append(f"{fps:.2f},{ft:.3f},20,55")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_mangohud_csv_basic():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "game_log.csv"
        _write_csv(p, n=80, fps_base=120.0)
        summary = parse_mangohud_csv(p)
        assert summary is not None
        assert summary["sample_count"] == 80
        assert 100 < summary["fps_avg"] < 125
        assert summary["fps_1pct"] < summary["fps_avg"]
        assert summary["frametime_1pct"] > summary["frametime_avg"]
        assert summary["source"] == "mangohud"
        assert summary["path"] == str(p)


def test_parse_too_few_samples():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tiny.csv"
        _write_csv(p, n=10)
        assert parse_mangohud_csv(p) is None


def test_parse_frametime_only():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ft_only.csv"
        lines = ["frametime"]
        for _ in range(50):
            lines.append("10.0")  # 100 FPS
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = parse_mangohud_csv(p)
        assert summary is not None
        assert 95 < summary["fps_avg"] < 105


def test_find_session_log_prefers_mtime():
    with tempfile.TemporaryDirectory() as td:
        log_dir = Path(td) / "mangohud-logs"
        log_dir.mkdir()
        now = time.time()
        old = log_dir / "old.csv"
        new = log_dir / "cs2_log.csv"
        _write_csv(old, n=50)
        _write_csv(new, n=50)
        os.utime(old, (now - 600, now - 600))
        os.utime(new, (now - 5, now - 5))

        with mock.patch("mangohud_logs.mangohud_log_dirs", return_value=[log_dir]):
            found = find_session_log(
                started_ts=now - 120,
                ended_ts=now,
                game_name="Counter-Strike 2",
            )
        assert found is not None
        assert found.name == "cs2_log.csv"


def test_summarize_for_session():
    with tempfile.TemporaryDirectory() as td:
        log_dir = Path(td) / "logs"
        log_dir.mkdir()
        now = time.time()
        p = log_dir / "elden_ring.csv"
        _write_csv(p, n=100, fps_base=60.0)
        os.utime(p, (now - 2, now - 2))
        with mock.patch("mangohud_logs.mangohud_log_dirs", return_value=[log_dir]):
            summary = summarize_for_session(
                started_ts=now - 300,
                ended_ts=now,
                game_name="Elden Ring",
            )
        assert summary is not None
        assert summary["fps_avg"] is not None
        assert "matched_ts" in summary


def test_incremental_byte_offset_reads():
    """Subsequent parses only ingest appended rows (offset tracking)."""
    import mangohud_logs as mh

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "live.csv"
        _write_csv(p, n=40, fps_base=100.0)
        mh._stream_state.clear()
        s1 = parse_mangohud_csv(p)
        assert s1 is not None
        assert s1["sample_count"] == 40
        key = str(p)
        assert key in mh._stream_state
        off1 = mh._stream_state[key]["last_byte_offset"]
        assert off1 > 0

        # Unchanged file → same summary, offset stable
        s1b = parse_mangohud_csv(p)
        assert s1b is not None
        assert s1b["sample_count"] == 40
        assert mh._stream_state[key]["last_byte_offset"] == off1

        # Append more frames
        with p.open("a", encoding="utf-8") as fh:
            for _ in range(20):
                fh.write("90.00,11.111,20,55\n")
        s2 = parse_mangohud_csv(p)
        assert s2 is not None
        assert s2["sample_count"] == 60
        assert mh._stream_state[key]["last_byte_offset"] > off1

        # Truncation resets stream
        _write_csv(p, n=50, fps_base=80.0)
        s3 = parse_mangohud_csv(p)
        assert s3 is not None
        assert s3["sample_count"] == 50


def test_attach_mangohud_on_finalize():
    """Session finalize prefers MangoHud frametime for hitch display."""
    from game_performance import GameSessionTracker

    with tempfile.TemporaryDirectory() as td:
        log_dir = Path(td) / "mh"
        log_dir.mkdir()
        now = time.time()
        p = log_dir / "game.csv"
        _write_csv(p, n=80, fps_base=90.0)
        os.utime(p, (now - 1, now - 1))

        tracker = GameSessionTracker()
        row = {
            "game_id": "1245620",
            "game_name": "Elden Ring",
            "started_ts": now - 120,
            "ended_ts": now,
            "duration_sec": 120,
            "rating": 75,
            "rating_tier": "good",
            "smoothness_avg": 80,
            "stutter_score_avg": 10,
            "hitch_ms_1pct": 40.0,  # proxy
            "hitch_events": 2,
            "game_cpu_avg": 40,
            "gpu_busy_avg": 70,
            "ram_pct_avg": 50,
            "sample_count": 40,
            "trend": [],
        }
        with mock.patch("mangohud_logs.mangohud_log_dirs", return_value=[log_dir]):
            out = tracker._attach_mangohud(row)
        assert out["mangohud"] is True
        assert out["fps_avg"] is not None
        assert out["hitch_source"] == "mangohud"
        assert out["hitch_ms_1pct"] == out["frametime_1pct"]
        assert out.get("hitch_ms_1pct_proxy") == 40.0


if __name__ == "__main__":
    test_parse_mangohud_csv_basic()
    test_parse_too_few_samples()
    test_parse_frametime_only()
    test_find_session_log_prefers_mtime()
    test_summarize_for_session()
    test_attach_mangohud_on_finalize()
    print("all ok")
