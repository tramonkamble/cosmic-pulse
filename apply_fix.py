# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Safe auto-apply policy for one-click Fixes.

Pulse may ONLY write user-owned config (files under ~/.config/cosmic-pulse or
this project's .pulse_config.json). It must NEVER:

  - kill or signal processes (pkill, flatpak kill, etc.)
  - launch external apps (xdg-open, corectrl, browsers)
  - run shell commands, sudo, or subprocesses for remediation

Copy-paste commands and fix scripts are suggestions the user runs themselves.
Register handlers in _SAFE_APPLY only when an action is provably safe.
"""

from __future__ import annotations

from typing import Callable

# UI hint: insight scripts/steps that need sudo — shown as "Requires root", no Fix button.
FIX_REQUIRES_ROOT: dict[str, bool] = {
    "cpu-governor-powersave": True,
    "vm-swappiness-high": True,
    "ram-expo-verify": True,
    "gpu-thermal-ceiling": False,
    "gpu-thermal-warm": False,
    "gpu-vram-bandwidth": False,
    "gpu-vram-full": False,
    "gpu-gtt-churn": False,
    "memory-swap-thrash": True,
    "memory-dram-stall": False,
    "memory-page-faults": False,
    "stutter-proxy": False,
    "cpu-bound": True,
    "gpu-shader-bound": False,
    "cpu-ccd-spread": False,
    "system-balanced": False,
}

_SAFE_APPLY: dict[str, Callable[[], dict]] = {}


def requires_root(insight_id: str) -> bool:
    return FIX_REQUIRES_ROOT.get(insight_id, True)


def fix_available(insight_id: str) -> bool:
    return insight_id in _SAFE_APPLY


def apply_fix(insight_id: str) -> dict:
    handler = _SAFE_APPLY.get(insight_id)
    if not handler:
        return {
            "ok": False,
            "suggest_only": True,
            "message": "Pulse does not run this — copy a command below and run it yourself.",
        }
    try:
        return handler()
    except OSError as exc:
        return {"ok": False, "message": f"Config update failed: {exc}"}