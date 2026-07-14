# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Game load-phase detection — suppress transient page-fault warnings during asset load."""

from __future__ import annotations

import time
from typing import Any

# Align with game_performance session grace.
LOAD_GRACE_SEC = 45

GPU_LOAD_MAX = 45.0
GPU_PLAY_MIN = 65.0
GPU_SETTLE_MIN = 30.0
DISK_READ_LOAD_MBPS = 25.0
PGMAJ_LOAD_MIN = 15
PGMAJ_FAULT_WARN = 20
PGMAJ_SETTLE_MIN = 10
SUSTAINED_FAULT_TICKS = 30
SWAP_LOAD_MAX = 10.0

_state: dict[str, dict[str, Any]] = {}
_active_gid: str | None = None


def _idle() -> dict[str, Any]:
    return {
        "phase": "idle",
        "game_id": None,
        "elapsed_sec": 0.0,
        "grace_sec": LOAD_GRACE_SEC,
        "in_grace": False,
        "pgmajfault_per_s": 0,
        "gpu_busy_pct": 0.0,
        "disk_read_mbps": 0.0,
        "swap_pct": 0.0,
        "sustained_fault_playing": False,
        "suppress_page_fault_warn": False,
    }


def tick_load_phase(snap: dict) -> dict[str, Any]:
    """Classify load vs play from disk I/O, GPU busy, and page faults."""
    global _active_gid

    gt = snap.get("game_totals") or {}
    game_id = gt.get("game_id") if gt.get("running") else None
    ts = float(snap.get("ts") or time.time())

    if not game_id:
        if _active_gid:
            _state.pop(_active_gid, None)
        _active_gid = None
        return _idle()

    if _active_gid != game_id:
        if _active_gid:
            _state.pop(_active_gid, None)
        _active_gid = game_id

    st = _state.setdefault(game_id, {"detected_ts": ts, "high_fault_ticks": 0})
    if st.get("detected_ts") is None:
        st["detected_ts"] = ts

    elapsed = ts - float(st["detected_ts"])
    dgpu = (snap.get("gpu") or {}).get("discrete") or {}
    gpu_busy = float(dgpu.get("busy_pct") or 0)
    disk = snap.get("disk") or {}
    disk_read = float(disk.get("read_mbps") or 0)
    dram = (snap.get("bandwidth") or {}).get("memory") or {}
    pgmaj = int(dram.get("pgmajfault_per_s") or 0)
    mem = snap.get("memory") or {}
    swap_pct = float(mem.get("swap_pct") or 0)

    in_grace = elapsed < LOAD_GRACE_SEC
    io_pressure = pgmaj >= PGMAJ_LOAD_MIN or disk_read >= DISK_READ_LOAD_MBPS
    loading = gpu_busy < GPU_LOAD_MAX and io_pressure and swap_pct < SWAP_LOAD_MAX
    playing = gpu_busy >= GPU_PLAY_MIN or (
        elapsed >= LOAD_GRACE_SEC and gpu_busy >= GPU_SETTLE_MIN
    )

    if loading and (in_grace or io_pressure):
        phase = "loading"
        st["high_fault_ticks"] = 0
    elif playing:
        phase = "playing"
        if pgmaj > PGMAJ_FAULT_WARN:
            st["high_fault_ticks"] = int(st.get("high_fault_ticks", 0)) + 1
        else:
            st["high_fault_ticks"] = 0
    elif pgmaj >= PGMAJ_SETTLE_MIN:
        phase = "settling"
        st["high_fault_ticks"] = 0
    else:
        phase = "loading" if in_grace else "settling"
        st["high_fault_ticks"] = 0

    sustained = phase == "playing" and int(st.get("high_fault_ticks", 0)) >= SUSTAINED_FAULT_TICKS
    suppress_warn = phase == "loading" or in_grace or not sustained

    return {
        "phase": phase,
        "game_id": game_id,
        "elapsed_sec": round(elapsed, 1),
        "grace_sec": LOAD_GRACE_SEC,
        "in_grace": in_grace,
        "pgmajfault_per_s": pgmaj,
        "gpu_busy_pct": round(gpu_busy, 1),
        "disk_read_mbps": round(disk_read, 1),
        "swap_pct": round(swap_pct, 1),
        "sustained_fault_playing": sustained,
        "suppress_page_fault_warn": suppress_warn,
    }


def page_fault_warn(snap: dict, pgmaj: int) -> bool:
    """True when memory-page-faults warn should fire."""
    if pgmaj <= PGMAJ_FAULT_WARN:
        return False
    gt = snap.get("game_totals") or {}
    if not gt.get("running"):
        return True
    lp = snap.get("load_phase") or {}
    return not lp.get("suppress_page_fault_warn", True)


def page_fault_settle(snap: dict, pgmaj: int) -> bool:
    """True when resolution-load-settle info should fire instead of warn."""
    if pgmaj < PGMAJ_SETTLE_MIN:
        return False
    gt = snap.get("game_totals") or {}
    if not gt.get("running"):
        return False
    if page_fault_warn(snap, pgmaj):
        return False
    lp = snap.get("load_phase") or {}
    if pgmaj < PGMAJ_FAULT_WARN:
        return True
    return (
        lp.get("phase") in ("loading", "settling")
        or lp.get("in_grace")
        or not lp.get("sustained_fault_playing")
    )