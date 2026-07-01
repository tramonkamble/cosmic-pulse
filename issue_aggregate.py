# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Cross-game issue aggregation and priority scoring."""

from __future__ import annotations

import time

from games import ALL_GAME_IDS, GAMES

LEVEL_SCORE = {"hot": 100, "warn": 70, "info": 40, "ok": 10}
MULTI_GAME_BOOST = 22  # extra priority per additional game affected


def hint_applies_to(hint: dict, game_id: str) -> bool:
    scope = hint.get("games") or ["all"]
    if "all" in scope:
        return True
    return game_id in scope


def _games_for_active(hint: dict, running_ids: list[str]) -> list[str]:
    return [gid for gid in ALL_GAME_IDS if hint_applies_to(hint, gid) and gid in running_ids]


def enrich_hint(item: dict) -> dict:
    games_seen = item.get("games_seen") or {}
    game_list = sorted(games_seen.keys())
    game_count = len(game_list)
    level = item.get("level", "info")
    score = LEVEL_SCORE.get(level, 40) + max(0, game_count - 1) * MULTI_GAME_BOOST
    out = dict(item)
    out["game_count"] = game_count
    out["games_affected"] = game_list
    out["priority_score"] = score
    out["multi_game"] = game_count > 1
    return out


def merge_games_seen(history_item: dict, game_ids: list[str], now: float) -> None:
    seen = history_item.setdefault("games_seen", {})
    for gid in game_ids:
        seen[gid] = now


def build_issue_views(
    active: list[dict],
    history: list[dict],
    running_ids: list[str],
) -> dict:
    """Build overall prioritized list and per-game issue sections."""
    active_ids = {h["insight_id"] for h in active if h.get("insight_id")}

    # Overall: active insights enriched with cross-game weight
    overall_map: dict[str, dict] = {}
    for item in history:
        iid = item.get("insight_id")
        if not iid or not item.get("active"):
            continue
        overall_map[iid] = enrich_hint(item)

    # Active but not yet in history (edge case)
    for h in active:
        iid = h.get("insight_id")
        if iid and iid not in overall_map:
            overall_map[iid] = enrich_hint({**h, "games_seen": {g: time.time() for g in _games_for_active(h, running_ids)}})

    overall_active = sorted(
        overall_map.values(),
        key=lambda x: (-x["priority_score"], -x.get("last_seen", 0)),
    )
    inactive = [
        enrich_hint(item)
        for item in history
        if not item.get("active") and item.get("insight_id") and item["insight_id"] not in overall_map
    ]
    overall = overall_active + inactive

    # Per-game: issues that apply to this game and were seen while playing it (or active now while running)
    by_game: dict[str, dict] = {}
    for gid, meta in GAMES.items():
        game_issues: list[dict] = []
        for item in overall:
            if not hint_applies_to(item, gid):
                continue
            seen = item.get("games_seen") or {}
            if gid in seen or (gid in running_ids and item.get("insight_id") in active_ids):
                game_issues.append(item)
        by_game[gid] = {
            "id": gid,
            "name": meta["name"],
            "short": meta["short"],
            "running": gid in running_ids,
            "issues": game_issues,
            "issue_count": len(game_issues),
        }

    return {"overall": overall, "by_game": by_game}