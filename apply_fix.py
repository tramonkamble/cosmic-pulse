# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Safe auto-apply policy for one-click Fixes.

Pulse may apply fixes that:
  - open user-owned folders (game settings, saves, mods) via xdg-open
  - launch optional GUI helpers the user already installed (e.g. CoreCtrl)

Pulse must NEVER:
  - kill or signal processes (pkill, flatpak kill, etc.)
  - run sudo, sysctl, or write under /etc or /sys
  - alter major system files or kernel tunables

Copy-paste commands and fix scripts remain for root or manual steps.
Register handlers in _SAFE_APPLY only when an action meets the rules above.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from fix_scripts import CS2_DIR
from gpu_thermal import infer_gpu_model, profile_for_model

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


def requires_root(insight_id: str) -> bool:
    return FIX_REQUIRES_ROOT.get(insight_id, True)


def _xdg_open(path: Path) -> bool:
    if not path.exists():
        return False
    subprocess.Popen(
        ["xdg-open", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _launch_corectrl() -> bool:
    exe = shutil.which("corectrl")
    if not exe:
        return False
    subprocess.Popen(
        [exe],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _apply_gpu_cool() -> dict:
    prof = profile_for_model(infer_gpu_model())
    steps: list[str] = []
    if prof.get("fan_curve_helpful") and _launch_corectrl():
        steps.append("CoreCtrl opened — adjust fan curve")
    if _xdg_open(CS2_DIR):
        steps.append("game settings folder opened")
    if not steps:
        return {
            "ok": False,
            "message": "Could not open tools — lower graphics in-game manually.",
        }
    tail = (
        "Cap FPS and LOD in-game."
        if prof.get("arch") == "rdna3"
        else "Cap FPS and LOD in-game; fan curves help most on RDNA2 and NVIDIA."
    )
    return {"ok": True, "message": " · ".join(steps) + ". " + tail}


def _apply_open_cs2() -> dict:
    if _xdg_open(CS2_DIR):
        return {"ok": True, "message": "Opened Cities II settings folder — adjust graphics in-game."}
    return {"ok": False, "message": "Game settings folder not found on this machine."}


def _apply_vram_bandwidth() -> dict:
    steps: list[str] = []
    mods = CS2_DIR / ".cache" / "Mods"
    if _xdg_open(mods):
        steps.append("mod cache opened")
    if _xdg_open(CS2_DIR):
        steps.append("settings folder opened")
    if not steps:
        return {"ok": False, "message": "Could not open game folders."}
    return {
        "ok": True,
        "message": " · ".join(steps) + ". Lower texture and asset quality in-game.",
    }


def _apply_page_faults() -> dict:
    saves = CS2_DIR / "Saves"
    if _xdg_open(saves):
        return {
            "ok": True,
            "message": "Opened save folder — let loading finish before unpausing large cities.",
        }
    return {"ok": False, "message": "Save folder not found."}


_SAFE_APPLY: dict[str, Callable[[], dict]] = {
    "gpu-thermal-ceiling": _apply_gpu_cool,
    "gpu-thermal-warm": _apply_gpu_cool,
    "gpu-vram-bandwidth": _apply_vram_bandwidth,
    "gpu-vram-full": _apply_open_cs2,
    "gpu-gtt-churn": _apply_vram_bandwidth,
    "memory-page-faults": _apply_page_faults,
    "gpu-shader-bound": _apply_open_cs2,
    "system-balanced": _apply_open_cs2,
}


def fix_available(insight_id: str) -> bool:
    return insight_id in _SAFE_APPLY and not requires_root(insight_id)


def apply_fix(insight_id: str) -> dict:
    if requires_root(insight_id):
        return {
            "ok": False,
            "requires_root": True,
            "message": "This fix needs administrator access (sudo). Use the script below.",
        }
    handler = _SAFE_APPLY.get(insight_id)
    if not handler:
        return {
            "ok": False,
            "suggest_only": True,
            "message": "No one-click fix — copy a command below and run it yourself.",
        }
    try:
        return handler()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"Fix failed: {exc}"}