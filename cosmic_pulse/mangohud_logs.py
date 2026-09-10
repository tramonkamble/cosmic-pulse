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

from .paths import data_dir

# How far after session end we still accept a log mtime (write flush).
_LOG_SLACK_SEC = 120.0
# Ignore logs older than this relative to session start.
_LOG_MAX_AGE_BEFORE_START = 30.0
# Bound CSV parse cost so a huge log cannot stall the sampler / HTTP threads.
_MAX_CSV_BYTES = 8 * 1024 * 1024  # 8 MiB
_MAX_CSV_ROWS = 120_000
# Per-file stream state: byte offset + rolling sample buffers (O(1) per tick).
_stream_state: dict[str, dict[str, Any]] = {}

_CONF_OUTPUT_RE = re.compile(
    r"^\s*output_folder\s*=\s*(.+?)\s*$",
    re.I | re.M,
)


def _field_keys(fieldnames: list[str] | None) -> tuple[str | None, str | None, list[str]]:
    """Map header names → fps / frametime columns (same logic as before)."""
    if not fieldnames:
        return None, None, []
    names = [h for h in fieldnames if h]
    field_map = {h.strip().lower(): h for h in names}
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
    return fps_key, ft_key, names


def _append_row_values(
    row: dict[str, str],
    *,
    fps_key: str | None,
    ft_key: str | None,
    fps_vals: list[float],
    ft_vals: list[float],
) -> None:
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


def _trim_samples(fps_vals: list[float], ft_vals: list[float]) -> None:
    """Keep only the newest window so memory stays bounded on long sessions."""
    if len(fps_vals) > _MAX_CSV_ROWS:
        del fps_vals[: len(fps_vals) - _MAX_CSV_ROWS]
    if len(ft_vals) > _MAX_CSV_ROWS:
        del ft_vals[: len(ft_vals) - _MAX_CSV_ROWS]


def _build_summary(
    path: Path,
    fps_vals: list[float],
    ft_vals: list[float],
) -> dict[str, Any] | None:
    if len(fps_vals) < 30 and len(ft_vals) < 30:
        return None
    fps = list(fps_vals)
    ft = list(ft_vals)
    if not fps and ft:
        fps = [1000.0 / x for x in ft if x > 0]
    if not ft and fps:
        ft = [1000.0 / f for f in fps if f > 0]
    if len(fps) < 30:
        return None
    fps_1pct = _percentile(fps, 0.01)
    fps_0_1pct = _percentile(fps, 0.001)
    fps_avg = sum(fps) / len(fps)
    ft_avg = sum(ft) / len(ft) if ft else (1000.0 / fps_avg if fps_avg else 0)
    ft_1pct = _percentile(ft, 0.99) if ft else (1000.0 / fps_1pct if fps_1pct else 0)
    return {
        "fps_avg": round(fps_avg, 1),
        "fps_1pct": round(fps_1pct, 1),
        "fps_0_1pct": round(fps_0_1pct, 1),
        "frametime_avg": round(ft_avg, 2),
        "frametime_1pct": round(ft_1pct, 2),
        "sample_count": len(fps),
        "path": str(path),
        "source": "mangohud",
    }


def _reset_stream(path_key: str) -> dict[str, Any]:
    st: dict[str, Any] = {
        "last_byte_offset": 0,
        "file_size": 0,
        "fps_key": None,
        "ft_key": None,
        "fieldnames": None,
        "pending": "",  # incomplete trailing line between ticks
        "fps_vals": [],
        "ft_vals": [],
        "summary": None,
        "mtime": 0.0,
    }
    _stream_state[path_key] = st
    # Bound number of tracked files
    if len(_stream_state) > 16:
        for k in list(_stream_state.keys())[:4]:
            if k != path_key:
                _stream_state.pop(k, None)
    return st


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
    """Parse a MangoHud log CSV into fps/frametime summary stats.

    Incremental O(1) path: after the first read we store ``last_byte_offset`` and
    on later ticks ``seek()`` + read only new bytes (see module state
    ``_stream_state``). Truncation / rotation (size < offset) resets to 0.
    """
    path_key = str(path)
    try:
        st_info = path.stat()
        size = st_info.st_size
        mtime = st_info.st_mtime
    except OSError:
        return None

    if size <= 0:
        return None
    # Pathological multi‑GB logs — refuse full rescan storms
    if size > _MAX_CSV_BYTES * 4:
        return None

    state = _stream_state.get(path_key)
    # Fast path: file unchanged since last successful summary
    if (
        state
        and state.get("summary") is not None
        and state.get("file_size") == size
        and state.get("mtime") == mtime
        and state.get("last_byte_offset", 0) >= size
    ):
        return state["summary"]

    # Truncation / new log overwrote same path
    if state and size < int(state.get("last_byte_offset") or 0):
        state = _reset_stream(path_key)
    if state is None:
        state = _reset_stream(path_key)

    fps_vals: list[float] = state["fps_vals"]
    ft_vals: list[float] = state["ft_vals"]
    offset = int(state.get("last_byte_offset") or 0)
    pending: str = state.get("pending") or ""

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            # --- First open or after reset: header + initial body --------------
            if state.get("fieldnames") is None or offset == 0 and not fps_vals and not ft_vals:
                # Huge brand-new file: start near the end (still need a header)
                if size > _MAX_CSV_BYTES and offset == 0:
                    fh.seek(0)
                    header_line = fh.readline()
                    if not header_line.strip():
                        return None
                    # Jump near end, discard partial line
                    fh.seek(max(0, size - _MAX_CSV_BYTES))
                    if fh.tell() > 0:
                        fh.readline()
                    sample = header_line + fh.read(min(4096, _MAX_CSV_BYTES))
                    try:
                        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t")
                    except csv.Error:
                        dialect = csv.excel
                    # Re-parse header fields from first line
                    header_reader = csv.reader([header_line], dialect=dialect)
                    try:
                        fieldnames = next(header_reader)
                    except StopIteration:
                        return None
                    fps_key, ft_key, names = _field_keys(fieldnames)
                    if not fps_key and not ft_key:
                        return None
                    state["fieldnames"] = names
                    state["fps_key"] = fps_key
                    state["ft_key"] = ft_key
                    state["dialect"] = dialect
                    # Body from current position to EOF
                    body = fh.read()
                    offset = fh.tell()
                else:
                    fh.seek(0)
                    sample = fh.read(4096)
                    if not sample.strip():
                        return None
                    fh.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                    except csv.Error:
                        dialect = csv.excel
                    reader = csv.DictReader(fh, dialect=dialect)
                    fps_key, ft_key, names = _field_keys(list(reader.fieldnames or []))
                    if not fps_key and not ft_key:
                        return None
                    state["fieldnames"] = names
                    state["fps_key"] = fps_key
                    state["ft_key"] = ft_key
                    state["dialect"] = dialect
                    for i, row in enumerate(reader):
                        if i >= _MAX_CSV_ROWS:
                            break
                        _append_row_values(
                            row,
                            fps_key=fps_key,
                            ft_key=ft_key,
                            fps_vals=fps_vals,
                            ft_vals=ft_vals,
                        )
                    offset = fh.tell()
                    pending = ""
            else:
                # --- Subsequent ticks: seek + only new lines -------------------
                fps_key = state["fps_key"]
                ft_key = state["ft_key"]
                dialect = state.get("dialect") or csv.excel
                names = state["fieldnames"] or []
                if size < offset:
                    # Truncation race
                    state = _reset_stream(path_key)
                    return parse_mangohud_csv(path)
                if size == offset and not pending:
                    # No new data
                    state["mtime"] = mtime
                    state["file_size"] = size
                    return state.get("summary")

                fh.seek(offset)
                chunk = fh.read()
                # Track absolute end after this read
                offset = fh.tell()
                text = pending + chunk
                if not text:
                    state["last_byte_offset"] = offset
                    state["file_size"] = size
                    state["mtime"] = mtime
                    return state.get("summary")

                # Keep incomplete trailing line for next tick
                if not text.endswith("\n") and not text.endswith("\r"):
                    last_nl = max(text.rfind("\n"), text.rfind("\r"))
                    if last_nl >= 0:
                        complete, pending = text[: last_nl + 1], text[last_nl + 1 :]
                    else:
                        # No complete line yet
                        state["pending"] = text
                        state["last_byte_offset"] = offset
                        state["file_size"] = size
                        state["mtime"] = mtime
                        return state.get("summary")
                else:
                    complete, pending = text, ""

                reader = csv.DictReader(
                    complete.splitlines(),
                    fieldnames=names,
                    dialect=dialect,
                )
                # DictReader treats first row as data when fieldnames provided
                for row in reader:
                    _append_row_values(
                        row,
                        fps_key=fps_key,
                        ft_key=ft_key,
                        fps_vals=fps_vals,
                        ft_vals=ft_vals,
                    )
    except OSError:
        return state.get("summary")

    _trim_samples(fps_vals, ft_vals)
    summary = _build_summary(path, fps_vals, ft_vals)

    state["last_byte_offset"] = offset
    state["file_size"] = size
    state["mtime"] = mtime
    state["pending"] = pending
    state["fps_vals"] = fps_vals
    state["ft_vals"] = ft_vals
    state["summary"] = summary
    _stream_state[path_key] = state
    return summary


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
