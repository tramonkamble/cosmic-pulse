# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Frametime / hitch proxy from page faults, PSI, swap, and disk spikes."""

from __future__ import annotations

SESSION_WINDOW_SEC = 300
EVENT_SCORE = 38
_EMA_SCORE: float | None = None
_active_game_id: str | None = None

CAUSE_LABELS = {
    "major_faults": "Major page faults",
    "mem_stall": "Memory stall (PSI)",
    "io_stall": "I/O stall (PSI)",
    "swap": "Swap activity",
    "disk_spike": "Disk write spike",
}


def reset_stutter_state() -> None:
    """Clear EMA baseline (tests / game session boundaries)."""
    global _EMA_SCORE, _active_game_id
    _EMA_SCORE = None
    _active_game_id = None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def effective_disk_io_wait(
    *,
    psi_io: float = 0,
    psi_mem: float = 0,
    disk_busy_pct: float = 0,
    disk_read_mbps: float = 0,
    disk_write_mbps: float = 0,
    cpu_iowait_pct: float = 0,
) -> dict:
    """Disk-relevant I/O wait for UI and stutter scoring.

    Raw PSI I/O often reflects zram swap churn while the NVMe is idle; dampen that
    so the dashboard reflects storage pain, not background swap traffic.
    """
    disk_rw = disk_read_mbps + disk_write_mbps
    disk_active = disk_busy_pct >= 12 or disk_rw >= 25
    zram_dominated = psi_io >= 20 and psi_mem < 6 and not disk_active

    if zram_dominated:
        display = max(cpu_iowait_pct, disk_busy_pct * 0.35)
        source = "cpu_iowait"
    elif disk_active:
        blend = max(cpu_iowait_pct, disk_busy_pct * 0.9)
        psi_scaled = psi_io * min(1.0, max(disk_busy_pct, disk_rw) / 35.0)
        display = max(blend, psi_scaled)
        source = "disk"
    else:
        display = max(cpu_iowait_pct, psi_io * 0.2)
        source = "idle"

    return {
        "io_wait_pct": round(min(100.0, display), 1),
        "zram_dominated": zram_dominated,
        "source": source,
    }


def hitch_ms_proxy(
    score: float,
    pgmaj: float,
    psi_mem: float,
    psi_io: float,
    swap_out: float,
) -> float:
    """Rough single-hitch duration estimate in milliseconds."""
    base = score * 1.2 + min(80.0, pgmaj * 0.4) + psi_mem * 1.5 + psi_io * 0.8
    if swap_out > 100:
        base += 15.0
    return round(min(250.0, max(0.0, base)), 1)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * pct)))
    return ordered[idx]


def _sync_game_baseline(snap: dict) -> None:
    """Reset hitch EMA when the active game changes or the session ends."""
    global _EMA_SCORE, _active_game_id
    gt = snap.get("game_totals") or {}
    gid = gt.get("game_id") if gt.get("running") else None
    if gid != _active_game_id:
        _EMA_SCORE = None
        _active_game_id = gid


def _window_samples(history: list, now: float, window_sec: float) -> list:
    """Recent history points within window_sec (newest history is at the end)."""
    if not history:
        return []
    cutoff = now - window_sec
    out: list = []
    for point in reversed(history):
        ts = point.get("ts") or 0
        if ts < cutoff:
            break
        out.append(point)
    out.reverse()
    return out


def compute_stutter(snap: dict) -> dict:
    global _EMA_SCORE

    _sync_game_baseline(snap)

    dram = (snap.get("bandwidth") or {}).get("memory") or {}
    disk = snap.get("disk") or {}
    mem = snap.get("memory") or {}

    pgmaj = float(dram.get("pgmajfault_per_s") or 0)
    psi_mem = float(dram.get("psi_avg10") or 0)
    psi_io = float(dram.get("psi_io_avg10") or 0)
    io_wait = float(dram.get("io_wait_pct") if dram.get("io_wait_pct") is not None else psi_io)
    swap_out = float(dram.get("swap_out_kbps") or 0)
    swap_in = float(dram.get("swap_in_kbps") or 0)
    swap_pct = float(mem.get("swap_pct") or 0)
    disk_w = float(disk.get("write_mbps") or 0)

    components = {
        "major_faults": _clamp(pgmaj / 60.0 * 100),
        "mem_stall": _clamp(psi_mem / 15.0 * 100),
        "io_stall": _clamp(io_wait / 20.0 * 100),
        "swap": _clamp(max(swap_out, swap_in) / 150.0 * 100 + swap_pct * 0.5),
        "disk_spike": _clamp(disk_w / 80.0 * 100) if disk_w > 20 else 0.0,
    }

    score = round(
        _clamp(
            components["major_faults"] * 0.38
            + components["mem_stall"] * 0.32
            + components["io_stall"] * 0.12
            + components["swap"] * 0.13
            + components["disk_spike"] * 0.05
        ),
        1,
    )

    if _EMA_SCORE is None:
        _EMA_SCORE = score
    else:
        _EMA_SCORE = _EMA_SCORE * 0.85 + score * 0.15
    spike = score - _EMA_SCORE > 22.0

    causes = [k for k, v in components.items() if v >= 35.0]
    is_event = score >= EVENT_SCORE or spike or (pgmaj >= 100 and psi_mem >= 4.0)

    if score >= 70 or (is_event and score >= 55):
        severity = "severe"
    elif score >= 50 or is_event:
        severity = "moderate"
    elif score >= 30:
        severity = "mild"
    else:
        severity = "none"

    est_ms = hitch_ms_proxy(score, pgmaj, psi_mem, io_wait, swap_out)

    return {
        "score": score,
        "smoothness": round(100.0 - score, 1),
        "event": is_event,
        "severity": severity,
        "est_ms": est_ms,
        "causes": causes,
        "components": {k: round(v, 1) for k, v in components.items()},
    }


def session_stats(snap: dict, history: list) -> dict:
    now = float(snap.get("ts") or 0)
    window = _window_samples(history, now, SESSION_WINDOW_SEC)
    samples = window
    if not samples or (samples[-1].get("ts") or 0) < now:
        samples = window + [snap]

    scores: list[float] = []
    hitch_ms: list[float] = []
    events = 0
    for h in samples:
        st = h.get("stutter") or {}
        scores.append(float(st.get("score") or 0))
        hitch_ms.append(float(st.get("est_ms") or 0))
        if st.get("event"):
            events += 1

    avg = sum(scores) / len(scores) if scores else 0.0
    span_sec = SESSION_WINDOW_SEC
    if len(samples) >= 2:
        span_sec = max(
            1.0,
            float(samples[-1].get("ts") or now) - float(samples[0].get("ts") or now),
        )
    return {
        "window_sec": SESSION_WINDOW_SEC,
        "events": events,
        "hitch_rate_per_min": round(events / (span_sec / 60), 2),
        "score_avg": round(avg, 1),
        "score_p95": round(_percentile(scores, 0.95), 1),
        "hitch_ms_1pct": round(_percentile(hitch_ms, 0.99), 1),
        "smoothness_session": round(100.0 - avg, 1),
    }


def attach_stutter(snap: dict, history: list) -> None:
    snap["stutter"] = compute_stutter(snap)
    snap["stutter"]["session"] = session_stats(snap, history)
    snap["stutter"]["cause_labels"] = {k: CAUSE_LABELS.get(k, k) for k in snap["stutter"]["causes"]}
