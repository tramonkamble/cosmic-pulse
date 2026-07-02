# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Issue-specific tuning actions with copy-paste commands."""

from __future__ import annotations

from pathlib import Path

from apply_fix import fix_available, requires_root
from games import active_game_context, steam_install_health
from gpu_thermal import gpu_thermal_state, profile_for_model
from fix_scripts import (
    fan_tool_actions,
    script_balanced,
    script_ccd_spread,
    script_cpu_bound,
    script_dram_stall,
    script_expo_verify,
    script_governor,
    script_gpu_shader,
    script_gpu_thermal,
    script_gpu_warm,
    script_gtt,
    script_page_faults,
    script_swap_thrash,
    script_swappiness,
    script_vram_bandwidth,
    script_steam_verify_files,
    script_stutter,
    script_vram_low,
)

PULSE_ROOT = Path(__file__).resolve().parent
PROBE_SCRIPT = PULSE_ROOT / "probe_memory.py"


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
) -> dict:
    root = requires_root(insight_id) if needs_root is None else needs_root
    return {
        "level": level,
        "title": title,
        "text": text,
        "actions": actions,
        "insight_id": insight_id,
        "fix_script": fix_script.strip(),
        "games": games or ["all"],
        "requires_root": root,
        "fixable": fix_available(insight_id) and not root,
    }


def _cmd(label: str, cmd: str, note: str = "", kind: str = "cmd") -> dict:
    return {"label": label, "kind": kind, "cmd": cmd, "note": note}


def _game_kwargs(snap: dict) -> dict:
    ctx = active_game_context(snap.get("game_totals"))
    return {"game_id": ctx.get("appid"), "game_name": ctx.get("name")}


def _open_game_action(ctx: dict) -> dict | None:
    if ctx.get("open_dir"):
        return _cmd(f"Open {ctx['name']} folder", f"xdg-open '{ctx['open_dir']}'")
    return None


def _gpu_cmd_paths(ctx: dict) -> dict[str, str]:
    sysfs = ctx.get("gpu_sysfs") or "/sys/class/drm/card1/device"
    sensor = ctx.get("gpu_sensor") or "amdgpu-pci-0300"
    return {"sysfs": sysfs, "sensor": sensor}


def _append_gpu_thermal_hints(
    hints: list[dict],
    g: dict,
    profile: dict,
    ctx: dict,
) -> None:
    paths = _gpu_cmd_paths(ctx)
    junc = g.get("junction_c")
    if junc is None:
        return

    arch = profile.get("label", "GPU")
    model = profile.get("model") or "GPU"
    throttle = profile.get("throttle_c", 110)
    hot_c = profile.get("hot_c", 100)
    warm_c = profile.get("warm_c")
    fan_help = profile.get("fan_curve_helpful", True)
    fan_note = profile.get("fan_curve_note", "")
    thermal = g.get("thermal_state") or gpu_thermal_state(
        g, profile, ctx.get("gpu_session_peak_mhz"),
    )
    gfx = g.get("gfx_mhz")
    peak = thermal.get("session_peak_mhz")

    cool_actions = [
        _cmd(
            "In-game: lower shadow / LOD / draw distance",
            "Lower Level of Detail, Shadow quality, and cap FPS 60–90",
            kind="game",
        ),
    ]
    if fan_help:
        for action in fan_tool_actions(profile, paths["sysfs"]):
            cool_actions.append(_cmd(action["label"], action["cmd"], note=action.get("note", ""), kind=action.get("kind", "cmd")))

    if not fan_help:
        if thermal.get("throttling"):
            text = (
                f"Junction {junc}°C and clocks dropped to {gfx or '—'} MHz "
                f"(session peak ~{peak or '—'} MHz). {arch} is throttling — lower graphics settings."
            )
            hints.append(_hint(
                "warn",
                "GPU throttling",
                text,
                cool_actions,
                insight_id="gpu-thermal-ceiling",
                fix_script=script_gpu_thermal(junc, profile=profile),
            ))
        elif thermal.get("by_design"):
            hints.append(_hint(
                "info",
                "GPU running hot by design",
                f"Junction {junc}°C — {profile.get('design_note', '')} "
                f"Clocks at {gfx or '—'} MHz"
                + (f" (peak ~{peak} MHz this session)." if peak else "."),
                [
                    _cmd(
                        "Check clocks + temps",
                        f"sensors {paths['sensor']} | grep -E 'junction|edge|fan|PPT'; "
                        f"cat {paths['sysfs']}/pp_dpm_sclk 2>/dev/null | tail -1",
                        note="Stable clocks under load = normal for this architecture",
                    ),
                ],
                insight_id="gpu-thermal-by-design",
                fix_script="",
            ))
        return

    if junc >= hot_c:
        text = (
            f"Junction is {junc}°C. Near the {arch} throttle (~{throttle}°C) — "
            "lower graphics settings or improve cooling."
        )
        title = "GPU overheating"
        if thermal.get("throttling"):
            title = "GPU throttling"
            text = (
                f"Junction {junc}°C with clocks at {gfx or '—'} MHz "
                f"(peak ~{peak or '—'} MHz). Lower graphics settings or improve cooling."
            )
        hints.append(_hint(
            "hot",
            title,
            text,
            cool_actions,
            insight_id="gpu-thermal-ceiling",
            fix_script=script_gpu_thermal(junc, profile=profile),
        ))
    elif warm_c is not None and junc >= warm_c:
        warm_actions = [
            _cmd("Cap FPS in-game", "Graphics → Frame rate limit → 90", kind="game"),
            _cmd(
                "Check GPU power",
                f"cat {paths['sysfs']}/hwmon/hwmon*/power1_cap 2>/dev/null; "
                f"sensors {paths['sensor']} | grep -i ppt",
            ),
        ]
        if fan_help:
            for action in fan_tool_actions(profile, paths["sysfs"]):
                warm_actions.append(
                    _cmd(action["label"], action["cmd"], note=action.get("note", ""), kind=action.get("kind", "cmd")),
                )
        warm_text = f"Junction is {junc}°C. {profile.get('design_note', '')}"
        if fan_help and fan_note:
            warm_text = f"Junction is {junc}°C. {fan_note}"
        hints.append(_hint(
            "warn",
            "GPU getting warm",
            warm_text,
            warm_actions,
            insight_id="gpu-thermal-warm",
            fix_script=script_gpu_warm(junc, profile=profile),
        ))


def system_context() -> dict:
    ctx: dict = {}
    try:
        ctx["governor"] = (Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip())
    except OSError:
        ctx["governor"] = None
    try:
        ctx["swappiness"] = int(Path("/proc/sys/vm/swappiness").read_text().strip())
    except (OSError, ValueError):
        ctx["swappiness"] = None
    try:
        avail = [g.read_text().strip() for g in Path("/sys/devices/system/cpu/cpu0/cpufreq/").glob("scaling_available_governors")]
        ctx["governors_avail"] = avail[0].split() if avail else []
    except OSError:
        ctx["governors_avail"] = []
    return ctx


def build_tuning_hints(snap: dict, mem_spec: dict, ctx: dict | None = None) -> list[dict]:
    ctx = ctx or system_context()
    g = snap["gpu"]["discrete"]
    if not ctx.get("gpu_model"):
        ctx["gpu_model"] = (g.get("thermal_profile") or {}).get("model") or ""
    mem = snap["memory"]
    bw = snap.get("bandwidth", {})
    dram = bw.get("memory", {})
    cpu = snap["cpu"]
    hints: list[dict] = []
    gt = snap.get("game_totals") or {}
    gctx = active_game_context(gt)
    gname = gctx.get("name") or "your game"
    gk = _game_kwargs(snap)

    active_appid = gctx.get("appid")
    if active_appid and gt.get("running"):
        health = steam_install_health(active_appid)
        pending_mb = health.get("pending_download_bytes", 0) / 1024**2
        if health.get("files_corrupt") or pending_mb > 50:
            detail_parts = []
            if health.get("files_corrupt"):
                detail_parts.append("Steam flagged the install as corrupt")
            if pending_mb > 50:
                detail_parts.append(f"{pending_mb:.0f} MB patch still pending")
            if health.get("update_suspended_while_running"):
                detail_parts.append("the update paused because the game launched early")
            hints.append(_hint(
                "hot" if health.get("files_corrupt") else "warn",
                f"{gname}: verify game files",
                " · ".join(detail_parts).capitalize()
                + " — common on Linux after updates; causes crashes, glitches, or failed loads.",
                [
                    _cmd(
                        "Verify in Steam (quit game first)",
                        f"xdg-open 'steam://validate/{active_appid}'",
                        note="Steam → Properties → Installed Files → Verify integrity",
                        kind="steam",
                    ),
                    _cmd(
                        "Let pending update finish",
                        "Exit the game and wait for Steam downloads to complete before relaunching",
                        kind="game",
                    ),
                ],
                insight_id="game-files-corrupt",
                fix_script=script_steam_verify_files(
                    active_appid,
                    gname,
                    pending_mb=pending_mb,
                    files_corrupt=health.get("files_corrupt", False),
                ),
                games=[active_appid],
            ))

    gov = ctx.get("governor")
    swap = ctx.get("swappiness")
    if gov == "powersave":
        hints.append(_hint(
            "warn",
            "CPU stuck in power-save mode",
            f"Governor is '{gov}' — cores may not boost fast enough while gaming. Switch to performance for game sessions.",
            [
                _cmd("Set performance governor (until reboot)", "echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"),
                _cmd("Check available governors", "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"),
                _cmd("Steam launch: add GameMode", "gamemoderun PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%", kind="steam", note="Steam → game → Properties → Launch Options"),
            ],
            insight_id="cpu-governor-powersave",
            fix_script=script_governor(),
        ))

    if swap is not None and swap > 60:
        hints.append(_hint(
            "warn",
            "Swappiness too high for gaming",
            f"vm.swappiness={swap} — the kernel swaps aggressively when RAM fills up, which causes hitches in any game.",
            [
                _cmd("Lower swappiness for this boot", "sudo sysctl vm.swappiness=10"),
                _cmd("Persist lower swappiness", "echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-gaming.conf && sudo sysctl --system"),
                _cmd("Check current value", "cat /proc/sys/vm/swappiness"),
                _cmd("See what is using RAM", "ps aux --sort=-%mem | head -20"),
            ],
            insight_id="vm-swappiness-high",
            fix_script=script_swappiness(swap),
        ))

    spd = mem_spec.get("spd_mts") or 4800
    cfg = mem_spec.get("configured_mts") or mem_spec.get("speed_mts") or 6000
    if mem_spec.get("source") != "dmidecode" and cfg >= 6000 and "6000" in mem_spec.get("part", ""):
        hints.append(_hint(
            "info",
            "Check EXPO is on in BIOS",
            f"Your {mem_spec.get('part')} kit needs AMD EXPO for {cfg} MT/s. Without it you get {spd} MT/s (~{spd * 2 * 64 / 8 / 1000:.1f} GB/s instead of 96 GB/s).",
            [
                _cmd("Read configured RAM speed", "sudo dmidecode -t memory | grep -E 'Speed|Configured|Part Number'"),
                _cmd("Re-probe dashboard RAM cache", f"sudo python3 '{PROBE_SCRIPT}'"),
            ],
            insight_id="ram-expo-verify",
            fix_script=script_expo_verify(),
        ))

    thermal_profile = g.get("thermal_profile") or profile_for_model(ctx.get("gpu_model", ""))
    _append_gpu_thermal_hints(hints, g, thermal_profile, ctx)

    if (g.get("mem_busy_pct") or 0) >= 65:
        est = g.get("vram_est_gbps", "?")
        hints.append(_hint(
            "info",
            "VRAM bus is busy",
            f"Memory controller at {g['mem_busy_pct']}% (~{est} GB/s). Textures are pushing the GDDR6 hard.",
            [
                _cmd("In-game: reduce texture / asset quality", f"{gname} → graphics → lower texture and asset quality", kind="game"),
                *([_open_game_action(gctx)] if _open_game_action(gctx) else []),
            ],
            insight_id="gpu-vram-bandwidth",
            fix_script=script_vram_bandwidth(g["mem_busy_pct"], str(est), **gk),
        ))

    if (g.get("vram_pct") or 0) >= 80:
        hints.append(_hint(
            "warn",
            "Running low on VRAM",
            f"{g['vram_pct']}% VRAM used ({g.get('vram_used_mb')} MB). Spilling into system RAM causes stutters.",
            [
                _cmd("In-game: lower resolution scale", f"{gname} → graphics → resolution scale 85–90%", kind="game"),
                _cmd("In-game: reduce texture quality", f"{gname} → graphics → medium textures", kind="game"),
                *([_open_game_action(gctx)] if _open_game_action(gctx) else []),
            ],
            insight_id="gpu-vram-full",
            fix_script=script_vram_low(g["vram_pct"], g.get("vram_used_mb") or 0, **gk),
        ))

    gtt = g.get("gtt") or {}
    if (gtt.get("rate_mbps") or 0) > 50:
        hints.append(_hint(
            "info",
            "GPU using system RAM",
            f"Shared memory traffic at {gtt['rate_mbps']} MB/s. Keep VRAM under ~80% to avoid this.",
            [
                _cmd("In-game: drop texture / asset mods", f"{gname} → disable high-res asset or texture mods", kind="game"),
                _cmd(
                    "Check VRAM use",
                    f"cat {_gpu_cmd_paths(ctx)['sysfs']}/mem_info_vram_used "
                    f"{_gpu_cmd_paths(ctx)['sysfs']}/mem_info_vram_total",
                ),
            ],
            insight_id="gpu-gtt-churn",
            fix_script=script_gtt(gtt["rate_mbps"], **gk),
        ))

    if (dram.get("swap_out_kbps") or 0) > 50 or mem.get("swap_pct", 0) > 25:
        hints.append(_hint(
            "warn",
            "Swap thrash — fix memory first",
            "The system is pushing data to swap. This is a common stutter cause — free RAM before tuning graphics.",
            [
                _cmd("Lower swappiness now", "sudo sysctl vm.swappiness=10"),
                _cmd("Close memory hogs", "ps aux --sort=-%mem | head -15"),
                _cmd("Drop caches (safe)", "sync && sudo sysctl vm.drop_caches=3", note="Frees page cache; game may stutter briefly"),
                _cmd("Reboot before long gaming session", "sudo reboot", note="Clears fragmented swap state"),
            ],
            insight_id="memory-swap-thrash",
            fix_script=script_swap_thrash(mem.get("swap_pct", 0)),
        ))

    if (dram.get("psi_avg10") or 0) > 8:
        hints.append(_hint(
            "warn",
            "RAM is the bottleneck",
            f"Memory stall at {dram['psi_avg10']}% — the CPU is waiting on RAM. Close background apps.",
            [
                _cmd("List top memory users", "ps aux --sort=-%mem | head -20"),
                _cmd("Close Brave — copy & run", "flatpak kill com.brave.Browser", note="You run this; Pulse never does"),
                _cmd("Close Firefox — copy & run", "pkill -x firefox", note="You run this; Pulse never does"),
                _cmd("Close Discord — copy & run", "pkill -x discord", note="You run this; Pulse never does"),
                _cmd("Disable unnecessary autostart", "systemctl --user list-unit-files --state=enabled | head -30", kind="cmd"),
            ],
            insight_id="memory-dram-stall",
            fix_script=script_dram_stall(dram["psi_avg10"]),
        ))

    if (dram.get("pgmajfault_per_s") or 0) > 20:
        hints.append(_hint(
            "warn",
            "Loading from disk/swap",
            f"{dram['pgmajfault_per_s']}/s major page faults — data is being pulled from slow storage.",
            [
                _cmd("Wait for load to finish", "Avoid camera panning / unpause until loading completes", kind="game"),
                _cmd("Preload: pause 30s after load", "Let the game settle before unpausing large saves", kind="game"),
            ],
            insight_id="memory-page-faults",
            fix_script=script_page_faults(dram["pgmajfault_per_s"], **gk),
        ))

    st = snap.get("stutter") or {}
    sess = st.get("session") or {}
    if gt.get("running") and (
        st.get("event")
        or st.get("score", 0) >= 42
        or sess.get("events", 0) >= 3
    ):
        causes = st.get("causes") or []
        cause_txt = ", ".join(st.get("cause_labels", {}).get(c, c) for c in causes) or "memory pressure"
        sev = st.get("severity") or "mild"
        level = "warn" if sev in ("moderate", "severe") else "info"
        hints.append(_hint(
            level,
            "Hitching detected (stutter proxy)",
            (
                f"~{st.get('est_ms', 0)}ms est. hitch · score {st.get('score', 0)}/100 · "
                f"{sess.get('events', 0)} events in 5m · 1% low proxy ~{sess.get('hitch_ms_1pct', 0)}ms. "
                f"Likely: {cause_txt}."
            ),
            [
                _cmd("List memory hogs", "ps aux --sort=-%mem | head -20"),
                _cmd("Close Brave — copy & run", "flatpak kill com.brave.Browser", note="You run this; Pulse never does"),
                _cmd("Lower swappiness — copy & run", "sudo sysctl vm.swappiness=10", note="Needs sudo; Pulse never does"),
                _cmd("Let load finish", "Stay paused 30s after save load before unpausing", kind="game"),
                _cmd("Lower sim / world detail", f"{gname} → reduce simulation speed or world detail if available", kind="game"),
            ],
            insight_id="stutter-proxy",
            fix_script=script_stutter(
                st.get("score", 0),
                st.get("est_ms", 0),
                [st.get("cause_labels", {}).get(c, c) for c in causes],
                **gk,
            ),
            games=[gt["game_id"]] if gt.get("game_id") else None,
        ))

    busy, mem_busy = g.get("busy_pct") or 0, g.get("mem_busy_pct") or 0
    if busy < 70 and cpu.get("overall_pct", 0) > 75:
        hints.append(_hint(
            "info",
            "CPU is the limit",
            f"GPU has headroom but the CPU is maxed — common in CPU-heavy scenes in {gname}.",
            [
                _cmd("In-game: lower simulation load", f"{gname} → reduce simulation speed, crowd, or AI detail", kind="game"),
                _cmd("Set performance governor", "echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"),
                _cmd("Close background CPU users", "ps aux --sort=-%cpu | head -15"),
            ],
            insight_id="cpu-bound",
            fix_script=script_cpu_bound(**gk),
        ))
    elif busy >= 85 and mem_busy < 50:
        hints.append(_hint(
            "info",
            "GPU shaders maxed out",
            "GPU compute is high but VRAM bus is fine — lower resolution helps more than textures.",
            [
                _cmd("In-game: raise resolution before textures", f"{gname} → raise resolution scale if thermals allow; avoid max texture packs", kind="game"),
            ],
            insight_id="gpu-shader-bound",
            fix_script=script_gpu_shader(**gk),
        ))

    ccds = cpu.get("temps", {}).get("ccd") or []
    if len(ccds) >= 2 and ccds[0] and ccds[1] and abs(ccds[0] - ccds[1]) >= 8:
        hints.append(_hint(
            "info",
            "Uneven CPU die temps",
            f"CCD1 {ccds[0]}°C vs CCD2 {ccds[1]}°C — normal on multi-CCD Ryzen, nothing to fix.",
            [
                _cmd("Optional: prefer one CCD (advanced)", "sudo apt install -y linux-tools-common && sudo turbostat --show Core,CPU,Busy,MHz -- interval 5", note="Observe which cores stay hot; manual affinity rarely needed"),
            ],
            insight_id="cpu-ccd-spread",
            fix_script=script_ccd_spread(ccds[0], ccds[1]),
        ))

    if not hints:
        hints.append(_hint(
            "ok",
            "Looking good",
            "No major issues right now. Check again when game load or mods increase.",
            [
                *([_open_game_action(gctx)] if _open_game_action(gctx) else []),
                _cmd("Steam launch options (keep Wayland fix)", "PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%", kind="steam", note="Steam → game → Properties → Launch Options"),
            ],
            insight_id="system-balanced",
            fix_script=script_balanced(**gk),
        ))

    return hints