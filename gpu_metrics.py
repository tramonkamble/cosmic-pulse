# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Decode AMD gpu_metrics sysfs blobs for per-engine activity."""

from __future__ import annotations

import struct
from pathlib import Path

# Field offsets from start of gpu_metrics file (incl. 4-byte header).
_V1_GFX_OFF = {
    0: 24,  # u64 system_clock_counter before temps
    1: 16,
    2: 16,
    3: 16,
}
_V2_GFX_OFF = 12  # four u16 temps, then gfx + mm


def _engine_pct(val: int | None) -> int | None:
    """AMD uses 0xFFFF when an engine counter is unavailable (common on iGPU)."""
    if val is None or val > 100:
        return None
    return int(val)


def read_gpu_engines(base: Path) -> dict[str, int | None] | None:
    """Return GFX / VRAM (UMC) / MM activity % from gpu_metrics, if available."""
    path = base / "gpu_metrics"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 22:
        return None

    size, fmt_rev, content_rev = struct.unpack_from("<HBB", data, 0)
    if size != len(data):
        return None

    if fmt_rev == 1:
        off = _V1_GFX_OFF.get(content_rev)
        if off is None or len(data) < off + 6:
            return None
        gfx, umc, mm = struct.unpack_from("<HHH", data, off)
        return {"gfx": _engine_pct(gfx), "vram": _engine_pct(umc), "mm": _engine_pct(mm)}

    if fmt_rev == 2:
        if len(data) < _V2_GFX_OFF + 4:
            return None
        gfx, mm = struct.unpack_from("<HH", data, _V2_GFX_OFF)
        return {"gfx": _engine_pct(gfx), "vram": None, "mm": _engine_pct(mm)}

    return None