# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Persistent Pulse settings (retention, suppressed insights, etc.)."""

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


def _normalize_suppressed(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        iid = item.strip()
        if not iid or iid in seen:
            continue
        seen.add(iid)
        out.append(iid)
    return out


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"retention_days": DEFAULT_RETENTION_DAYS, "suppressed_insights": []}
    try:
        data = json.loads(CONFIG_PATH.read_text())
        if not isinstance(data, dict):
            raise ValueError("config must be object")
        days = _clamp(data.get("retention_days", DEFAULT_RETENTION_DAYS))
        return {
            "retention_days": days,
            "suppressed_insights": _normalize_suppressed(data.get("suppressed_insights", [])),
        }
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return {"retention_days": DEFAULT_RETENTION_DAYS, "suppressed_insights": []}


def get_retention_days() -> int:
    return load_config()["retention_days"]


def get_suppressed_insights() -> list[str]:
    return load_config()["suppressed_insights"]


def save_config(**updates: object) -> dict:
    cfg = load_config()
    if "retention_days" in updates:
        cfg["retention_days"] = _clamp(int(updates["retention_days"]))  # type: ignore[arg-type]
    if "suppressed_insights" in updates:
        cfg["suppressed_insights"] = _normalize_suppressed(updates["suppressed_insights"])
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    except OSError:
        pass
    return cfg


def save_retention_days(days: int) -> int:
    return save_config(retention_days=days)["retention_days"]


def suppress_insight(insight_id: str) -> list[str]:
    cfg = load_config()
    iid = (insight_id or "").strip()
    if not iid:
        return cfg["suppressed_insights"]
    suppressed = list(cfg["suppressed_insights"])
    if iid not in suppressed:
        suppressed.append(iid)
    return save_config(suppressed_insights=suppressed)["suppressed_insights"]


def unsuppress_insight(insight_id: str) -> list[str]:
    cfg = load_config()
    iid = (insight_id or "").strip()
    suppressed = [x for x in cfg["suppressed_insights"] if x != iid]
    return save_config(suppressed_insights=suppressed)["suppressed_insights"]


def estimate_max_mb(days: int | None = None) -> float:
    d = days if days is not None else get_retention_days()
    return round(d * SAMPLES_PER_DAY * BYTES_PER_SAMPLE_EST / 1024**2, 1)