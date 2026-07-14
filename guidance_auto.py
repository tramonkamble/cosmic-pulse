# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Auto-resolve guidance when live conditions stay clear (no extra scans)."""

from __future__ import annotations

from collections.abc import Callable

# Sustained absence from live rule eval before moving to Fixed.
AUTO_RESOLVE_CLEAR_SEC = 60
CLEAR_SINCE_KEY = "_clear_since"

# Hints backed by diagnostics — re-verify with a fresh scan before auto-resolving.
DIAG_BACKED_INSIGHTS = frozenset(
    {
        "game-libs-missing",
        "steam-disk-low",
        "vulkan-broken",
        "game-files-corrupt",
        "game-update-pending",
        "game-prefix-reset",
    }
)


def seed_clear_timers(
    history: list[dict],
    active_ids: set[str],
    resolved_ids: set[str],
    suppressed_ids: set[str],
    now: float,
) -> bool:
    """Start clear timers for stale outstanding hints (uses last_seen so old fixes resolve fast)."""
    changed = False
    for item in history:
        iid = item.get("insight_id")
        if not iid or iid in resolved_ids or iid in suppressed_ids:
            continue
        if iid in active_ids:
            continue
        if CLEAR_SINCE_KEY not in item:
            item[CLEAR_SINCE_KEY] = float(item.get("last_seen") or now)
            changed = True
    return changed


def tick_auto_resolve(
    history: list[dict],
    active_ids: set[str],
    resolved_ids: set[str],
    suppressed_ids: set[str],
    now: float,
    resolve_callback: Callable[[str], None],
    *,
    fresh_active_ids: Callable[[], set[str]] | None = None,
) -> bool:
    """
    Mark outstanding hints fixed when they leave active_ids long enough.

    Piggybacks on the existing sampler tick — O(history) set lookups only.
    Ignored and user-marked-fixed IDs are skipped. Clears timer when a hint fires again.
    """
    changed = False
    to_resolve: list[str] = []
    for item in history:
        iid = item.get("insight_id")
        if not iid or iid in resolved_ids or iid in suppressed_ids:
            continue
        if iid in active_ids:
            if CLEAR_SINCE_KEY in item:
                item.pop(CLEAR_SINCE_KEY, None)
                changed = True
            continue
        clear_since = item.get(CLEAR_SINCE_KEY)
        if clear_since is None:
            item[CLEAR_SINCE_KEY] = now
            changed = True
            continue
        if now - float(clear_since) >= AUTO_RESOLVE_CLEAR_SEC:
            if iid in DIAG_BACKED_INSIGHTS and fresh_active_ids is not None:
                if iid in fresh_active_ids():
                    item[CLEAR_SINCE_KEY] = now
                    changed = True
                    continue
            to_resolve.append(iid)
            item.pop(CLEAR_SINCE_KEY, None)
            changed = True
    for iid in to_resolve:
        resolve_callback(iid)
        resolved_ids.add(iid)
    return changed or bool(to_resolve)
