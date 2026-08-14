# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only fix policy — Cosmic Pulse never executes commands.

v0.1 security pivot: one-click Fix / xdg-open / subprocess launch paths are
disabled. Guidance only *suggests* shell text (from fix_scripts / rule packs).
Users copy commands and run them in their own terminal at their own risk.

This module still exports:
  - requires_root() — UI badge for sudo-heavy suggestions
  - fix_available() — always False (no GUI apply)
  - apply_fix() — safe no-op that returns suggest_only + message
"""

from __future__ import annotations

# UI hint: insight scripts/steps that typically need sudo — shown as "Requires root".
FIX_REQUIRES_ROOT: dict[str, bool] = {
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
    "mangohud-recommended": True,  # apt install
    "gamemode-recommended": True,
    # Audio pipeline — inspect / session-only quantum; no root
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

# Human-readable policy line for API + UI
READ_ONLY_MESSAGE = (
    "Pulse never runs fixes. Copy the suggested command or script and run it "
    "yourself in a terminal — review first; execute at your own risk."
)


def requires_root(insight_id: str) -> bool:
    return FIX_REQUIRES_ROOT.get(insight_id, True)


def fix_available(insight_id: str) -> bool:
    """One-click Fix is permanently disabled (read-only product policy)."""
    return False


def apply_fix(
    insight_id: str,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
) -> dict:
    """No-op apply path — never opens apps, never writes config, never spawns shells.

    Kept so /api/apply-fix and older clients fail closed with a clear message.
    """
    _ = (insight_id, game_id, game_name)
    root = requires_root(insight_id) if insight_id else False
    return {
        "ok": False,
        "suggest_only": True,
        "read_only": True,
        "fixable": False,
        "requires_root": root,
        "message": READ_ONLY_MESSAGE,
    }
