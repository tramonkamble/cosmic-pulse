# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""SQLite time-series store for Pulse trending and correlation."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time

from paths import data_dir
from pulse_config import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_THEME_MODE,
    DEFAULT_TUNING_LOG_MAX,
    DEFAULT_UI_SCALE,
    RETENTION_MAX_DAYS,
    RETENTION_MIN_DAYS,
    RETENTION_PRESETS,
    THEME_MODES,
    TUNING_LOG_MAX_CAP,
    TUNING_LOG_MIN,
    TUNING_LOG_PRESETS,
    UI_SCALE_MAX,
    UI_SCALE_MIN,
    UI_SCALE_STEP,
    estimate_max_mb,
    get_resolved_insights,
    get_retention_days,
    get_suppressed_insights,
    get_theme_mode,
    get_tuning_log_max,
    get_ui_scale,
    load_config,
    resolve_insight,
    save_config,
    save_retention_days,
    suppress_insight,
    unresolve_insight,
    unsuppress_insight,
)

DB_PATH = data_dir() / "pulse.db"

# Flat metrics available for /api/trends and /api/correlation
METRICS: dict[str, str] = {
    "cpu_pct": "CPU usage %",
    "load1": "Load average (1m)",
    "ram_pct": "RAM used %",
    "swap_pct": "Swap used %",
    "swap_in_kbps": "Swap in KB/s",
    "swap_out_kbps": "Swap out KB/s",
    "gpu_junction_c": "GPU junction °C",
    "gpu_ppt_w": "GPU power W",
    "gpu_busy_pct": "GPU engine busy %",
    "vram_busy_pct": "VRAM controller busy %",
    "vram_gbps": "VRAM est. GB/s",
    "gtt_rate_mbps": "GTT rate MB/s",
    "pgfault_per_s": "Page faults /s",
    "pgmajfault_per_s": "Major faults /s",
    "psi_mem": "PSI memory (10s avg)",
    "psi_io": "PSI I/O (10s avg)",
    "dram_util_pct": "DRAM util est. %",
    "game_cpu_pct": "Game process %",
    "game_rss_mb": "Game RSS MB",
    "session_index": "Session load index",
    "active_issues": "Active issue count",
    "stutter_score": "Stutter proxy score",
    "stutter_smoothness": "Smoothness %",
    "stutter_est_ms": "Hitch estimate ms",
}

_SAMPLE_EXTRA_COLS = (
    ("stutter_score", "REAL"),
    ("stutter_smoothness", "REAL"),
    ("stutter_est_ms", "REAL"),
    ("stutter_event", "INTEGER"),
)
_SESSION_EXTRA_COLS = (
    ("trend_json", "TEXT"),
    ("fps_avg", "REAL"),
    ("fps_1pct", "REAL"),
    ("fps_0_1pct", "REAL"),
    ("frametime_avg", "REAL"),
    ("frametime_1pct", "REAL"),
    ("mangohud_path", "TEXT"),
)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def _ensure_columns(c: sqlite3.Connection, table: str, cols: tuple[tuple[str, str], ...]) -> None:
    existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, typ in cols:
        if col not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def init_db() -> None:
    with _lock:
        c = _get_conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                game_id TEXT,
                cpu_pct REAL,
                load1 REAL,
                ram_pct REAL,
                swap_pct REAL,
                swap_in_kbps REAL,
                swap_out_kbps REAL,
                gpu_junction_c REAL,
                gpu_ppt_w REAL,
                gpu_busy_pct REAL,
                vram_busy_pct REAL,
                vram_gbps REAL,
                gtt_rate_mbps REAL,
                pgfault_per_s REAL,
                pgmajfault_per_s REAL,
                psi_mem REAL,
                psi_io REAL,
                dram_util_pct REAL,
                game_cpu_pct REAL,
                game_rss_mb REAL,
                session_index REAL,
                active_issues INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
            CREATE INDEX IF NOT EXISTS idx_samples_game_ts ON samples(game_id, ts);

            CREATE TABLE IF NOT EXISTS game_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                game_name TEXT,
                started_ts REAL NOT NULL,
                ended_ts REAL NOT NULL,
                duration_sec REAL,
                rating REAL,
                rating_tier TEXT,
                smoothness_avg REAL,
                stutter_score_avg REAL,
                hitch_ms_1pct REAL,
                hitch_events INTEGER,
                game_cpu_avg REAL,
                gpu_busy_avg REAL,
                ram_pct_avg REAL,
                sample_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_game_sessions_game ON game_sessions(game_id, started_ts);

            CREATE TABLE IF NOT EXISTS session_markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                game_id TEXT,
                kind TEXT NOT NULL,
                label TEXT,
                insight_id TEXT,
                meta TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_session_markers_game ON session_markers(game_id, ts);
            """
        )
        _ensure_columns(c, "samples", _SAMPLE_EXTRA_COLS)
        _ensure_columns(c, "game_sessions", _SESSION_EXTRA_COLS)
        _migrate_legacy_game_ids(c)
        c.commit()


def _migrate_legacy_game_ids(c: sqlite3.Connection) -> None:
    """Normalize pre-dynamic-detection game_id values in samples."""
    c.execute("UPDATE samples SET game_id = '949230' WHERE game_id = 'cities2'")


def prune_old() -> int:
    cutoff = time.time() - get_retention_days() * 86400
    with _lock:
        c = _get_conn()
        cur = c.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM game_sessions WHERE ended_ts < ?", (cutoff,))
        c.execute("DELETE FROM session_markers WHERE ts < ?", (cutoff,))
        c.commit()
        return cur.rowcount


def clear_history() -> dict:
    """Wipe SQLite samples, game sessions, and session markers (schema kept)."""
    with _lock:
        c = _get_conn()
        samples = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        sessions = c.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
        markers = c.execute("SELECT COUNT(*) FROM session_markers").fetchone()[0]
        c.execute("DELETE FROM samples")
        c.execute("DELETE FROM game_sessions")
        c.execute("DELETE FROM session_markers")
        c.commit()
        try:
            c.execute("VACUUM")
        except sqlite3.Error:
            pass
    return {
        "cleared_samples": samples,
        "cleared_sessions": sessions,
        "cleared_markers": markers,
    }


def flatten_sample(snap: dict) -> dict:
    cpu = snap.get("cpu") or {}
    mem = snap.get("memory") or {}
    dgpu = (snap.get("gpu") or {}).get("discrete") or {}
    bw_gpu = (snap.get("bandwidth") or {}).get("gpu") or {}
    bw_mem = (snap.get("bandwidth") or {}).get("memory") or {}
    gt = snap.get("game_totals") or {}
    cmp = snap.get("comparison") or {}
    active = [h for h in (snap.get("tuning") or []) if h.get("active") is not False]
    if not active and snap.get("tuning_active"):
        active = snap["tuning_active"]
    load = cpu.get("load") or [None, None, None]
    st = snap.get("stutter") or {}
    return {
        "ts": snap["ts"],
        "game_id": gt.get("game_id"),
        "cpu_pct": cpu.get("overall_pct"),
        "load1": load[0] if load else None,
        "ram_pct": mem.get("pct"),
        "swap_pct": mem.get("swap_pct"),
        "swap_in_kbps": bw_mem.get("swap_in_kbps"),
        "swap_out_kbps": bw_mem.get("swap_out_kbps"),
        "gpu_junction_c": dgpu.get("junction_c"),
        "gpu_ppt_w": dgpu.get("ppt_w"),
        "gpu_busy_pct": bw_gpu.get("engine_busy_pct"),
        "vram_busy_pct": bw_gpu.get("vram_busy_pct"),
        "vram_gbps": bw_gpu.get("vram_est_gbps"),
        "gtt_rate_mbps": bw_gpu.get("gtt_rate_mbps"),
        "pgfault_per_s": bw_mem.get("pgfault_per_s"),
        "pgmajfault_per_s": bw_mem.get("pgmajfault_per_s"),
        "psi_mem": bw_mem.get("psi_avg10"),
        "psi_io": bw_mem.get("psi_io_avg10"),
        "dram_util_pct": bw_mem.get("dram_util_pct"),
        "game_cpu_pct": gt.get("cpu_pct") if gt.get("running") else None,
        "game_rss_mb": gt.get("rss_mb") if gt.get("running") else None,
        "session_index": cmp.get("session_index"),
        "active_issues": len(active),
        "stutter_score": st.get("score"),
        "stutter_smoothness": st.get("smoothness"),
        "stutter_est_ms": st.get("est_ms"),
        "stutter_event": 1 if st.get("event") else 0,
    }


def record_sample(snap: dict) -> None:
    row = flatten_sample(snap)
    cols = [k for k in row if k != "ts"]
    placeholders = ", ".join("?" * (len(cols) + 1))
    names = "ts, " + ", ".join(cols)
    values = [row["ts"]] + [row[c] for c in cols]
    with _lock:
        _get_conn().execute(
            f"INSERT INTO samples ({names}) VALUES ({placeholders})",
            values,
        )
        _get_conn().commit()


_last_prune = 0.0


def record_sample_maybe_prune(snap: dict) -> None:
    global _last_prune
    record_sample(snap)
    now = time.time()
    if now - _last_prune > 3600:
        prune_old()
        _last_prune = now


def _since_ts(hours: float) -> float:
    return time.time() - max(0.1, hours) * 3600


def series(
    metric: str,
    hours: float = 24,
    bucket_sec: int = 60,
    game_id: str | None = None,
) -> list[dict]:
    if metric not in METRICS:
        return []
    since = _since_ts(hours)
    bucket_sec = max(1, int(bucket_sec))
    game_clause = "AND game_id = ?" if game_id else ""
    params: list = [since]
    if game_id:
        params.append(game_id)
    params.append(bucket_sec)
    sql = f"""
        SELECT (CAST(ts AS INTEGER) / ?) * ? AS bucket,
               AVG({metric}) AS v,
               COUNT(*) AS n
        FROM samples
        WHERE ts >= ? AND {metric} IS NOT NULL {game_clause}
        GROUP BY bucket
        ORDER BY bucket
    """
    params = [bucket_sec, bucket_sec, since] + ([game_id] if game_id else [])
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    return [{"ts": r["bucket"], "value": round(r["v"], 3), "n": r["n"]} for r in rows]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 8:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


def correlate(
    metric_a: str,
    metric_b: str,
    hours: float = 4,
    game_id: str | None = None,
) -> dict:
    if metric_a not in METRICS or metric_b not in METRICS:
        return {"error": "unknown metric", "pairs": 0}
    since = _since_ts(hours)
    game_clause = "AND game_id = ?" if game_id else ""
    params: list = [since]
    if game_id:
        params.append(game_id)
    sql = f"""
        SELECT {metric_a} AS a, {metric_b} AS b
        FROM samples
        WHERE ts >= ?
          AND {metric_a} IS NOT NULL
          AND {metric_b} IS NOT NULL
          {game_clause}
        ORDER BY ts
    """
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    xs = [r["a"] for r in rows]
    ys = [r["b"] for r in rows]
    r = _pearson(xs, ys)
    return {
        "a": metric_a,
        "b": metric_b,
        "hours": hours,
        "pairs": len(xs),
        "r": r,
        "strength": _strength(r),
    }


def _strength(r: float | None) -> str | None:
    if r is None:
        return None
    ar = abs(r)
    if ar >= 0.7:
        return "strong"
    if ar >= 0.4:
        return "moderate"
    if ar >= 0.2:
        return "weak"
    return "negligible"


def _decode_session(row: sqlite3.Row) -> dict:
    data = dict(row)
    raw = data.pop("trend_json", None)
    if raw:
        try:
            data["trend"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data["trend"] = []
    else:
        data["trend"] = []
    # MangoHud presence: stored path/fps columns (not a separate flag in SQLite)
    has_mh = data.get("fps_avg") is not None or bool(data.get("mangohud_path"))
    data["mangohud"] = has_mh
    data["hitch_source"] = "mangohud" if has_mh else "proxy"
    return data


def save_game_session(row: dict) -> int:
    trend = row.get("trend") or []
    trend_json = json.dumps(trend, separators=(",", ":")) if trend else None
    with _lock:
        cur = _get_conn().execute(
            """
            INSERT INTO game_sessions (
                game_id, game_name, started_ts, ended_ts, duration_sec,
                rating, rating_tier, smoothness_avg, stutter_score_avg,
                hitch_ms_1pct, hitch_events, game_cpu_avg, gpu_busy_avg,
                ram_pct_avg, sample_count, trend_json,
                fps_avg, fps_1pct, fps_0_1pct, frametime_avg, frametime_1pct,
                mangohud_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["game_id"],
                row.get("game_name"),
                row["started_ts"],
                row["ended_ts"],
                row.get("duration_sec"),
                row.get("rating"),
                row.get("rating_tier"),
                row.get("smoothness_avg"),
                row.get("stutter_score_avg"),
                row.get("hitch_ms_1pct"),
                row.get("hitch_events"),
                row.get("game_cpu_avg"),
                row.get("gpu_busy_avg"),
                row.get("ram_pct_avg"),
                row.get("sample_count"),
                trend_json,
                row.get("fps_avg"),
                row.get("fps_1pct"),
                row.get("fps_0_1pct"),
                row.get("frametime_avg"),
                row.get("frametime_1pct"),
                row.get("mangohud_path"),
            ),
        )
        _get_conn().commit()
        return int(cur.lastrowid or 0)


def list_game_sessions(game_id: str | None = None, days: float = 30) -> list[dict]:
    since = time.time() - max(0.1, days) * 86400
    clause = "AND game_id = ?" if game_id else ""
    params: list = [since]
    if game_id:
        params.append(game_id)
    with _lock:
        rows = (
            _get_conn()
            .execute(
                f"""
            SELECT * FROM game_sessions
            WHERE ended_ts >= ? {clause}
            ORDER BY ended_ts DESC
            LIMIT 200
            """,
                params,
            )
            .fetchall()
        )
    return [_decode_session(r) for r in rows]


def latest_game_session(game_id: str | None = None) -> dict | None:
    clause = "AND game_id = ?" if game_id else ""
    params: list = []
    if game_id:
        params.append(game_id)
    with _lock:
        row = (
            _get_conn()
            .execute(
                f"""
            SELECT * FROM game_sessions
            WHERE 1=1 {clause}
            ORDER BY ended_ts DESC
            LIMIT 1
            """,
                params,
            )
            .fetchone()
        )
    return _decode_session(row) if row else None


def list_session_markers(game_id: str | None = None, days: float = 30) -> list[dict]:
    since = time.time() - max(0.1, days) * 86400
    clause = "AND game_id = ?" if game_id else ""
    params: list = [since]
    if game_id:
        params.append(game_id)
    with _lock:
        rows = (
            _get_conn()
            .execute(
                f"""
            SELECT id, ts, game_id, kind, label, insight_id, meta
            FROM session_markers
            WHERE ts >= ? {clause}
            ORDER BY ts DESC
            LIMIT 100
            """,
                params,
            )
            .fetchall()
        )
    return [dict(r) for r in rows]


def record_session_marker(
    game_id: str,
    kind: str,
    *,
    label: str = "",
    insight_id: str = "",
    meta: str = "",
) -> None:
    with _lock:
        _get_conn().execute(
            """
            INSERT INTO session_markers (ts, game_id, kind, label, insight_id, meta)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (time.time(), game_id, kind, label, insight_id, meta),
        )
        _get_conn().commit()


def stats() -> dict:
    with _lock:
        c = _get_conn()
        count = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        span = c.execute("SELECT MIN(ts), MAX(ts) FROM samples").fetchone()
        games = c.execute(
            "SELECT game_id, COUNT(*) AS n FROM samples WHERE game_id IS NOT NULL GROUP BY game_id"
        ).fetchall()
        session_count = c.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0]
    size_mb = round(DB_PATH.stat().st_size / 1024**2, 2) if DB_PATH.exists() else 0
    days = get_retention_days()
    scale = get_ui_scale()
    log_max = get_tuning_log_max()
    theme_mode = get_theme_mode()
    suppressed = get_suppressed_insights()
    resolved = get_resolved_insights()
    return {
        "path": str(DB_PATH),
        "samples": count,
        "oldest_ts": span[0],
        "newest_ts": span[1],
        "retention_days": days,
        "retention_default": DEFAULT_RETENTION_DAYS,
        "retention_presets": RETENTION_PRESETS,
        "retention_min": RETENTION_MIN_DAYS,
        "retention_max": RETENTION_MAX_DAYS,
        "ui_scale": scale,
        "ui_scale_default": DEFAULT_UI_SCALE,
        "ui_scale_min": UI_SCALE_MIN,
        "ui_scale_max": UI_SCALE_MAX,
        "ui_scale_step": UI_SCALE_STEP,
        "theme_mode": theme_mode,
        "theme_mode_default": DEFAULT_THEME_MODE,
        "theme_modes": list(THEME_MODES),
        "tuning_log_max": log_max,
        "tuning_log_default": DEFAULT_TUNING_LOG_MAX,
        "tuning_log_presets": TUNING_LOG_PRESETS,
        "tuning_log_min": TUNING_LOG_MIN,
        "tuning_log_max_cap": TUNING_LOG_MAX_CAP,
        "size_mb": size_mb,
        "est_max_mb": estimate_max_mb(days),
        "games": {r["game_id"]: r["n"] for r in games},
        "game_sessions": session_count,
        "suppressed_insights": suppressed,
        "resolved_insights": resolved,
        "suppressed_count": len(suppressed),
        "resolved_count": len(resolved),
        "metrics": METRICS,
        "pulse_config": load_config(),
    }


def set_retention(days: int) -> dict:
    saved = save_retention_days(days)
    pruned = prune_old()
    out = stats()
    out["ok"] = True
    out["pruned"] = pruned
    out["retention_days"] = saved
    return out


RESET_CONFIRM_TOKEN = "RESET"


def update_settings(body: dict) -> dict:
    updates: dict = {}
    acted = False
    details: dict = {}
    if "retention_days" in body:
        updates["retention_days"] = body["retention_days"]
    if "ui_scale" in body:
        updates["ui_scale"] = body["ui_scale"]
    if "tuning_log_max" in body:
        updates["tuning_log_max"] = body["tuning_log_max"]
    if "theme_mode" in body:
        updates["theme_mode"] = body["theme_mode"]
    if "suppressed_insights" in body:
        updates["suppressed_insights"] = body["suppressed_insights"]
    if "suppress_insight" in body and isinstance(body["suppress_insight"], str):
        suppress_insight(body["suppress_insight"].strip())
        acted = True
    if "unsuppress_insight" in body and isinstance(body["unsuppress_insight"], str):
        unsuppress_insight(body["unsuppress_insight"].strip())
        acted = True
    if "resolve_insight" in body and isinstance(body["resolve_insight"], str):
        resolve_insight(body["resolve_insight"].strip())
        acted = True
    if "unresolve_insight" in body and isinstance(body["unresolve_insight"], str):
        unresolve_insight(body["unresolve_insight"].strip())
        acted = True

    action = body.get("action")
    if isinstance(action, str) and action:
        # Server handles memory-side actions; store only runs DB/config pieces.
        confirm = body.get("confirm")
        needs_confirm = action in (
            "clear_samples",
            "clear_tuning_log",
            "reset_guidance_prefs",
            "reset_all_pulse_data",
        )
        if needs_confirm and confirm != RESET_CONFIRM_TOKEN:
            out = stats()
            out["ok"] = False
            out["error"] = f"Type {RESET_CONFIRM_TOKEN} to confirm this action"
            return out
        if action == "clear_samples":
            details["clear_history"] = clear_history()
            acted = True
        elif action == "reset_guidance_prefs":
            save_config(suppressed_insights=[], resolved_insights=[])
            details["reset_guidance_prefs"] = True
            acted = True
        elif action == "reset_all_pulse_data":
            details["clear_history"] = clear_history()
            save_config(suppressed_insights=[], resolved_insights=[])
            details["reset_guidance_prefs"] = True
            acted = True
        elif action in ("clear_tuning_log", "trim_tuning_log", "clear_diag_cache"):
            # No DB work here — server applies and still returns stats.
            acted = True
        else:
            out = stats()
            out["ok"] = False
            out["error"] = f"unknown action: {action}"
            return out

    if not updates and not acted:
        out = stats()
        out["ok"] = False
        out["error"] = "no settings provided"
        return out
    if updates:
        save_config(**updates)
    pruned = 0
    if "retention_days" in updates:
        pruned = prune_old()
    out = stats()
    out["ok"] = True
    out["pruned"] = pruned
    out["suppressed_insights"] = get_suppressed_insights()
    out["resolved_insights"] = get_resolved_insights()
    if details:
        out["details"] = details
    return out
