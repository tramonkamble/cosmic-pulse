# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tuning hints — rules live in YAML packs; this module wires evaluation + fallbacks."""

from __future__ import annotations

from apply_fix import fix_available, requires_root
from games import active_game_context
from rule_packs import evaluate_rule_packs, resolve_fix_script_for_insight
from fix_scripts import (
    get_fix_script,
    script_balanced,
)


def _hint(
    level: str,
    title: str,
    text: str,
    actions: list[dict],
    *,
    insight_id: str,
    fix_script: str,
    games: list[str] | None = None,
    needs_root: bool | None = None,
    bucket: str | None = None,
) -> dict:
    root = requires_root(insight_id) if needs_root is None else needs_root
    script = fix_script.strip()
    out = {
        "level": level,
        "title": title,
        "text": text,
        "actions": actions,
        "insight_id": insight_id,
        "fix_script": script,
        "has_fix_script": bool(script),
        "games": games or ["all"],
        "requires_root": root,
        "fixable": fix_available(insight_id) and not root,
    }
    if bucket:
        out["bucket"] = bucket
    return out


def _cmd(label: str, cmd: str, note: str = "", kind: str = "cmd") -> dict:
    return {"label": label, "kind": kind, "cmd": cmd, "note": note}


def _game_kwargs(snap: dict) -> dict:
    ctx = active_game_context(snap.get("game_totals"))
    return {"appid": ctx.get("appid"), "game_name": ctx.get("name")}


def _open_game_action(ctx: dict) -> dict | None:
    if ctx.get("open_dir"):
        return _cmd(f"Open {ctx['name']} folder", f"xdg-open '{ctx['open_dir']}'")
    return None


def system_context() -> dict:
    from pathlib import Path

    ctx: dict = {}
    try:
        ctx["governor"] = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    except OSError:
        ctx["governor"] = None
    try:
        ctx["swappiness"] = int(Path("/proc/sys/vm/swappiness").read_text().strip())
    except (OSError, ValueError):
        ctx["swappiness"] = None
    try:
        avail = [
            g.read_text().strip()
            for g in Path("/sys/devices/system/cpu/cpu0/cpufreq/").glob("scaling_available_governors")
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
    gk = _game_kwargs(snap)
    return [_hint(
        "ok",
        "Looking good",
        "No major issues right now. Check again when game load or mods increase.",
        [
            *([_open_game_action(gctx)] if _open_game_action(gctx) else []),
            _cmd(
                "Steam launch options (keep Wayland fix)",
                "PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%",
                kind="steam",
                note="Steam → game → Properties → Launch Options",
            ),
        ],
        insight_id="system-balanced",
        fix_script=script_balanced(**gk),
    )]


def fix_script_for_insight(
    insight_id: str,
    snap: dict,
    mem_spec: dict,
    ctx: dict | None = None,
    history: list[dict] | None = None,
) -> str:
    """Regenerate or recall a fix script for an insight (lazy API load)."""
    ctx = ctx or system_context()
    for h in build_tuning_hints(snap, mem_spec, ctx):
        if h.get("insight_id") == insight_id:
            return h.get("fix_script") or ""
    if history:
        for item in history:
            if item.get("insight_id") == insight_id:
                cached = item.get("fix_script") or ""
                if cached:
                    return cached
    pack_script = resolve_fix_script_for_insight(insight_id, snap, mem_spec, ctx)
    if pack_script:
        return pack_script
    gctx = active_game_context(snap.get("game_totals") or {})
    extra: dict = {
        "appid": gctx.get("appid"),
        "game_name": gctx.get("name"),
    }
    if insight_id == "vm-swappiness-high":
        extra["current"] = ctx.get("swappiness") or 60
    if insight_id == "game-libs-missing":
        try:
            from diagnostics import get_diagnostics
            from rule_packs import _LIB_FINDING_RE, _lib_install_context
            findings = (get_diagnostics() or {}).get("findings") or []
            lib_hits = [f for f in findings if _LIB_FINDING_RE.match(f["id"])]
            if lib_hits:
                lib_ctx = _lib_install_context(lib_hits)
                extra.update({
                    "lib_findings": lib_hits,
                    "multilib": lib_ctx["lib_multilib_needed"],
                    "apt_packages": lib_ctx["lib_apt_packages"],
                })
        except Exception:
            pass
    return get_fix_script(insight_id, **extra)