# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""One-click remediation for insights that do not need root."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fix_scripts import CS2_DIR

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


def fix_available(insight_id: str) -> bool:
    return insight_id in _APPLY_HANDLERS and not requires_root(insight_id)


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
    steps: list[str] = []
    if _launch_corectrl():
        steps.append("CoreCtrl opened — adjust fan curve")
    if _xdg_open(CS2_DIR):
        steps.append("game settings folder opened")
    if not steps:
        return {
            "ok": False,
            "message": "Could not open tools — lower graphics in-game manually.",
        }
    return {
        "ok": True,
        "message": " · ".join(steps) + ". Cap FPS and LOD in-game.",
    }


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


_APPLY_HANDLERS: dict[str, callable] = {
    "gpu-thermal-ceiling": _apply_gpu_cool,
    "gpu-thermal-warm": _apply_gpu_cool,
    "gpu-vram-bandwidth": _apply_vram_bandwidth,
    "gpu-vram-full": _apply_open_cs2,
    "gpu-gtt-churn": _apply_vram_bandwidth,
    "memory-page-faults": _apply_page_faults,
    "gpu-shader-bound": _apply_open_cs2,
}


def apply_fix(insight_id: str) -> dict:
    if requires_root(insight_id):
        return {
            "ok": False,
            "requires_root": True,
            "message": "This fix needs administrator access (sudo). Use the script below.",
        }
    handler = _APPLY_HANDLERS.get(insight_id)
    if not handler:
        return {
            "ok": False,
            "message": "No one-click fix — follow the manual steps below.",
        }
    try:
        return handler()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"Fix failed: {exc}"}