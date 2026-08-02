# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Persistent Pulse settings (retention, suppressed insights, etc.)."""

from __future__ import annotations

import json

from paths import data_dir

CONFIG_PATH = data_dir() / ".pulse_config.json"
_config_cache: tuple[float, dict] | None = None

DEFAULT_RETENTION_DAYS = 10
DEFAULT_UI_SCALE = 1.5
DEFAULT_TUNING_LOG_MAX = 48
DEFAULT_THEME_MODE = "cosmic"

# Guidance that must match live system state — reopens when detected again after "Fixed".
STATE_VERIFIED_INSIGHTS = frozenset({"proton-wayland-launch-fix"})
RETENTION_PRESETS = [3, 7, 10, 14, 30]
RETENTION_MIN_DAYS = 1
RETENTION_MAX_DAYS = 90
UI_SCALE_MIN = 1.0
UI_SCALE_MAX = 2.0
UI_SCALE_STEP = 0.05
TUNING_LOG_PRESETS = [24, 48, 96, 200]
TUNING_LOG_MIN = 8
TUNING_LOG_MAX_CAP = 500
# cosmic = desktop tokens; system = prefers-color-scheme; dark/light = forced chrome
THEME_MODES = ("cosmic", "system", "dark", "light")
BYTES_PER_SAMPLE_EST = 200
SAMPLES_PER_DAY = 86400


def _clamp(days: int) -> int:
    return max(RETENTION_MIN_DAYS, min(RETENTION_MAX_DAYS, int(days)))


def _clamp_ui_scale(value: object) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_UI_SCALE
    # Snap to 0.05 so sliders don't thrash float noise
    stepped = round(v / UI_SCALE_STEP) * UI_SCALE_STEP
    return max(UI_SCALE_MIN, min(UI_SCALE_MAX, round(stepped, 2)))


def _clamp_tuning_log_max(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TUNING_LOG_MAX
    return max(TUNING_LOG_MIN, min(TUNING_LOG_MAX_CAP, n))


def _normalize_theme_mode(value: object) -> str:
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode in THEME_MODES:
            return mode
    return DEFAULT_THEME_MODE


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


def _normalize_insight_ids(items: object) -> list[str]:
    return _normalize_suppressed(items)


def _normalize_str_list(items: object) -> list[str]:
    """Dedupe non-empty strings preserving order (pack ids, paths)."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _config_mtime() -> float:
    try:
        return CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0.0
    except OSError:
        return 0.0


def _default_config() -> dict:
    return {
        "retention_days": DEFAULT_RETENTION_DAYS,
        "ui_scale": DEFAULT_UI_SCALE,
        "tuning_log_max": DEFAULT_TUNING_LOG_MAX,
        "theme_mode": DEFAULT_THEME_MODE,
        "disabled_packs": [],
        "rule_pack_paths": [],
        "suppressed_insights": [],
        "resolved_insights": [],
    }


def invalidate_config_cache() -> None:
    global _config_cache
    _config_cache = None


def load_config() -> dict:
    global _config_cache
    mtime = _config_mtime()
    if _config_cache and _config_cache[0] == mtime:
        return _config_cache[1]

    if not CONFIG_PATH.exists():
        cfg = _default_config()
    else:
        try:
            data = json.loads(CONFIG_PATH.read_text())
            if not isinstance(data, dict):
                raise ValueError("config must be object")
            days = _clamp(data.get("retention_days", DEFAULT_RETENTION_DAYS))
            cfg = {
                "retention_days": days,
                "ui_scale": _clamp_ui_scale(data.get("ui_scale", DEFAULT_UI_SCALE)),
                "tuning_log_max": _clamp_tuning_log_max(
                    data.get("tuning_log_max", DEFAULT_TUNING_LOG_MAX)
                ),
                "theme_mode": _normalize_theme_mode(data.get("theme_mode", DEFAULT_THEME_MODE)),
                "disabled_packs": _normalize_str_list(data.get("disabled_packs", [])),
                "rule_pack_paths": _normalize_str_list(data.get("rule_pack_paths", [])),
                "suppressed_insights": _normalize_insight_ids(data.get("suppressed_insights", [])),
                "resolved_insights": _normalize_insight_ids(data.get("resolved_insights", [])),
            }
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            cfg = _default_config()
    _config_cache = (mtime, cfg)
    return cfg


def get_retention_days() -> int:
    return load_config()["retention_days"]


def get_ui_scale() -> float:
    return load_config()["ui_scale"]


def get_tuning_log_max() -> int:
    return load_config()["tuning_log_max"]


def get_theme_mode() -> str:
    return load_config()["theme_mode"]


def get_disabled_packs() -> list[str]:
    return load_config()["disabled_packs"]


def get_rule_pack_paths() -> list[str]:
    return load_config()["rule_pack_paths"]


def get_suppressed_insights() -> list[str]:
    return load_config()["suppressed_insights"]


def get_resolved_insights() -> list[str]:
    return load_config()["resolved_insights"]


def get_insight_pref_sets() -> tuple[set[str], set[str]]:
    """Resolved + suppressed insight IDs in one config read."""
    cfg = load_config()
    return set(cfg["resolved_insights"]), set(cfg["suppressed_insights"])


def save_config(**updates: object) -> dict:
    cfg = load_config()
    if "retention_days" in updates:
        cfg["retention_days"] = _clamp(int(updates["retention_days"]))  # type: ignore[arg-type]
    if "ui_scale" in updates:
        cfg["ui_scale"] = _clamp_ui_scale(updates["ui_scale"])
    if "tuning_log_max" in updates:
        cfg["tuning_log_max"] = _clamp_tuning_log_max(updates["tuning_log_max"])
    if "theme_mode" in updates:
        cfg["theme_mode"] = _normalize_theme_mode(updates["theme_mode"])
    if "disabled_packs" in updates:
        cfg["disabled_packs"] = _normalize_str_list(updates["disabled_packs"])
    if "rule_pack_paths" in updates:
        cfg["rule_pack_paths"] = _normalize_str_list(updates["rule_pack_paths"])
    if "suppressed_insights" in updates:
        cfg["suppressed_insights"] = _normalize_insight_ids(updates["suppressed_insights"])
    if "resolved_insights" in updates:
        cfg["resolved_insights"] = _normalize_insight_ids(updates["resolved_insights"])
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
        global _config_cache
        _config_cache = (_config_mtime(), cfg)
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


def resolve_insight(insight_id: str) -> list[str]:
    cfg = load_config()
    iid = (insight_id or "").strip()
    if not iid:
        return cfg["resolved_insights"]
    resolved = list(cfg["resolved_insights"])
    if iid not in resolved:
        resolved.append(iid)
    suppressed = [x for x in cfg["suppressed_insights"] if x != iid]
    return save_config(resolved_insights=resolved, suppressed_insights=suppressed)[
        "resolved_insights"
    ]


def unresolve_insight(insight_id: str) -> list[str]:
    cfg = load_config()
    iid = (insight_id or "").strip()
    resolved = [x for x in cfg["resolved_insights"] if x != iid]
    return save_config(resolved_insights=resolved)["resolved_insights"]


def estimate_max_mb(days: int | None = None) -> float:
    d = days if days is not None else get_retention_days()
    return round(d * SAMPLES_PER_DAY * BYTES_PER_SAMPLE_EST / 1024**2, 1)
