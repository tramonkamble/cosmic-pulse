# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Cross-game issue aggregation and priority scoring."""

from __future__ import annotations

import time

from games import LEGACY_GAME_IDS, game_meta, normalize_game_id
from pulse_config import get_insight_pref_sets

LEVEL_SCORE = {"hot": 100, "warn": 70, "info": 40, "ok": 10}
MULTI_GAME_BOOST = 22  # extra priority per additional game affected


def hint_applies_to(hint: dict, game_id: str) -> bool:
    game_id = normalize_game_id(game_id) or game_id
    scope = hint.get("games") or ["all"]
    if "all" in scope:
        return True
    normed = {normalize_game_id(g) for g in scope if normalize_game_id(g)}
    return game_id in normed


def _games_for_active(hint: dict, running_ids: list[str]) -> list[str]:
    return [gid for gid in running_ids if hint_applies_to(hint, gid)]


def enrich_hint(
    item: dict,
    *,
    live_ids: set[str] | None = None,
    resolved_ids: set[str] | None = None,
    suppressed_ids: set[str] | None = None,
) -> dict:
    games_seen = item.get("games_seen") or {}
    game_list = sorted(games_seen.keys())
    game_count = len(game_list)
    level = item.get("level", "info")
    score = LEVEL_SCORE.get(level, 40) + max(0, game_count - 1) * MULTI_GAME_BOOST
    iid = item.get("insight_id") or ""
    live = live_ids or set()
    resolved = resolved_ids or set()
    suppressed = suppressed_ids or set()
    out = dict(item)
    out["game_count"] = game_count
    out["games_affected"] = game_list
    out["priority_score"] = score
    out["multi_game"] = game_count > 1
    out["condition_live"] = bool(iid and iid in live)
    if iid in suppressed:
        out["user_status"] = "ignored"
    elif iid in resolved:
        out["user_status"] = "resolved"
    else:
        out["user_status"] = "outstanding"
    out["active"] = out["user_status"] == "outstanding"
    return out


def guidance_sort_key(item: dict) -> tuple:
    """Stable Guidance ordering: severity, priority, then first_seen."""
    level = item.get("level", "info")
    rank = {"hot": 0, "warn": 1, "info": 2, "ok": 3}.get(level, 9)
    games_seen = item.get("games_seen") or {}
    score = LEVEL_SCORE.get(level, 40) + max(0, len(games_seen) - 1) * MULTI_GAME_BOOST
    return (rank, -score, item.get("first_seen", 0), item.get("insight_id", ""))


def merge_games_seen(history_item: dict, game_ids: list[str], now: float) -> None:
    seen = history_item.setdefault("games_seen", {})
    for gid in game_ids:
        norm = normalize_game_id(gid)
        if norm:
            seen[norm] = max(seen.get(norm, 0), now)


def _normalize_games_seen(seen: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for gid, ts in (seen or {}).items():
        norm = normalize_game_id(gid)
        if norm:
            out[norm] = max(out.get(norm, 0), float(ts or 0))
    return out


def build_issue_views(
    active: list[dict],
    history: list[dict],
    running_ids: list[str],
    games_state: dict | None = None,
) -> dict:
    """Build overall prioritized list and per-game issue sections.

    ``overall`` merges outstanding history with resolved (marked-fixed) items.
    ``condition_live`` is enriched per tick but does not remove outstanding rows.
    """
    active_ids = {h["insight_id"] for h in active if h.get("insight_id")}
    # Prefer hysteresis-held live flags from history (15s hold), not raw tick matches
    live_ids = {
        item.get("insight_id")
        for item in history
        if item.get("insight_id") and item.get("condition_live")
    } or active_ids
    resolved_ids, suppressed_ids = get_insight_pref_sets()

    def enrich(item):
        return enrich_hint(
            item,
            live_ids=live_ids,
            resolved_ids=resolved_ids,
            suppressed_ids=suppressed_ids,
        )

    outstanding_map: dict[str, dict] = {}
    for item in history:
        iid = item.get("insight_id")
        if not iid or iid in resolved_ids or iid in suppressed_ids:
            continue
        outstanding_map[iid] = enrich(item)

    for h in active:
        iid = h.get("insight_id")
        if (
            iid
            and iid not in outstanding_map
            and iid not in resolved_ids
            and iid not in suppressed_ids
        ):
            outstanding_map[iid] = enrich(
                {
                    **h,
                    "games_seen": {g: time.time() for g in _games_for_active(h, running_ids)},
                }
            )

    outstanding = sorted(outstanding_map.values(), key=guidance_sort_key)
    resolved = sorted(
        [enrich(item) for item in history if item.get("insight_id") in resolved_ids],
        key=lambda x: -x.get("last_seen", 0),
    )
    overall = outstanding + resolved

    # Per-game: running titles + games referenced by outstanding issues.
    norm_running = {normalize_game_id(g) for g in running_ids if normalize_game_id(g)}
    game_ids: set[str] = set(norm_running)
    if games_state:
        for gid in games_state:
            norm = normalize_game_id(gid)
            if norm:
                game_ids.add(norm)
    for item in outstanding:
        for gid in item.get("games_seen") or {}:
            norm = normalize_game_id(gid)
            if norm:
                game_ids.add(norm)
    for legacy, canonical in LEGACY_GAME_IDS.items():
        if canonical in game_ids:
            game_ids.discard(legacy)

    by_game: dict[str, dict] = {}
    for gid in sorted(game_ids, key=lambda x: (x not in norm_running, x)):
        legacy_gid = next((k for k, v in LEGACY_GAME_IDS.items() if v == gid), None)
        src = (games_state or {}).get(gid) or (games_state or {}).get(legacy_gid) or game_meta(gid)
        game_issues: list[dict] = []
        for item in outstanding:
            if not hint_applies_to(item, gid):
                continue
            seen = _normalize_games_seen(item.get("games_seen") or {})
            if gid in seen or (gid in norm_running and item.get("insight_id") in active_ids):
                game_issues.append(item)
        if not game_issues and gid not in norm_running:
            continue
        by_game[gid] = {
            "id": gid,
            "name": src.get("name", f"AppID {gid}"),
            "short": src.get("short", src.get("name", gid)),
            "running": gid in norm_running,
            "issues": game_issues,
            "issue_count": len(game_issues),
        }

    return {"overall": overall, "by_game": by_game}
