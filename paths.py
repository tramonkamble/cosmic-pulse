# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Resolve install root (read-only code) vs data dir (writable local state)."""

from __future__ import annotations

import os
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
_DATA_DIR: Path | None = None


def app_root() -> Path:
    """Application tree: Python modules, index.html, rules/."""
    return _APP_ROOT


def _default_data_dir() -> Path:
    override = os.environ.get("PULSE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    root = _APP_ROOT
    # Debian/apt install under /usr or /opt — state lives in XDG data home.
    if any(root.is_relative_to(p) for p in (Path("/usr"), Path("/opt"))):
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "cosmic-pulse"
    return root


def data_dir(*, create: bool = True) -> Path:
    """Writable state: pulse.db, .pulse_config.json, tuning log, caches."""
    global _DATA_DIR
    if _DATA_DIR is None:
        _DATA_DIR = _default_data_dir()
        if create:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def reset_data_dir_cache() -> None:
    """Test helper — re-read PULSE_DATA_DIR / heuristics."""
    global _DATA_DIR
    _DATA_DIR = None