# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Insight metadata for Guidance (no execution, no fix scripts).

Cosmic Pulse is read-only: it never runs commands. This module only
labels which suggestions typically need sudo so the UI can say so.
"""

from __future__ import annotations

# UI hint: steps that typically need sudo — shown as "Requires root".
REQUIRES_ROOT: dict[str, bool] = {
    "cpu-governor-powersave": True,
    "vm-swappiness-high": True,
    "ram-expo-verify": True,
    "gpu-thermal-ceiling": False,
    "gpu-thermal-warm": False,
    "gpu-thermal-by-design": False,
    "gpu-vram-bandwidth": False,
    "gpu-vram-full": False,
    "gpu-gtt-churn": False,
    "memory-swap-thrash": True,
    "memory-dram-stall": False,
    "memory-page-faults": False,
    "stutter-proxy": False,
    "cpu-bound": True,
    "gpu-shader-bound": False,
    "gpu-fps-cap": False,
    "resolution-swap-stutter": False,
    "resolution-load-settle": False,
    "resolution-cpu-perf": True,
    "cpu-ccd-spread": False,
    "game-files-corrupt": False,
    "game-update-pending": False,
    "game-libs-missing": True,
    "steam-disk-low": False,
    "vulkan-broken": True,
    "game-prefix-reset": False,
    "proton-wayland-launch-fix": False,
    "display-hdr-off": False,
    "enable-nvme-smart": True,
    "system-balanced": False,
    "mangohud-recommended": True,
    "gamemode-recommended": True,
    "cpu-rapl-unreadable": True,
    "enable-cpu-rapl": True,
    "audio-pipeline": False,
    "audio-default-sink-missing": False,
    "audio-hdmi-default-alt": False,
    "audio-bluetooth-default": False,
    "audio-odd-sample-rate": False,
    "audio-large-quantum": False,
    "audio-xruns-recent": False,
    "audio-stock-min-quantum": False,
    "audio-conf-not-applied": False,
    "audio-conf-multi-context": False,
    "audio-hdmi-priority-conf": False,
}


def requires_root(insight_id: str) -> bool:
    return REQUIRES_ROOT.get(insight_id, True)
