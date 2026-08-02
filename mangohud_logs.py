# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""MangoHud CSV log discovery and summary stats for game sessions."""

from __future__ import annotations

import csv
import os
import re
import time
from pathlib import Path
from typing import Any

from paths import data_dir

# How far after session end we still accept a log mtime (write flush).
_LOG_SLACK_SEC = 120.0
# Ignore logs older than this relative to session start.
_LOG_MAX_AGE_BEFORE_START = 30.0

_CONF_OUTPUT_RE = re.compile(
    r"^\s*output_folder\s*=\s*(.+?)\s*$",
    re.I | re.M,
)


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(path.strip().strip("\"'"))))


def _read_output_folders_from_conf(conf: Path) -> list[Path]:
    try:
        text = conf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[Path] = []
    for m in _CONF_OUTPUT_RE.finditer(text):
        raw = m.group(1).split("#", 1)[0].strip()
        if raw:
            out.append(_expand(raw))
    return out


def mangohud_log_dirs() -> list[Path]:
    """Candidate directories for MangoHud CSV logs (existing dirs only)."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            key = str(p.expanduser().resolve())
        except OSError:
            key = str(p.expanduser())
        if key in seen:
            return
        seen.add(key)
        path = Path(key)
        if path.is_dir():
            candidates.append(path)

    # Pulse-owned default (also written by fix script sample conf)
    add(Path.home() / "mangohud-logs")
    add(Path.home() / "mangologs")
    add(data_dir() / "mangohud-logs")

    conf_paths = [
        Path.home() / ".config" / "MangoHud" / "MangoHud.conf",
        Path.home()
        / ".var"
        / "app"
        / "com.valvesoftware.Steam"
        / ".config"
        / "MangoHud"
        / "MangoHud.conf",
    ]
    for conf in conf_paths:
        if conf.is_file():
            for folder in _read_output_folders_from_conf(conf):
                add(folder)

    # Common default: CSVs dropped in home when output_folder unset historically
    add(Path.home())
    return candidates


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[idx]


def parse_mangohud_csv(path: Path) -> dict[str, Any] | None:
    """Parse a MangoHud log CSV into fps/frametime summary stats."""
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            # Skip BOM
            sample = fh.read(4096)
            fh.seek(0)
            if not sample.strip():
                return None
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            if not reader.fieldnames:
                return None
            # Normalize headers
            field_map = {h.strip().lower(): h for h in reader.fieldnames if h}
            fps_key = None
            ft_key = None
            for cand in ("fps", "framerate", "frame_rate"):
                if cand in field_map:
                    fps_key = field_map[cand]
                    break
            for cand in ("frametime", "frame_time", "frametimes", "ms"):
                if cand in field_map:
                    ft_key = field_map[cand]
                    break
            if not fps_key and not ft_key:
                return None

            fps_vals: list[float] = []
            ft_vals: list[float] = []
            for row in reader:
                if fps_key:
                    try:
                        v = float(row.get(fps_key) or "")
                        if 0 < v < 10000:
                            fps_vals.append(v)
                    except (TypeError, ValueError):
                        pass
                if ft_key:
                    try:
                        v = float(row.get(ft_key) or "")
                        if 0 < v < 10000:
                            ft_vals.append(v)
                    except (TypeError, ValueError):
                        pass
    except OSError:
        return None

    if len(fps_vals) < 30 and len(ft_vals) < 30:
        return None

    # Derive missing series
    if not fps_vals and ft_vals:
        fps_vals = [1000.0 / ft for ft in ft_vals if ft > 0]
    if not ft_vals and fps_vals:
        ft_vals = [1000.0 / f for f in fps_vals if f > 0]

    if len(fps_vals) < 30:
        return None

    # 1% / 0.1% lows = low percentiles of FPS (worst frames)
    fps_1pct = _percentile(fps_vals, 0.01)
    fps_0_1pct = _percentile(fps_vals, 0.001)
    fps_avg = sum(fps_vals) / len(fps_vals)
    ft_avg = sum(ft_vals) / len(ft_vals) if ft_vals else (1000.0 / fps_avg if fps_avg else 0)
    # 1% high frametime ≈ worst 1% of frames
    ft_1pct = _percentile(ft_vals, 0.99) if ft_vals else (1000.0 / fps_1pct if fps_1pct else 0)

    return {
        "fps_avg": round(fps_avg, 1),
        "fps_1pct": round(fps_1pct, 1),
        "fps_0_1pct": round(fps_0_1pct, 1),
        "frametime_avg": round(ft_avg, 2),
        "frametime_1pct": round(ft_1pct, 2),
        "sample_count": len(fps_vals),
        "path": str(path),
        "source": "mangohud",
    }


def _score_log(
    path: Path,
    *,
    started_ts: float,
    ended_ts: float,
    game_name: str | None,
) -> float | None:
    try:
        st = path.stat()
    except OSError:
        return None
    mtime = st.st_mtime
    # Prefer logs finished near session end
    if mtime < started_ts - _LOG_MAX_AGE_BEFORE_START:
        return None
    if mtime > ended_ts + _LOG_SLACK_SEC:
        return None
    # Size filter — tiny files are incomplete
    if st.st_size < 500:
        return None
    score = 0.0
    # Closer mtime to session end is better
    score += max(0.0, 100.0 - abs(mtime - ended_ts))
    # Prefer larger logs (more samples)
    score += min(50.0, st.st_size / 50_000.0)
    name = path.name.lower()
    if game_name:
        token = re.sub(r"[^a-z0-9]+", "", game_name.lower())[:12]
        if token and token in re.sub(r"[^a-z0-9]+", "", name):
            score += 40.0
    if name.endswith(".csv"):
        score += 5.0
    return score


def find_session_log(
    *,
    started_ts: float,
    ended_ts: float | None = None,
    game_name: str | None = None,
) -> Path | None:
    """Best MangoHud CSV for a session time window."""
    end = ended_ts if ended_ts is not None else time.time()
    best: Path | None = None
    best_score = -1.0
    for folder in mangohud_log_dirs():
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".csv", ".log", ""):
                # Allow extensionless rare cases; prefer .csv
                if path.suffix:
                    continue
            # Skip obvious non-logs in $HOME
            if folder == Path.home() and path.suffix.lower() != ".csv":
                continue
            if "mangohud" not in path.name.lower() and path.suffix.lower() != ".csv":
                if folder == Path.home():
                    continue
            sc = _score_log(path, started_ts=started_ts, ended_ts=end, game_name=game_name)
            if sc is not None and sc > best_score:
                best_score = sc
                best = path
    return best


def summarize_for_session(
    *,
    started_ts: float,
    ended_ts: float | None = None,
    game_name: str | None = None,
) -> dict[str, Any] | None:
    """Locate + parse the best MangoHud log for a game session."""
    path = find_session_log(
        started_ts=started_ts,
        ended_ts=ended_ts,
        game_name=game_name,
    )
    if not path:
        return None
    summary = parse_mangohud_csv(path)
    if not summary:
        return None
    summary["matched_ts"] = path.stat().st_mtime
    return summary
