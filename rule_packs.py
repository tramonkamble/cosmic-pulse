# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Community rule packs — declarative detect/emit rules loaded from YAML."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from apply_fix import fix_available, requires_root
from diagnostics import _PROMOTE_SEVERITIES, scan_findings
from fix_scripts import get_fix_script
from games import (
    active_game_context,
    game_meta,
    game_session_launch_metrics,
    session_is_wayland,
    steam_install_health,
    steam_root,
    steam_update_needs_attention,
    steam_update_summary_parts,
)
from gpu_thermal import gpu_thermal_state, profile_for_model
from hardware_probe import primary_display_refresh_hz
from load_phase import page_fault_settle, page_fault_warn

PULSE_ROOT = Path(__file__).resolve().parent
BUILTIN_RULES = PULSE_ROOT / "rules" / "builtin"
USER_RULES = Path.home() / ".config" / "pulse" / "rules"

_TEMPLATE_RE = re.compile(r"\{([^}]+)\}")
_UNRESOLVED_TEMPLATE_RE = re.compile(r"\{[^}]+\}")
_PACK_CACHE: dict[str, Any] = {"mtime": 0.0, "packs": []}


def rule_search_paths() -> list[Path]:
    paths: list[Path] = []
    extra = os.environ.get("PULSE_RULE_PATH", "")
    if extra:
        paths.extend(Path(p) for p in extra.split(os.pathsep) if p.strip())
    paths.append(BUILTIN_RULES)
    paths.append(USER_RULES)
    return paths


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _coerce_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1", "on")
    return bool(val)


def render_template(template: str, metrics: dict) -> str:
    if not template or "{" not in template:
        return template

    def repl(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if ":" in expr:
            path, fmt = expr.rsplit(":", 1)
            path = path.strip()
            fmt = fmt.strip()
        else:
            path, fmt = expr, ""
        val = _get_path(metrics, path)
        if val is None:
            return match.group(0)
        if fmt:
            try:
                return format(val, fmt)
            except (ValueError, TypeError):
                return str(val)
        return str(val)

    return _TEMPLATE_RE.sub(repl, template)


def _has_unresolved_template(text: str) -> bool:
    return bool(text and _UNRESOLVED_TEMPLATE_RE.search(text))


def _render_actions(actions: list[dict] | None, metrics: dict) -> list[dict]:
    out: list[dict] = []
    for action in actions or []:
        rendered = {
            "label": render_template(str(action.get("label", "")), metrics),
            "kind": action.get("kind", "cmd"),
            "cmd": render_template(str(action.get("cmd", "")), metrics),
            "note": render_template(str(action.get("note", "")), metrics),
        }
        blob = f"{rendered['label']}{rendered['cmd']}{rendered['note']}"
        if _has_unresolved_template(blob):
            continue
        out.append(rendered)
    return out


_LIB_FINDING_RE = re.compile(r"^lib-missing-|lib-multilib-missing")

_DEFAULT_LIB_PKGS = "libvulkan1 mesa-vulkan-drivers libgl1 libgamemode0 libldap2 libgpg-error0"


def _lib_install_context(lib_hits: list[dict]) -> dict[str, Any]:
    """Derive apt/multilib install lines from diagnostics lib findings."""
    pkgs: list[str] = []
    multilib = False
    for f in lib_hits:
        fix = (f.get("fix") if isinstance(f, dict) else "") or ""
        if "add-architecture i386" in fix or f.get("id") == "lib-multilib-missing":
            multilib = True
            pkgs.extend(["libgl1:i386", "libvulkan1:i386", "libldap2:i386"])
        elif fix.startswith("sudo apt install "):
            pkgs.extend(fix.replace("sudo apt install ", "").split())
    pkgs = list(dict.fromkeys(pkgs))
    apt_install = (
        f"sudo apt install {' '.join(pkgs)}" if pkgs else f"sudo apt install {_DEFAULT_LIB_PKGS}"
    )
    return {
        "lib_multilib_needed": multilib,
        "lib_apt_packages": " ".join(pkgs),
        "lib_apt_install": apt_install,
        "lib_findings": lib_hits,
    }


def _flatten_diag(findings: list[dict], active_appid: str | None, running: bool) -> dict:
    """Boolean/text signals from diagnostics for pack rules."""
    lib_hits = [f for f in findings if _LIB_FINDING_RE.match(f["id"])]
    vulkan_hits = [f for f in findings if f["id"] in ("vulkaninfo-error", "vulkan-device-mismatch")]
    disk_hit = next((f for f in findings if f["id"] == "disk-steam-low"), None)
    corrupt_hit = (
        next((f for f in findings if f["id"] == f"steam-corrupt-{active_appid}"), None)
        if active_appid
        else None
    )
    update_hit = (
        next((f for f in findings if f["id"] == f"steam-update-{active_appid}"), None)
        if active_appid
        else None
    )
    exit_hit = (
        next((f for f in findings if f["id"] == f"game-exit-{active_appid}"), None)
        if active_appid
        else None
    )

    def promoted(hit: dict | None) -> bool:
        return bool(hit and hit.get("severity") in _PROMOTE_SEVERITIES)

    lib_lines = [f["title"] for f in lib_hits[:4]]
    lib_summary = " · ".join(lib_lines)
    if len(lib_hits) > 4:
        lib_summary += " …"
    lib_ctx = _lib_install_context(lib_hits)

    return {
        "game_libs_missing": bool(lib_hits),
        "lib_missing_hot": any(f["severity"] == "hot" for f in lib_hits),
        "lib_missing_summary": lib_summary,
        **lib_ctx,
        "steam_disk_low": promoted(disk_hit),
        "disk_free_gb": float(re.search(r"([\d.]+)\s*GB free", disk_hit["title"]).group(1))
        if disk_hit and re.search(r"([\d.]+)\s*GB free", disk_hit["title"])
        else 0.0,
        "disk_title": (disk_hit or {}).get("title", ""),
        "disk_text": (disk_hit or {}).get("text", ""),
        "disk_severity": (disk_hit or {}).get("severity", "warn"),
        "vulkan_broken": bool(vulkan_hits),
        "vulkan_hot": any(h["severity"] == "hot" for h in vulkan_hits),
        "vulkan_title": (vulkan_hits[0]["title"] if vulkan_hits else ""),
        "vulkan_text": (vulkan_hits[0]["text"] if vulkan_hits else ""),
        "game_files_corrupt": promoted(corrupt_hit),
        "corrupt_title": (corrupt_hit or {}).get("title", ""),
        "corrupt_text": (corrupt_hit or {}).get("text", ""),
        "game_update_pending": promoted(update_hit) and running,
        "update_title": (update_hit or {}).get("title", ""),
        "update_text": (update_hit or {}).get("text", ""),
        "game_prefix_reset": promoted(exit_hit),
        "exit_title": (exit_hit or {}).get("title", ""),
        "exit_text": (exit_hit or {}).get("text", ""),
        "exit_codes": (
            re.search(r"codes (\[[^\]]+\])", exit_hit["text"]).group(1)
            if exit_hit and re.search(r"codes (\[[^\]]+\])", exit_hit["text"])
            else "[]"
        ),
        "exit_severe": bool(
            exit_hit and ("139" in exit_hit.get("text", "") or "137" in exit_hit.get("text", ""))
        ),
        "bin_missing_mangohud": any(f["id"] == "bin-missing-mangohud" for f in findings),
        "bin_missing_gamemoded": any(f["id"] == "bin-missing-gamemoded" for f in findings),
    }


def _flatten_steam(active_appid: str | None, running: bool) -> dict:
    if not active_appid:
        return {
            "files_corrupt": False,
            "update_needs_attention": False,
            "update_summary": "",
            "pending_mb": 0.0,
            "stage_mb": 0.0,
            "shader_mb": 0.0,
            "suspended_while_running": False,
        }
    health = steam_install_health(active_appid)
    pending_mb = health.get("effective_pending_download_bytes", 0) / 1024**2
    stage_mb = health.get("effective_pending_stage_bytes", 0) / 1024**2
    shader_mb = health.get("shader_cache_bytes", 0) / 1024**2
    parts = steam_update_summary_parts(health)
    if health.get("update_suspended_while_running"):
        parts = ["the patch paused because the game launched early", *parts]
    return {
        "files_corrupt": bool(health.get("files_corrupt")),
        "update_needs_attention": steam_update_needs_attention(health, running=running),
        "update_summary": " · ".join(parts).capitalize() if parts else "",
        "pending_mb": pending_mb,
        "stage_mb": stage_mb,
        "shader_mb": shader_mb,
        "suspended_while_running": bool(health.get("update_suspended_while_running")),
    }


def flatten_metrics(snap: dict, mem_spec: dict, ctx: dict) -> dict:
    """Namespace for pack detect conditions and emit templates."""
    g = (snap.get("gpu") or {}).get("discrete") or {}
    mem = snap.get("memory") or {}
    bw = snap.get("bandwidth") or {}
    dram = bw.get("memory") or {}
    cpu = snap.get("cpu") or {}
    gt = snap.get("game_totals") or {}
    gctx = active_game_context(gt)
    st = snap.get("stutter") or {}
    sess = st.get("session") or {}
    gtt = g.get("gtt") or {}
    lp = snap.get("load_phase") or {}
    fault_rate = int(dram.get("pgmajfault_per_s") or 0)
    refresh_hz = primary_display_refresh_hz()
    thermal_profile = g.get("thermal_profile") or profile_for_model(
        ctx.get("gpu_model") or (g.get("thermal_profile") or {}).get("model") or "",
    )
    vram_pct = float(g.get("vram_pct") or 0)
    gtt_pool_pct = float(gtt.get("pct") or 0)
    mem_busy_pct = g.get("mem_busy_pct")
    cpu_pct = float(cpu.get("overall_pct") or 0)
    busy = float(g.get("busy_pct") or 0)
    swap_pct = float(mem.get("swap_pct") or 0)
    st_score = float(st.get("score") or 0)
    junc = g.get("junction_c")
    hot_c = float(thermal_profile.get("hot_c") or 100)
    warm_c = thermal_profile.get("warm_c")
    fan_help = bool(thermal_profile.get("fan_curve_helpful", True))
    thermal_state = g.get("thermal_state") or gpu_thermal_state(
        g,
        thermal_profile,
        ctx.get("gpu_session_peak_mhz"),
    )
    causes = st.get("causes") or []
    cause_labels = st.get("cause_labels") or {}
    cause_txt = ", ".join(cause_labels.get(c, c) for c in causes) or "memory pressure"
    active_appid = str(gctx.get("appid") or gt.get("game_id") or "") or None
    running = bool(gt.get("running"))
    launch_metrics = game_session_launch_metrics(
        active_appid if running else None,
        gt.get("primary_pid"),
    )

    try:
        from diagnostics import get_diagnostics

        findings = (get_diagnostics() or {}).get("findings") or []
    except Exception:
        findings = []

    return {
        "ctx": {
            "governor": ctx.get("governor"),
            "swappiness": ctx.get("swappiness"),
            "gpu_model": ctx.get("gpu_model") or thermal_profile.get("model") or "",
        },
        "session": {
            "wayland": session_is_wayland(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP") or "",
        },
        "game": {
            "running": bool(gt.get("running")),
            "appid": gctx.get("appid"),
            "name": gctx.get("name") or "your game",
            "proton": bool(launch_metrics["proton"]),
            "wayland_fix_missing": bool(launch_metrics["wayland_fix_missing"]),
        },
        "display": {
            "refresh_hz": refresh_hz,
            "cap_hz": int(round(refresh_hz)) if refresh_hz else 60,
        },
        "cpu": {
            "overall_pct": cpu_pct,
            "ccd0_c": (cpu.get("temps", {}).get("ccd") or [None, None])[0],
            "ccd1_c": (cpu.get("temps", {}).get("ccd") or [None, None])[1]
            if len(cpu.get("temps", {}).get("ccd") or []) > 1
            else None,
        },
        "gpu": {
            "busy_pct": busy,
            "mem_busy_pct": mem_busy_pct if mem_busy_pct is not None else -1,
            "vram_pct": vram_pct,
            "vram_used_mb": g.get("vram_used_mb") or 0,
            "junction_c": g.get("junction_c"),
            "gtt_rate_mbps": float(gtt.get("rate_mbps") or 0),
            "gtt_pool_pct": gtt_pool_pct,
            "gtt_sustained_high": bool(gtt.get("sustained_high")),
        },
        "memory": {
            "swap_pct": swap_pct,
            "swap_out_kbps": float(dram.get("swap_out_kbps") or 0),
            "psi_avg10": float(dram.get("psi_avg10") or 0),
            "pgmajfault_per_s": fault_rate,
        },
        "stutter": {
            "score": st_score,
            "event": bool(st.get("event")),
            "severity": st.get("severity") or "mild",
            "session_events": int(sess.get("events") or 0),
        },
        "load_phase": {
            "phase": lp.get("phase") or "idle",
            "in_grace": bool(lp.get("in_grace")),
            "sustained_fault_playing": bool(lp.get("sustained_fault_playing")),
            "suppress_page_fault_warn": bool(lp.get("suppress_page_fault_warn")),
        },
        "signals": {
            "page_fault_warn": page_fault_warn(snap, fault_rate),
            "page_fault_settle": page_fault_settle(snap, fault_rate),
            "gtt_spill_risk": (
                vram_pct >= 70
                or gtt_pool_pct >= 20
                or (mem_busy_pct is not None and mem_busy_pct >= 50)
            ),
            "load_phase_loading": lp.get("phase") == "loading" or bool(lp.get("in_grace")),
        },
        "thermal": {
            "throttling": bool(thermal_state.get("throttling")),
            "by_design": bool(thermal_state.get("by_design")),
            "fan_curve_helpful": fan_help,
            "hot_c": hot_c,
            "warm_c": warm_c if warm_c is not None else -1,
            "is_hot": junc is not None and float(junc) >= hot_c,
            "is_warm": (
                warm_c is not None and junc is not None and float(warm_c) <= float(junc) < hot_c
            ),
            "gfx_mhz": g.get("gfx_mhz") or 0,
            "peak_mhz": thermal_state.get("observed_peak_mhz")
            or thermal_state.get("session_peak_mhz")
            or 0,
            "arch_label": thermal_profile.get("label", "GPU"),
            "design_note": thermal_profile.get("design_note", ""),
        },
        "stutter_detail": {
            "est_ms": int(st.get("est_ms") or 0),
            "cause_text": cause_txt,
            "hitch_ms_1pct": int(sess.get("hitch_ms_1pct") or 0),
            "severity": st.get("severity") or "mild",
        },
        "steam": {
            **_flatten_steam(active_appid, running),
            "root": str(steam_root()),
        },
        "diag": _flatten_diag(findings, active_appid, running),
        "tools": {
            "mangohud": bool(shutil.which("mangohud")),
            "gamemoded": bool(shutil.which("gamemoded")),
            "gamemode_lib": "libgamemode.so.0" in _ldconfig_quick(),
        },
        "mem_spec": {
            "spd_mts": mem_spec.get("spd_mts") or 4800,
            "configured_mts": mem_spec.get("configured_mts") or mem_spec.get("speed_mts") or 6000,
            "source": mem_spec.get("source") or "",
            "part": mem_spec.get("part") or "",
        },
    }


def _ldconfig_quick() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["ldconfig", "-p"], text=True, timeout=5, stderr=subprocess.STDOUT
        )
    except Exception:
        return ""


def _compare(metric_val: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return metric_val is not None
    if op == "not_exists":
        return metric_val is None
    if metric_val is None:
        return False

    if op == "eq":
        if isinstance(expected, bool) or expected in ("true", "false"):
            return _coerce_bool(metric_val) == _coerce_bool(expected)
        return metric_val == expected
    if op == "ne":
        if isinstance(expected, bool) or expected in ("true", "false"):
            return _coerce_bool(metric_val) != _coerce_bool(expected)
        return metric_val != expected
    if op == "in":
        return metric_val in (expected or [])
    if op == "not_in":
        return metric_val not in (expected or [])

    try:
        left = float(metric_val)
        right = float(expected)
    except (TypeError, ValueError):
        return False

    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def _eval_leaf(cond: dict, metrics: dict) -> bool:
    if "metric" not in cond:
        return False
    val = _get_path(metrics, str(cond["metric"]))
    for op in ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "exists", "not_exists"):
        if op in cond:
            return _compare(val, op, cond[op])
    return False


def eval_condition(cond: Any, metrics: dict) -> bool:
    if cond is None:
        return True
    if isinstance(cond, bool):
        return cond
    if not isinstance(cond, dict):
        return False
    if "all" in cond:
        return all(eval_condition(c, metrics) for c in (cond["all"] or []))
    if "any" in cond:
        return any(eval_condition(c, metrics) for c in (cond["any"] or []))
    if "not" in cond:
        return not eval_condition(cond["not"], metrics)
    return _eval_leaf(cond, metrics)


def match_pack(pack: dict, metrics: dict) -> bool:
    match_when = pack.get("match_when")
    if not match_when:
        return True
    return eval_condition(match_when, metrics)


def _resolve_games(emit: dict, metrics: dict) -> list[str]:
    games = emit.get("games")
    if games is None:
        return ["all"]
    if games == "active":
        appid = _get_path(metrics, "game.appid")
        return [str(appid)] if appid else ["all"]
    out: list[str] = []
    for item in games:
        rendered = render_template(str(item), metrics)
        if rendered and rendered != "{game.appid}":
            out.append(rendered)
    return out or ["all"]


def _resolve_fix_script(
    emit: dict,
    metrics: dict,
    pack_dir: Path,
    game_kwargs: dict,
) -> str:
    spec = emit.get("fix_script")
    if spec is None or spec == "":
        return ""
    spec = str(spec)
    if spec.startswith("file:"):
        path = pack_dir / spec[5:].lstrip("/")
        try:
            return path.read_text().strip()
        except OSError:
            return ""

    insight_id = emit.get("insight_id", spec)
    kwargs: dict[str, Any] = {}
    for key, metric_path in (emit.get("fix_kwargs") or {}).items():
        kwargs[key] = _get_path(metrics, str(metric_path))
    if emit.get("game_context"):
        kwargs.update(game_kwargs)
    try:
        return get_fix_script(insight_id, **kwargs).strip()
    except TypeError:
        try:
            return get_fix_script(insight_id).strip()
        except TypeError:
            return ""


def _resolve_level(emit: dict, metrics: dict) -> str:
    level_when = emit.get("level_when")
    if isinstance(level_when, dict):
        if eval_condition(level_when.get("detect"), metrics):
            return str(level_when.get("then", emit.get("level", "info")))
        return str(level_when.get("else", emit.get("level", "info")))
    return str(emit.get("level", "info"))


def _pack_hint(
    emit: dict,
    actions: list[dict],
    fix_script: str,
    metrics: dict,
    *,
    pack_id: str,
    rule_id: str,
) -> dict:
    insight_id = str(emit["insight_id"])
    needs_root = emit.get("requires_root")
    root = requires_root(insight_id) if needs_root is None else bool(needs_root)
    script = fix_script.strip()
    out = {
        "level": _resolve_level(emit, metrics),
        "title": render_template(str(emit.get("title", "")), metrics),
        "text": render_template(str(emit.get("text", "")), metrics),
        "actions": actions,
        "insight_id": insight_id,
        "fix_script": script,
        "has_fix_script": bool(script),
        "games": _resolve_games(emit, metrics),
        "requires_root": root,
        "fixable": fix_available(insight_id) and not root,
        "pack_id": pack_id,
        "rule_id": rule_id,
    }
    bucket = emit.get("bucket")
    if bucket:
        out["bucket"] = bucket
    if emit.get("condition_live"):
        out["condition_live"] = True
    return out


def promoted_finding_skip_ids(
    emitted: set[str],
    findings: list[dict],
    *,
    active_appid: str | None,
    running: bool,
) -> set[str]:
    """Finding IDs consumed by promoted Guidance rules (for system scan panel)."""
    skip: set[str] = set()
    metrics = {
        "diag": _flatten_diag(findings, active_appid, running),
        "steam": _flatten_steam(active_appid, running),
        "game": {"running": running},
    }
    if "game-libs-missing" in emitted and metrics["diag"]["game_libs_missing"]:
        skip.update(f["id"] for f in findings if _LIB_FINDING_RE.match(f["id"]))
    if "steam-disk-low" in emitted:
        skip.add("disk-steam-low")
    if "vulkan-broken" in emitted:
        skip.update(
            f["id"] for f in findings if f["id"] in ("vulkaninfo-error", "vulkan-device-mismatch")
        )
    if active_appid:
        if "game-files-corrupt" in emitted:
            skip.add(f"steam-corrupt-{active_appid}")
        if "game-update-pending" in emitted:
            skip.add(f"steam-update-{active_appid}")
        if "game-prefix-reset" in emitted:
            skip.add(f"game-exit-{active_appid}")
    if "mangohud-recommended" in emitted:
        skip.add("bin-missing-mangohud")
    if "gamemode-recommended" in emitted:
        skip.add("bin-missing-gamemoded")
    return skip


def scan_findings_for_guidance(
    findings: list[dict],
    emitted: set[str],
    *,
    active_appid: str | None,
    running: bool,
) -> list[dict]:
    skip = promoted_finding_skip_ids(
        emitted,
        findings,
        active_appid=active_appid,
        running=running,
    )
    return scan_findings(findings, skip_ids=skip)


def _load_rule_file(path: Path) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    rules = data.get("rules")
    if isinstance(rules, list):
        return [r for r in rules if isinstance(r, dict)]
    return []


def _pack_dir_mtime(root: Path) -> float:
    latest = 0.0
    if not root.is_dir():
        return latest
    for path in root.rglob("*"):
        if path.suffix in (".yaml", ".yml"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                pass
    return latest


def _load_packs(force: bool = False) -> list[dict]:
    latest = max((_pack_dir_mtime(p) for p in rule_search_paths()), default=0.0)
    if not force and _PACK_CACHE["packs"] and latest <= _PACK_CACHE["mtime"]:
        return _PACK_CACHE["packs"]

    packs: list[dict] = []
    seen_ids: set[str] = set()
    for root in rule_search_paths():
        if not root.is_dir():
            continue
        for manifest in sorted(root.glob("*/pack.yaml")) + sorted(root.glob("*/pack.yml")):
            try:
                pack = yaml.safe_load(manifest.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            pack_id = str(pack.get("id") or manifest.parent.name)
            if pack_id in seen_ids:
                continue
            seen_ids.add(pack_id)
            pack_dir = manifest.parent
            rules: list[dict] = []
            for entry in pack.get("rules") or []:
                rule_path = pack_dir / str(entry)
                rules.extend(_load_rule_file(rule_path))
            for inline in pack.get("inline_rules") or []:
                if isinstance(inline, dict):
                    rules.append(inline)
            packs.append(
                {
                    "id": pack_id,
                    "name": pack.get("name", pack_id),
                    "version": pack.get("version", "0"),
                    "priority": int(pack.get("priority") or 0),
                    "dir": pack_dir,
                    "manifest": pack,
                    "rules": rules,
                }
            )

    packs.sort(key=lambda p: p["priority"], reverse=True)
    _PACK_CACHE["mtime"] = latest
    _PACK_CACHE["packs"] = packs
    try:
        from games import reload_game_pack_data

        reload_game_pack_data()
    except Exception:
        pass
    return packs


def _normalize_override_entry(appid: str, raw: dict) -> dict:
    """Coerce pack YAML game_overrides entry into games.py shape."""
    out: dict[str, Any] = {}
    if "name" in raw:
        out["name"] = str(raw["name"])
    if "short" in raw:
        out["short"] = str(raw["short"])
    if "main_exe" in raw:
        exes = raw["main_exe"]
        if isinstance(exes, (list, tuple, set, frozenset)):
            out["main_exe"] = frozenset(str(x).lower() for x in exes if x)
    if "exclude_exe" in raw:
        exes = raw["exclude_exe"]
        if isinstance(exes, (list, tuple, set, frozenset)):
            out["exclude_exe"] = frozenset(str(x).lower() for x in exes if x)
    return out


def get_legacy_game_ids() -> dict[str, str]:
    """Merged legacy game_id → AppID map from all enabled packs (lowest priority first)."""
    merged: dict[str, str] = {}
    for pack in reversed(_load_packs()):
        manifest = pack.get("manifest") or {}
        legacy = manifest.get("legacy_game_ids") or {}
        if isinstance(legacy, dict):
            for legacy_id, appid in legacy.items():
                if legacy_id and appid:
                    merged[str(legacy_id)] = str(appid)
    return merged


def get_game_overrides() -> dict[str, dict]:
    """Merged per-AppID detection overrides from all enabled packs (lowest priority first)."""
    merged: dict[str, dict] = {}
    for pack in reversed(_load_packs()):
        manifest = pack.get("manifest") or {}
        overrides = manifest.get("game_overrides") or {}
        if not isinstance(overrides, dict):
            continue
        for appid, raw in overrides.items():
            if not appid or not isinstance(raw, dict):
                continue
            entry = _normalize_override_entry(str(appid), raw)
            if entry:
                merged[str(appid)] = {**merged.get(str(appid), {}), **entry}
    return merged


def game_context_kwargs(metrics: dict) -> dict[str, Any]:
    """Kwargs for fix scripts from active game metrics."""
    appid = metrics.get("game", {}).get("appid")
    name = metrics.get("game", {}).get("name")
    if appid and (not name or name == "your game"):
        name = game_meta(str(appid)).get("name") or name
    return {
        "appid": str(appid) if appid else None,
        "game_name": name or "your game",
    }


def list_packs() -> list[dict]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "version": p["version"],
            "priority": p["priority"],
            "rule_count": len(p["rules"]),
            "override_count": sum(
                1 for aid in (p.get("manifest") or {}).get("game_overrides") or {}
            ),
            "legacy_id_count": len((p.get("manifest") or {}).get("legacy_game_ids") or {}),
            "path": str(p["dir"]),
        }
        for p in _load_packs()
    ]


def resolve_fix_script_for_insight(
    insight_id: str,
    snap: dict,
    mem_spec: dict,
    ctx: dict,
) -> str:
    """Rebuild fix script from pack rules + live metrics (fallback for /api/fix-script)."""
    metrics = flatten_metrics(snap, mem_spec, ctx)
    game_kwargs = game_context_kwargs(metrics)
    for pack in _load_packs():
        if not match_pack(pack["manifest"], metrics):
            continue
        for rule in pack["rules"]:
            emit = rule.get("emit") or {}
            if str(emit.get("insight_id") or "") != insight_id:
                continue
            if not eval_condition(rule.get("detect"), metrics):
                continue
            return _resolve_fix_script(emit, metrics, pack["dir"], game_kwargs)
    return ""


def evaluate_rule_packs(
    snap: dict,
    mem_spec: dict,
    ctx: dict,
) -> tuple[list[dict], set[str]]:
    """Evaluate installed packs; return hints and insight_ids emitted."""
    metrics = flatten_metrics(snap, mem_spec, ctx)
    game_kwargs = game_context_kwargs(metrics)
    hints: list[dict] = []
    emitted: set[str] = set()

    for pack in _load_packs():
        if not match_pack(pack["manifest"], metrics):
            continue
        for rule in pack["rules"]:
            rule_id = str(rule.get("id") or rule.get("emit", {}).get("insight_id") or "rule")
            detect = rule.get("detect")
            if not eval_condition(detect, metrics):
                continue
            emit = rule.get("emit") or {}
            insight_id = str(emit.get("insight_id") or "")
            if not insight_id or insight_id in emitted:
                continue
            actions = _render_actions(rule.get("actions"), metrics)
            fix_script = _resolve_fix_script(emit, metrics, pack["dir"], game_kwargs)
            hints.append(
                _pack_hint(
                    emit,
                    actions,
                    fix_script,
                    metrics,
                    pack_id=pack["id"],
                    rule_id=rule_id,
                )
            )
            emitted.add(insight_id)

    return hints, emitted
