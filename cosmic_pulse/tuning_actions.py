# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tuning hints — rules live in YAML packs; this module wires evaluation + fallbacks."""

from __future__ import annotations

from .apply_fix import requires_root
from .games import active_game_context
from .rule_packs import evaluate_rule_packs


def _hint(
    level: str,
    title: str,
    text: str,
    actions: list[dict],
    *,
    insight_id: str,
    games: list[str] | None = None,
    needs_root: bool | None = None,
    bucket: str | None = None,
) -> dict:
    root = requires_root(insight_id) if needs_root is None else needs_root
    out = {
        "level": level,
        "title": title,
        "text": text,
        "actions": actions,
        "insight_id": insight_id,
        "games": games or ["all"],
        "requires_root": root,
    }
    if bucket:
        out["bucket"] = bucket
    return out


def _cmd(label: str, cmd: str, note: str = "", kind: str = "cmd") -> dict:
    return {"label": label, "kind": kind, "cmd": cmd, "note": note}


def _open_game_action(ctx: dict) -> dict | None:
    if ctx.get("open_dir"):
        return _cmd(f"Open {ctx['name']} folder", f"xdg-open '{ctx['open_dir']}'")
    return None


def system_context() -> dict:
    from pathlib import Path

    ctx: dict = {}
    try:
        ctx["governor"] = (
            Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
        )
    except OSError:
        ctx["governor"] = None
    try:
        ctx["swappiness"] = int(Path("/proc/sys/vm/swappiness").read_text().strip())
    except (OSError, ValueError):
        ctx["swappiness"] = None
    try:
        avail = [
            g.read_text().strip()
            for g in Path("/sys/devices/system/cpu/cpu0/cpufreq/").glob(
                "scaling_available_governors"
            )
        ]
        ctx["governors_avail"] = avail[0].split() if avail else []
    except OSError:
        ctx["governors_avail"] = []
    return ctx


def build_tuning_hints(snap: dict, mem_spec: dict, ctx: dict | None = None) -> list[dict]:
    ctx = ctx or system_context()
    g = snap["gpu"]["discrete"]
    if not ctx.get("gpu_model"):
        ctx["gpu_model"] = (g.get("thermal_profile") or {}).get("model") or ""

    hints, _emitted = evaluate_rule_packs(snap, mem_spec, ctx)
    if hints:
        return hints

    gctx = active_game_context(snap.get("game_totals") or {})
    return [
        _hint(
            "ok",
            "Looking good",
            "No major issues right now. Check again when game load or mods increase.",
            [
                *([_open_game_action(gctx)] if _open_game_action(gctx) else []),
                _cmd(
                    "Wayland + Proton games",
                    "See Guidance: Proton on Wayland — X11 override (per game)",
                    kind="game",
                    note="Only if mouse/camera acts up on COSMIC/Wayland",
                ),
            ],
            insight_id="system-balanced",
            needs_root=False,
        )
    ]
