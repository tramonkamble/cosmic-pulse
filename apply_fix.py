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

import subprocess
from collections.abc import Callable
from pathlib import Path

from fix_scripts import launch_fan_tool
from games import game_data_paths
from gpu_thermal import infer_gpu_model, profile_for_model
from hardware_profiles import FIX_TOOL_SPECS

# UI hint: insight scripts/steps that need sudo — shown as "Requires root", no Fix button.
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


def _game_base(ctx: dict) -> Path | None:
    for key in ("userdata", "open_dir", "install", "compat"):
        path = ctx.get(key)
        if path and Path(path).exists():
            return Path(path)
    return None


def _open_game_path(ctx: dict, *candidates: str) -> bool:
    """Open the first existing subfolder under the game base, else the base itself."""
    base = _game_base(ctx)
    if not base:
        return False
    for sub in candidates:
        if not sub:
            continue
        target = base / sub
        if target.exists():
            return _xdg_open(target)
    return _xdg_open(base)


def _paths(game_id: str | None) -> dict:
    return game_data_paths(game_id)


def _apply_gpu_cool(_ctx: dict) -> dict:
    prof = profile_for_model(infer_gpu_model())
    steps: list[str] = []
    if prof.get("fan_curve_helpful"):
        tool = launch_fan_tool(prof)
        if tool:
            label = FIX_TOOL_SPECS.get(tool, {}).get("label", tool)
            steps.append(f"{label} opened — adjust fan curve")
    if not steps:
        return {
            "ok": False,
            "message": (
                "No fan tool found — lower graphics in-game. "
                + (prof.get("fan_curve_note") or prof.get("design_note", ""))
            ).strip(),
        }
    arch = prof.get("arch")
    if arch == "rdna3":
        tail = "Cap FPS and LOD in-game. RDNA3 rarely needs a fan curve unless clocks drop."
    elif prof.get("vendor") == "nvidia":
        tail = "Cap FPS and LOD in-game; CoolerControl or vendor tools help NVIDIA thermals."
    else:
        tail = "Cap FPS and LOD in-game; fan curves help most on RDNA2, Polaris, and NVIDIA."
    return {"ok": True, "message": " · ".join(steps) + ". " + tail}


def _apply_open_game(ctx: dict) -> dict:
    gname = ctx.get("name") or "game"
    open_dir = ctx.get("open_dir")
    if open_dir and _xdg_open(open_dir):
        return {"ok": True, "message": f"Opened {gname} folder — adjust graphics in-game."}
    return {"ok": False, "message": "Game folder not found — change settings in-game."}


def _apply_vram_bandwidth(ctx: dict) -> dict:
    gname = ctx.get("name") or "game"
    if _open_game_path(ctx, ".cache/Mods", "Mods", "mod"):
        return {
            "ok": True,
            "message": f"Opened {gname} data folder — lower texture and asset quality in-game.",
        }
    return {"ok": False, "message": "Game folder not found — change settings in-game."}


def _apply_steam_verify(ctx: dict) -> dict:
    appid = ctx.get("appid") or "730"
    gname = ctx.get("name") or "game"
    url = f"steam://validate/{appid}"
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return {
            "ok": False,
            "message": f"Could not open Steam verify — quit {gname}, then verify in Steam Properties.",
        }
    return {
        "ok": True,
        "message": (
            f"Opened Steam file verification for {gname}. "
            "Quit the game first if it's still running, then let verify and any update finish."
        ),
    }


def _apply_page_faults(ctx: dict) -> dict:
    gname = ctx.get("name") or "game"
    if _open_game_path(ctx, "Saves", "save", "Save Games", "saved"):
        return {
            "ok": True,
            "message": f"Opened {gname} data folder — let loading finish before unpausing.",
        }
    return {"ok": False, "message": "Game folder not found — wait for load to finish in-game."}


def apply_fix(
    insight_id: str,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
) -> dict:
    if requires_root(insight_id):
        return {
            "ok": False,
            "requires_root": True,
            "message": "This fix needs administrator access (sudo). Use the script below.",
        }
    ctx = _paths(game_id)
    if game_name:
        ctx["name"] = game_name

    handlers: dict[str, Callable[[dict], dict]] = {
        "gpu-thermal-ceiling": _apply_gpu_cool,
        "gpu-thermal-warm": _apply_gpu_cool,
        "gpu-vram-bandwidth": _apply_vram_bandwidth,
        "gpu-vram-full": _apply_open_game,
        "gpu-gtt-churn": _apply_vram_bandwidth,
        "memory-page-faults": _apply_page_faults,
        "gpu-shader-bound": _apply_open_game,
        "game-files-corrupt": _apply_steam_verify,
        "system-balanced": _apply_open_game,
    }
    handler = handlers.get(insight_id)
    if not handler:
        return {
            "ok": False,
            "suggest_only": True,
            "message": "No one-click fix — copy a command below and run it yourself.",
        }
    try:
        return handler(ctx)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "message": f"Fix failed: {exc}"}


def fix_available(insight_id: str) -> bool:
    handlers = {
        "gpu-thermal-ceiling", "gpu-thermal-warm", "gpu-vram-bandwidth",
        "gpu-vram-full", "gpu-gtt-churn", "memory-page-faults",
        "gpu-shader-bound", "game-files-corrupt", "system-balanced",
    }
    return insight_id in handlers and not requires_root(insight_id)