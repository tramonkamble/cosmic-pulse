# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Per-game performance sessions — live stats, rating, SQLite persistence."""

from __future__ import annotations

import time
from typing import Any

from games import game_meta
from stutter import _percentile

MIN_SESSION_SAMPLES = 30  # ~30s at 1 Hz after load grace
LOAD_GRACE_SEC = 45  # wait after detect before counting (loading / menus)
MAX_TREND_POINTS = 600  # cap stored trend samples per session


def compute_rating(agg: dict[str, Any]) -> float:
    """0–100 performance rating for a completed or in-progress session."""
    smooth = float(agg.get("smoothness_avg") or (100 - (agg.get("stutter_score_avg") or 0)))
    score_avg = float(agg.get("stutter_score_avg") or 0)
    hitch_1pct = float(agg.get("hitch_ms_1pct") or 0)
    events = int(agg.get("hitch_events") or 0)
    duration_sec = max(float(agg.get("duration_sec") or 1), 1.0)
    events_per_min = events / (duration_sec / 60.0)

    hitch_component = max(0.0, 100.0 - hitch_1pct * 0.35 - events_per_min * 12.0)
    rating = smooth * 0.50 + (100.0 - score_avg) * 0.25 + hitch_component * 0.20
    gpu_avg = agg.get("gpu_busy_avg")
    if gpu_avg is not None and float(gpu_avg) < 95:
        rating += min(5.0, (95.0 - float(gpu_avg)) * 0.08)
    return round(max(0.0, min(100.0, rating)), 1)


def rating_tier(rating: float) -> str:
    if rating >= 85:
        return "excellent"
    if rating >= 70:
        return "good"
    if rating >= 55:
        return "fair"
    if rating >= 40:
        return "poor"
    return "bad"


def _new_accumulator(game_id: str, game_name: str | None, ts: float) -> dict[str, Any]:
    meta = game_meta(game_id)
    return {
        "game_id": game_id,
        "game_name": game_name or meta.get("name") or f"AppID {game_id}",
        "started_ts": ts,
        "last_ts": ts,
        "stutter_scores": [],
        "hitch_ms": [],
        "hitch_events": 0,
        "game_cpu_sum": 0.0,
        "gpu_busy_sum": 0.0,
        "ram_pct_sum": 0.0,
        "sample_count": 0,
        "trend_points": [],
    }


def _new_pending(game_id: str, game_name: str | None, ts: float) -> dict[str, Any]:
    meta = game_meta(game_id)
    return {
        "game_id": game_id,
        "game_name": game_name or meta.get("name") or f"AppID {game_id}",
        "detected_ts": ts,
    }


def _aggregate(acc: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    scores = acc["stutter_scores"]
    hitch_ms = acc["hitch_ms"]
    n = acc["sample_count"] or 1
    score_avg = sum(scores) / len(scores) if scores else 0.0
    duration = max((acc.get("last_ts") or now) - acc["started_ts"], 1.0)
    agg = {
        "game_id": acc["game_id"],
        "game_name": acc["game_name"],
        "started_ts": acc["started_ts"],
        "ended_ts": acc.get("last_ts") or now,
        "duration_sec": round(duration, 1),
        "stutter_score_avg": round(score_avg, 1),
        "smoothness_avg": round(100.0 - score_avg, 1),
        "hitch_ms_1pct": round(_percentile(hitch_ms, 0.99), 1),
        "hitch_events": acc["hitch_events"],
        "game_cpu_avg": round(acc["game_cpu_sum"] / n, 1),
        "gpu_busy_avg": round(acc["gpu_busy_sum"] / n, 1),
        "ram_pct_avg": round(acc["ram_pct_sum"] / n, 1),
        "sample_count": acc["sample_count"],
    }
    agg["rating"] = compute_rating({**agg, "duration_sec": duration})
    agg["rating_tier"] = rating_tier(agg["rating"])
    agg["trend"] = _downsample_trend(acc.get("trend_points") or [])
    return agg


def _downsample_trend(points: list[dict], max_n: int = MAX_TREND_POINTS) -> list[dict]:
    if len(points) <= max_n:
        return points
    step = len(points) / max_n
    return [points[int(i * step)] for i in range(max_n)]


class GameSessionTracker:
    """Track one active game session; finalize to SQLite on exit or game switch."""

    def __init__(self) -> None:
        self._active: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._last_session: dict[str, Any] | None = None

    def _accumulate(self, snap: dict) -> None:
        if not self._active:
            return
        acc = self._active
        ts = snap.get("ts") or time.time()
        acc["last_ts"] = ts
        acc["sample_count"] += 1

        st = snap.get("stutter") or {}
        score = float(st.get("score") or 0)
        acc["stutter_scores"].append(score)
        acc["hitch_ms"].append(float(st.get("est_ms") or 0))
        if st.get("event"):
            acc["hitch_events"] += 1

        gt = snap.get("game_totals") or {}
        acc["game_cpu_sum"] += float(gt.get("cpu_pct") or 0)
        dgpu = (snap.get("gpu") or {}).get("discrete") or {}
        acc["gpu_busy_sum"] += float(dgpu.get("busy_pct") or 0)
        mem = snap.get("memory") or {}
        acc["ram_pct_sum"] += float(mem.get("pct") or 0)
        acc.setdefault("trend_points", []).append(
            {
                "ts": ts,
                "smoothness": st.get("smoothness"),
                "stutter_score": st.get("score"),
                "game_cpu": gt.get("cpu_pct"),
                "gpu_busy": dgpu.get("busy_pct"),
            }
        )

    def _store_finished(self, row: dict[str, Any]) -> None:
        self._last_session = row

    def _idle_response(self) -> dict[str, Any]:
        out: dict[str, Any] = {"active": False}
        if self._last_session:
            out["last_session"] = self._last_session
        return out

    def _finalize(self) -> dict[str, Any] | None:
        if not self._active or self._active["sample_count"] < MIN_SESSION_SAMPLES:
            self._active = None
            return None
        row = _aggregate(self._active)
        self._active = None
        return row

    def _clear_all(self) -> dict[str, Any] | None:
        finished = self._finalize() if self._active else None
        self._pending = None
        return finished

    def _loading_response(self, ts: float) -> dict[str, Any]:
        pending = self._pending or {}
        elapsed = ts - pending.get("detected_ts", ts)
        remaining = max(0.0, LOAD_GRACE_SEC - elapsed)
        return {
            "active": True,
            "recording": False,
            "phase": "loading",
            "game_id": pending.get("game_id"),
            "game_name": pending.get("game_name"),
            "detected_ts": pending.get("detected_ts"),
            "load_grace_sec": LOAD_GRACE_SEC,
            "load_remaining_sec": round(remaining, 1),
        }

    def tick(self, snap: dict, *, save_session) -> dict[str, Any]:
        """Update session state; return live performance block for the API."""
        gt = snap.get("game_totals") or {}
        game_id = gt.get("game_id") if gt.get("running") else None
        ts = snap.get("ts") or time.time()

        if self._active and self._active["game_id"] != game_id:
            finished = self._finalize()
            if finished:
                self._store_finished(finished)
                save_session(finished)
            self._active = None

        if self._pending and self._pending["game_id"] != game_id:
            self._pending = None

        if not game_id:
            finished = self._clear_all()
            if finished:
                self._store_finished(finished)
                save_session(finished)
            return self._idle_response()

        if not self._active and not self._pending:
            self._pending = _new_pending(game_id, gt.get("game_name"), ts)

        if self._pending:
            if ts - self._pending["detected_ts"] < LOAD_GRACE_SEC:
                return self._loading_response(ts)
            self._active = _new_accumulator(
                self._pending["game_id"],
                self._pending["game_name"],
                ts,
            )
            self._pending = None

        if self._active:
            self._accumulate(snap)

        live = _aggregate(self._active)
        live["active"] = True
        live["recording"] = True
        live["phase"] = "playing"
        return live


_tracker = GameSessionTracker()


def tick_game_performance(snap: dict, *, save_session) -> dict[str, Any]:
    return _tracker.tick(snap, save_session=save_session)


def seed_last_session(session: dict[str, Any] | None) -> None:
    """Restore last completed session after Pulse restart."""
    if session:
        _tracker._last_session = session
