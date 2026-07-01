# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Issue-specific tuning actions with copy-paste commands."""

from __future__ import annotations

import shutil
from pathlib import Path

from apply_fix import fix_available, requires_root
from fix_scripts import (
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
    script_stutter,
    script_vram_low,
)

HOME = Path.home()
PULSE_ROOT = Path(__file__).resolve().parent
PROBE_SCRIPT = PULSE_ROOT / "probe_memory.py"
CS2_DIR = (
    HOME
    / ".local/share/Steam/steamapps/compatdata/949230/pfx/drive_c/users/steamuser/AppData/LocalLow/Colossal Order/Cities Skylines II"
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
    mem = snap["memory"]
    bw = snap.get("bandwidth", {})
    dram = bw.get("memory", {})
    cpu = snap["cpu"]
    hints: list[dict] = []

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
                _cmd("Steam launch: add GameMode", "gamemoderun PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%", kind="steam", note="Steam → Cities 2 → Properties → Launch Options — replaces current line"),
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

    if g.get("junction_c") is not None and g["junction_c"] >= 100:
        gpu_cool_actions = [
            _cmd("Open CS2 settings folder", f"xdg-open '{CS2_DIR}'", note="Graphics live in-game; Settings.coc is binary"),
            _cmd("In-game: lower shadow / LOD / draw distance", "Cities 2 → Options → Graphics → lower Level of Detail, Shadow quality, and enable FPS cap 60–90", kind="game"),
        ]
        if shutil.which("corectrl"):
            gpu_cool_actions.append(
                _cmd("Open CoreCtrl", "corectrl", note="Fan curve, power limit, and per-app profiles"),
            )
        else:
            gpu_cool_actions.append(
                _cmd("Raise GPU fan (amdgpu)", "echo manual | sudo tee /sys/class/drm/card1/device/pp_power_profile_mode 2>/dev/null; echo 1 | sudo tee /sys/class/drm/card1/device/hwmon/hwmon*/pwm1_enable 2>/dev/null", note="Or install CoreCtrl: sudo apt install corectrl"),
            )
        hints.append(_hint(
            "hot",
            "GPU overheating",
            f"Junction is {g['junction_c']}°C. Above ~110°C the RX 7900 XT throttles — lower graphics settings or improve cooling.",
            gpu_cool_actions,
            insight_id="gpu-thermal-ceiling",
            fix_script=script_gpu_thermal(g["junction_c"]),
        ))
    elif g.get("junction_c") is not None and g["junction_c"] >= 90:
        gpu_warm_actions = [
            _cmd("Cap FPS in-game", "Cities 2 → Options → Graphics → Frame rate limit → 90", kind="game"),
            _cmd("Check GPU power cap", "cat /sys/class/drm/card1/device/hwmon/hwmon*/power1_cap 2>/dev/null; sensors amdgpu-pci-0300 | grep -i ppt"),
        ]
        if shutil.which("corectrl"):
            gpu_warm_actions.append(
                _cmd("Open CoreCtrl", "corectrl", note="Nudge fan curve before junction climbs further"),
            )
        hints.append(_hint(
            "warn",
            "GPU getting warm",
            f"Junction is {g['junction_c']}°C. Fine for now, but clocks may drop if it stays high.",
            gpu_warm_actions,
            insight_id="gpu-thermal-warm",
            fix_script=script_gpu_warm(g["junction_c"]),
        ))

    if (g.get("mem_busy_pct") or 0) >= 65:
        est = g.get("vram_est_gbps", "?")
        hints.append(_hint(
            "info",
            "VRAM bus is busy",
            f"Memory controller at {g['mem_busy_pct']}% (~{est} GB/s). Textures are pushing the GDDR6 hard.",
            [
                _cmd("In-game: reduce texture / asset quality", "Cities 2 → Options → Graphics → Texture quality ↓, Asset quality ↓", kind="game"),
                _cmd("Disable heavy mods temporarily", f"xdg-open '{CS2_DIR}/.cache/Mods'", note="Test without asset-replacement mods"),
            ],
            insight_id="gpu-vram-bandwidth",
            fix_script=script_vram_bandwidth(g["mem_busy_pct"], str(est)),
        ))

    if (g.get("vram_pct") or 0) >= 80:
        hints.append(_hint(
            "warn",
            "Running low on VRAM",
            f"{g['vram_pct']}% VRAM used ({g.get('vram_used_mb')} MB). Spilling into system RAM causes stutters.",
            [
                _cmd("In-game: lower resolution scale", "Cities 2 → Options → Graphics → Resolution scale → 85–90%", kind="game"),
                _cmd("In-game: reduce texture quality", "Cities 2 → Options → Graphics → Texture quality → Medium", kind="game"),
                _cmd("Open CS2 user data", f"xdg-open '{CS2_DIR}'"),
            ],
            insight_id="gpu-vram-full",
            fix_script=script_vram_low(g["vram_pct"], g.get("vram_used_mb") or 0),
        ))

    gtt = g.get("gtt") or {}
    if (gtt.get("rate_mbps") or 0) > 50:
        hints.append(_hint(
            "info",
            "GPU using system RAM",
            f"Shared memory traffic at {gtt['rate_mbps']} MB/s. Keep VRAM under ~80% to avoid this.",
            [
                _cmd("In-game: drop texture / asset mods", "Cities 2 → Content Manager → disable high-res asset mods", kind="game"),
                _cmd("Check VRAM use", "cat /sys/class/drm/card1/device/mem_info_vram_used /sys/class/drm/card1/device/mem_info_vram_total"),
            ],
            insight_id="gpu-gtt-churn",
            fix_script=script_gtt(gtt["rate_mbps"]),
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
                _cmd("Reboot before long city session", "sudo reboot", note="Clears fragmented swap state"),
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
                _cmd("Wait for city load to finish", "Avoid camera panning / unpause until loading bar completes", kind="game"),
                _cmd("Preload: sit on paused city 30s", "Let simulation settle before unpausing large saves", kind="game"),
            ],
            insight_id="memory-page-faults",
            fix_script=script_page_faults(dram["pgmajfault_per_s"]),
        ))

    st = snap.get("stutter") or {}
    sess = st.get("session") or {}
    gt = snap.get("game_totals") or {}
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
                _cmd("Cities: drop sim speed", "Cities 2 → reduce simulation speed on huge saves", kind="game"),
            ],
            insight_id="stutter-proxy",
            fix_script=script_stutter(
                st.get("score", 0),
                st.get("est_ms", 0),
                [st.get("cause_labels", {}).get(c, c) for c in causes],
            ),
            games=[gt["game_id"]] if gt.get("game_id") else None,
        ))

    busy, mem_busy = g.get("busy_pct") or 0, g.get("mem_busy_pct") or 0
    if busy < 70 and cpu.get("overall_pct", 0) > 75:
        hints.append(_hint(
            "info",
            "CPU is the limit",
            "GPU has headroom but the CPU is maxed — normal for big Cities 2 saves.",
            [
                _cmd("In-game: lower simulation load", "Cities 2 → Simulation speed 2×→1× on huge cities; reduce traffic/agents in mod settings", kind="game"),
                _cmd("Set performance governor", "echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"),
                _cmd("Close background CPU users", "ps aux --sort=-%cpu | head -15"),
            ],
            insight_id="cpu-bound",
            fix_script=script_cpu_bound(),
        ))
    elif busy >= 85 and mem_busy < 50:
        hints.append(_hint(
            "info",
            "GPU shaders maxed out",
            "GPU compute is high but VRAM bus is fine — lower resolution helps more than textures.",
            [
                _cmd("In-game: raise resolution before textures", "Cities 2 → Graphics → increase Resolution scale if headroom; avoid max texture packs", kind="game"),
            ],
            insight_id="gpu-shader-bound",
            fix_script=script_gpu_shader(),
        ))

    ccds = cpu.get("temps", {}).get("ccd") or []
    if len(ccds) >= 2 and ccds[0] and ccds[1] and abs(ccds[0] - ccds[1]) >= 8:
        hints.append(_hint(
            "info",
            "Uneven CPU die temps",
            f"CCD1 {ccds[0]}°C vs CCD2 {ccds[1]}°C — normal on Ryzen 7900X, nothing to fix.",
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
            "No major issues right now. Check again when the city grows or you add mods.",
            [
                _cmd("Open Cities 2 settings", f"xdg-open '{CS2_DIR}'"),
                _cmd("Steam launch options (keep Wayland fix)", "PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%", kind="steam", note="Steam → Cities 2 → Properties → Launch Options"),
            ],
            insight_id="system-balanced",
            fix_script=script_balanced(),
        ))

    return hints