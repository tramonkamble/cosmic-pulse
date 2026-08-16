# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Auto-resolve guidance when live conditions stay clear (no extra scans)."""

from __future__ import annotations

from collections.abc import Callable

from pulse_config import STATE_VERIFIED_INSIGHTS

# Sustained absence from live rule eval before moving to Fixed.
# Keep short: users apply a step and expect the card to go away within a moment.
AUTO_RESOLVE_CLEAR_SEC = 20
CLEAR_SINCE_KEY = "_clear_since"
# Live-condition hold so UI badges do not flap on/off every 1 Hz tick.
LIVE_HOLD_SEC = 12.0
COOLDOWN_UNTIL_KEY = "cooldown_until"

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


def _parse_timestamp(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


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
            item[CLEAR_SINCE_KEY] = _parse_timestamp(item.get("last_seen")) or now
            changed = True
    return changed


def _as_id_set(ids: set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    """Normalize active/resolved/suppressed collections to a set once per tick."""
    if ids is None:
        return set()
    if isinstance(ids, set):
        return ids
    return set(ids)


def apply_live_hysteresis(
    history: list[dict],
    active_ids: set[str],
    now: float,
) -> set[str]:
    """Hold ``condition_live`` for LIVE_HOLD_SEC after last true evaluation.

    When a rule matches: ``cooldown_until = now + LIVE_HOLD_SEC``.
    When it stops matching: stay live until ``now > cooldown_until``.
    Returns the set of insight ids considered live after hysteresis (for resolve timers).
    """
    active = _as_id_set(active_ids)
    live_ids: set[str] = set()
    for item in history:
        iid = item.get("insight_id")
        if not iid:
            item["condition_live"] = False
            continue
        if iid in active:
            item[COOLDOWN_UNTIL_KEY] = now + LIVE_HOLD_SEC
            item["condition_live"] = True
            live_ids.add(iid)
            continue
        until = _parse_timestamp(item.get(COOLDOWN_UNTIL_KEY))
        if until is not None and now < until:
            item["condition_live"] = True
            live_ids.add(iid)
        else:
            item["condition_live"] = False
            # Drop stale cooldown so future logic does not revive
            if until is not None and now >= until:
                item.pop(COOLDOWN_UNTIL_KEY, None)
    return live_ids


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

    Respects LIVE_HOLD_SEC hysteresis: while ``cooldown_until`` is in the future,
    the rule is still treated as live (no resolve timer progress).

    Complexity per tick:
    - O(P) to normalize id sets
    - O(N) over history with O(1) set membership
    - At most **one** call to ``fresh_active_ids``
    """
    # O(1) lookups — never re-scan lists inside the history loop.
    active = _as_id_set(active_ids)
    resolved = _as_id_set(resolved_ids)
    suppressed = _as_id_set(suppressed_ids)

    changed = False
    to_resolve: list[str] = []
    # Lazy: evaluate fresh_active_ids at most once per tick, then set membership.
    fresh_ids: set[str] | None = None

    def _fresh_diag_ids() -> set[str]:
        nonlocal fresh_ids
        if fresh_active_ids is None:
            return set()
        if fresh_ids is None:
            raw = fresh_active_ids()
            fresh_ids = _as_id_set(raw)
        return fresh_ids

    for item in history:
        iid = item.get("insight_id")
        if not iid or iid in resolved or iid in suppressed:
            continue
        if iid in STATE_VERIFIED_INSIGHTS:
            item.pop(CLEAR_SINCE_KEY, None)
            continue
        # Still in live hold window — do not start or advance clear timer.
        until = _parse_timestamp(item.get(COOLDOWN_UNTIL_KEY))
        holding = until is not None and now < until
        if iid in active or holding:
            if iid in active:
                item[COOLDOWN_UNTIL_KEY] = now + LIVE_HOLD_SEC
            if CLEAR_SINCE_KEY in item:
                item.pop(CLEAR_SINCE_KEY, None)
                changed = True
            continue
        clear_since = item.get(CLEAR_SINCE_KEY)
        if clear_since is None:
            item[CLEAR_SINCE_KEY] = now
            changed = True
            continue
        clear_at = _parse_timestamp(clear_since)
        if clear_at is None:
            item[CLEAR_SINCE_KEY] = now
            changed = True
            continue
        if now - clear_at >= AUTO_RESOLVE_CLEAR_SEC:
            if iid in DIAG_BACKED_INSIGHTS and fresh_active_ids is not None:
                if iid in _fresh_diag_ids():
                    item[CLEAR_SINCE_KEY] = now
                    changed = True
                    continue
            to_resolve.append(iid)
            item.pop(CLEAR_SINCE_KEY, None)
            changed = True
    for iid in to_resolve:
        resolve_callback(iid)
        # When caller passed a set, resolved is that same object (_as_id_set).
        resolved.add(iid)
        if resolved is not resolved_ids and isinstance(resolved_ids, set):
            resolved_ids.add(iid)
    return changed or bool(to_resolve)
