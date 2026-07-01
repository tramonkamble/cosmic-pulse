# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Persistent Pulse settings (retention, etc.)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / ".pulse_config.json"

DEFAULT_RETENTION_DAYS = 10
RETENTION_PRESETS = [3, 7, 10, 14, 30]
RETENTION_MIN_DAYS = 1
RETENTION_MAX_DAYS = 90
BYTES_PER_SAMPLE_EST = 200
SAMPLES_PER_DAY = 86400

FIX_CLOSE_APP_IDS = ("firefox", "brave", "discord")
FIX_CLOSE_APP_LABELS = {
    "firefox": "Firefox",
    "brave": "Brave",
    "discord": "Discord",
}
DEFAULT_FIX_CLOSE_APPS = {
    "firefox": True,
    "brave": False,
    "discord": True,
}


def _clamp(days: int) -> int:
    return max(RETENTION_MIN_DAYS, min(RETENTION_MAX_DAYS, int(days)))


def _normalize_fix_close_apps(raw: object) -> dict[str, bool]:
    out = dict(DEFAULT_FIX_CLOSE_APPS)
    if isinstance(raw, dict):
        for key in FIX_CLOSE_APP_IDS:
            if key in raw:
                out[key] = bool(raw[key])
    return out


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "retention_days": DEFAULT_RETENTION_DAYS,
            "fix_close_apps": dict(DEFAULT_FIX_CLOSE_APPS),
        }
    try:
        data = json.loads(CONFIG_PATH.read_text())
        if not isinstance(data, dict):
            raise ValueError("config must be object")
        days = _clamp(data.get("retention_days", DEFAULT_RETENTION_DAYS))
        return {
            "retention_days": days,
            "fix_close_apps": _normalize_fix_close_apps(data.get("fix_close_apps")),
        }
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return {
            "retention_days": DEFAULT_RETENTION_DAYS,
            "fix_close_apps": dict(DEFAULT_FIX_CLOSE_APPS),
        }


def get_retention_days() -> int:
    return load_config()["retention_days"]


def get_fix_close_apps() -> dict[str, bool]:
    return dict(load_config()["fix_close_apps"])


def save_config(**updates: object) -> dict:
    cfg = load_config()
    if "retention_days" in updates:
        cfg["retention_days"] = _clamp(int(updates["retention_days"]))  # type: ignore[arg-type]
    if "fix_close_apps" in updates:
        cfg["fix_close_apps"] = _normalize_fix_close_apps(updates["fix_close_apps"])
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    except OSError:
        pass
    return cfg


def save_retention_days(days: int) -> int:
    return save_config(retention_days=days)["retention_days"]


def save_fix_close_apps(apps: dict) -> dict[str, bool]:
    return save_config(fix_close_apps=apps)["fix_close_apps"]


def estimate_max_mb(days: int | None = None) -> float:
    d = days if days is not None else get_retention_days()
    return round(d * SAMPLES_PER_DAY * BYTES_PER_SAMPLE_EST / 1024**2, 1)