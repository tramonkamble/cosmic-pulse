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


def _clamp(days: int) -> int:
    return max(RETENTION_MIN_DAYS, min(RETENTION_MAX_DAYS, int(days)))


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"retention_days": DEFAULT_RETENTION_DAYS}
    try:
        data = json.loads(CONFIG_PATH.read_text())
        if not isinstance(data, dict):
            raise ValueError("config must be object")
        days = _clamp(data.get("retention_days", DEFAULT_RETENTION_DAYS))
        return {"retention_days": days}
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return {"retention_days": DEFAULT_RETENTION_DAYS}


def get_retention_days() -> int:
    return load_config()["retention_days"]


def save_retention_days(days: int) -> int:
    days = _clamp(days)
    try:
        CONFIG_PATH.write_text(json.dumps({"retention_days": days}, indent=2) + "\n")
    except OSError:
        pass
    return days


def estimate_max_mb(days: int | None = None) -> float:
    d = days if days is not None else get_retention_days()
    return round(d * SAMPLES_PER_DAY * BYTES_PER_SAMPLE_EST / 1024**2, 1)