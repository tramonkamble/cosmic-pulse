# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Per-issue fix scripts — one full bash script per recommendation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from games import WAYLAND_X11_LAUNCH_OPTS, game_data_paths, game_meta, steam_root
from hardware_profiles import FIX_TOOL_SPECS, iter_fix_tools
from paths import app_root

HOME = Path.home()
ROOT = app_root()
PROBE = ROOT / "probe_memory.py"


def _resolve_appid(**kwargs) -> str | None:
    appid = kwargs.get("appid") or kwargs.get("game_id")
    if appid is not None:
        return str(appid)
    return None


def _resolve_game_name(appid: str | None, game_name: str | None = None) -> str:
    if game_name:
        return game_name
    if appid:
        return game_meta(appid).get("name") or f"AppID {appid}"
    return "your game"


def _game_ctx(game_id: str | None = None, game_name: str | None = None, **kwargs) -> dict:
    appid = _resolve_appid(game_id=game_id, game_name=game_name, **kwargs)
    ctx = game_data_paths(appid)
    ctx["name"] = _resolve_game_name(appid, game_name or kwargs.get("game_name"))
    if appid:
        ctx["appid"] = appid
    return ctx


def _open_dir_cmd(ctx: dict, key: str = "open_dir") -> str:
    path = ctx.get(key)
    if path:
        return f"xdg-open '{path}' 2>/dev/null || true"
    return 'log "Game folder not found — change settings in-game"'


def _game_base(ctx: dict) -> Path | None:
    for key in ("userdata", "open_dir", "install", "compat"):
        path = ctx.get(key)
        if path and Path(path).is_dir():
            return Path(path)
    return None


def _open_subdir_cmd(ctx: dict, sub: str) -> str:
    base = _game_base(ctx)
    if not base:
        return 'log "Game folder not found — change settings in-game"'
    subpath = base / sub
    if subpath.is_dir():
        return f"xdg-open '{subpath}' 2>/dev/null || true"
    return f"xdg-open '{base}' 2>/dev/null || true"


def _gpu_sysfs() -> str:
    try:
        from hardware_probe import gpu_device_path

        return str(gpu_device_path())
    except Exception:
        return "/sys/class/drm/card1/device"


def _gpu_sensor_chip() -> str:
    try:
        from hardware_probe import gpu_sensor_prefix

        return f"amdgpu-pci-{gpu_sensor_prefix()}"
    except Exception:
        return "amdgpu-pci-0300"


def _fan_tool_hint(*, profile: dict | None = None) -> str:
    prof = profile or {}
    if not prof.get("fan_curve_helpful", True):
        arch = prof.get("label", "GPU")
        return f'log "{arch} rarely needs a fan curve — lower in-game settings if clocks drop"\n'
    chunks: list[str] = []
    for tool in iter_fix_tools(prof):
        spec = FIX_TOOL_SPECS.get(tool, {})
        label = spec.get("label", tool)
        binary = spec.get("binary", "")
        note = spec.get("note", "")
        if binary and shutil.which(binary):
            chunks.append(f'log "{label} is installed — adjust fan curve"\nlog "  {binary} &"\n')
        elif tool == "afterburner":
            chunks.append(
                f'log "{label} (Windows) or CoolerControl (Linux) for NVIDIA fan curves"\n'
                f'log "  {spec.get("install", "")}"\n'
            )
        else:
            chunks.append(
                f'log "Optional: {label} for fan curve GUI"\nlog "  {spec.get("install", "")}"\n'
            )
        if note:
            chunks.append(f'log "  ({note})"\n')
    vendor = prof.get("vendor")
    if vendor == "amd":
        sysfs = _gpu_sysfs()
        chunks.append(
            f'log "CLI fallback (AMD): manual fan via amdgpu sysfs"\n'
            f'log "  echo manual | sudo tee {sysfs}/pp_power_profile_mode"\n'
            f'log "  echo 1 | sudo tee {sysfs}/hwmon/hwmon*/pwm1_enable"\n'
        )
    return "".join(chunks)


def _gpu_telemetry_block(*, profile: dict | None = None) -> str:
    prof = profile or {}
    vendor = prof.get("vendor")
    if vendor == "nvidia":
        return """log "=== GPU telemetry ==="
nvidia-smi --query-gpu=temperature.gpu,clocks.gr,power.draw,fan.speed,utilization.gpu --format=csv 2>/dev/null || true
"""
    sensor = _gpu_sensor_chip()
    sysfs = _gpu_sysfs()
    return f"""log "=== GPU telemetry ==="
sensors {sensor} 2>/dev/null | grep -E 'edge|junction|mem|fan|PPT' || true
cat {sysfs}/gpu_busy_percent 2>/dev/null && echo "% GPU busy" || true
"""


def fan_tool_actions(profile: dict, sysfs: str) -> list[dict]:
    """UI action rows for thermal hints — profile picks CoreCtrl vs CoolerControl vs sysfs."""
    prof = profile or {}
    actions: list[dict] = []
    if not prof.get("fan_curve_helpful", True):
        return actions
    launched = False
    for tool in iter_fix_tools(prof):
        spec = FIX_TOOL_SPECS.get(tool, {})
        binary = spec.get("binary", "")
        label = spec.get("label", tool)
        if binary and shutil.which(binary):
            actions.append(
                {
                    "label": f"Open {label}",
                    "kind": "cmd",
                    "cmd": binary,
                    "note": spec.get("note", ""),
                }
            )
            launched = True
            break
    if not launched and prof.get("vendor") == "amd":
        actions.append(
            {
                "label": "Raise GPU fan (amdgpu sysfs)",
                "kind": "cmd",
                "cmd": (
                    f"echo manual | sudo tee {sysfs}/pp_power_profile_mode 2>/dev/null; "
                    f"echo 1 | sudo tee {sysfs}/hwmon/hwmon*/pwm1_enable 2>/dev/null"
                ),
                "note": spec.get("install", "Or install CoreCtrl: sudo apt install corectrl")
                if (spec := FIX_TOOL_SPECS.get("corectrl"))
                else "Or install CoreCtrl: sudo apt install corectrl",
            }
        )
    elif not launched and prof.get("vendor") == "nvidia":
        actions.append(
            {
                "label": "Install CoolerControl (NVIDIA fan curves)",
                "kind": "cmd",
                "cmd": FIX_TOOL_SPECS["coolercontrol"]["install"],
                "note": FIX_TOOL_SPECS["coolercontrol"]["note"],
            }
        )
    return actions


def launch_fan_tool(profile: dict) -> str | None:
    """Launch the first installed fan tool for this GPU profile."""
    for tool in iter_fix_tools(profile or {}):
        spec = FIX_TOOL_SPECS.get(tool, {})
        binary = spec.get("binary", "")
        if binary and shutil.which(binary):
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return tool
    return None


def _header(insight_id: str, title: str, risk: str = "low") -> str:
    return f"""#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cosmic Pulse · {insight_id}
# {title}
# Risk: {risk} · Review before running · Generated for {HOME}
# Usage:  sudo bash fix.sh
#         — or —  chmod +x fix.sh && sudo ./fix.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [ -z "${{BASH_VERSION:-}}" ]; then
  echo "This script needs bash (not sh/dash). Re-run: sudo bash $0"
  exit 1
fi
set -euo pipefail

log() {{ printf '▸ %s\\n' "$*"; }}
need_root() {{
  if [[ ${{EUID:-$(id -u)}} -ne 0 ]]; then
    echo "This script needs root. Re-run: sudo bash $0"
    exit 1
  fi
}}
"""


def _header_user(insight_id: str, title: str, risk: str = "low") -> str:
    return f"""#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cosmic Pulse · {insight_id}
# {title}
# Risk: {risk} · Review before running · Generated for {HOME}
# Usage:  bash fix.sh   (no sudo — edits your Steam user config only)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [ -z "${{BASH_VERSION:-}}" ]; then
  echo "This script needs bash (not sh/dash). Re-run: bash $0"
  exit 1
fi
set -euo pipefail

log() {{ printf '▸ %s\\n' "$*"; }}
"""


def script_governor() -> str:
    return (
        _header(
            "cpu-governor-powersave", "Switch CPU governor to performance (gaming session)", "low"
        )
        + """
log "Current governor:"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor || true
log "Available:"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors || true

need_root
TARGET="${1:-performance}"
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo "$TARGET" > "$gov"
done

log "Governor now:"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
log "Done. Reverts on reboot."
log "Rollback: sudo bash -c 'echo powersave > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor' (repeat per core or use tee wildcard)"
"""
    )


def script_swappiness(current: int = 60, **kwargs) -> str:
    return (
        _header("vm-swappiness-high", f"Lower swappiness from {current} for gaming", "low")
        + f"""
TARGET="${{1:-10}}"
log "Current swappiness: $(cat /proc/sys/vm/swappiness)"

need_root
sysctl -w vm.swappiness="$TARGET"
CONF=/etc/sysctl.d/99-gaming-swappiness.conf
if [[ ! -f "$CONF" ]]; then
  echo "vm.swappiness=$TARGET" > "$CONF"
  log "Persisted → $CONF"
else
  log "$CONF already exists — edit manually if needed"
fi
sysctl --system 2>/dev/null | grep swappiness || true
log "Rollback: sudo sysctl vm.swappiness={current} && sudo rm -f $CONF"
"""
    )


def script_expo_verify(
    *,
    spd_mts: int = 4800,
    configured_mts: int = 6000,
    part: str = "",
    **kwargs,
) -> str:
    kit = part.strip() or "your memory kit"
    return (
        _header(
            "ram-expo-verify",
            f"Verify DDR{configured_mts} EXPO/XMP is active in firmware",
            "low",
        )
        + f"""
log "=== dmidecode memory speeds ==="
if command -v dmidecode >/dev/null; then
  need_root
  dmidecode -t memory | grep -E 'Size:|[Ss]peed|Locator|Part Number|Configured|Manufacturer' | grep -v 'No Module'
else
  echo "Install: sudo apt install dmidecode"
  exit 1
fi

log "=== Refresh dashboard RAM cache ==="
if [[ -f '{PROBE}' ]]; then
  python3 '{PROBE}' || sudo python3 '{PROBE}'
fi

log "Expected: Configured Memory Speed near {configured_mts} MT/s (SPD often {spd_mts})"
log "If Configured shows {spd_mts} instead of {configured_mts}:"
log "  1. Reboot → BIOS/UEFI"
log "  2. Enable EXPO/XMP profile for {kit}"
log "  3. Re-run this script"
"""
    )


def script_gpu_thermal(junction: float, *, profile: dict | None = None) -> str:
    prof = profile or {}
    arch = prof.get("label", "GPU")
    throttle = prof.get("throttle_c", 110)
    temp_key = prof.get("primary_temp", "junction")
    if prof.get("arch") == "rdna3":
        target_line = (
            f'log "RDNA3 runs {temp_key} near {throttle}°C by design — only worry if clocks drop"\n'
        )
    else:
        target_line = (
            f'log "Re-check {temp_key} on dashboard — target well below {throttle}°C sustained"\n'
        )
    fan_note = prof.get("fan_curve_note") or prof.get("design_note", "")
    fan_block = _fan_tool_hint(profile=prof)
    if fan_note:
        fan_block += f'log "Note: {fan_note}"\n'
    return (
        _header(
            "gpu-thermal-ceiling",
            f"Cool-down playbook ({arch}, {temp_key} was {junction}°C)",
            "medium",
        )
        + _gpu_telemetry_block(profile=prof)
        + """
log "=== In-game (manual) ==="
cat <<'PLAYBOOK'

  In your game's graphics settings:
    • Cap frame rate (60–90 FPS)
    • Lower shadow / LOD / draw distance
    • Reduce volumetrics, AA, or upscaling quality if thermals climb

PLAYBOOK

"""
        + fan_block
        + target_line
    )


def script_gpu_warm(junction: float, *, profile: dict | None = None) -> str:
    prof = profile or {}
    arch = prof.get("label", "GPU")
    body = script_gpu_thermal(junction, profile=profile)
    body = body.replace("gpu-thermal-ceiling", "gpu-thermal-warm").replace(
        "Cool-down playbook", f"Warm GPU playbook ({arch})"
    )
    if prof.get("fan_curve_note"):
        body += f'\nlog "Note: {prof["fan_curve_note"]}"\n'
    return body


def script_vram_bandwidth(
    pct: int,
    est: str,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    return (
        _header("gpu-vram-bandwidth", f"Reduce VRAM bandwidth load ({pct}% busy)", "low")
        + f"""
log "VRAM controller busy: {pct}% (~{est} GB/s est.)"
log "Opening game folders for {gname}..."
{_open_subdir_cmd(ctx, ".cache/Mods")}
sleep 1
{_open_dir_cmd(ctx)}
cat <<'PLAYBOOK'

  In {gname} → graphics settings:
    • Texture quality → Medium or lower
    • Asset / model quality → Medium or lower
  Disable heavy mods temporarily and retest.

PLAYBOOK
log "Monitor mem_busy% on dashboard — aim for under 50% in normal play"
"""
    )


def script_vram_low(
    pct: float,
    used: int,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    return (
        _header("gpu-vram-full", f"Free VRAM headroom ({pct}% used)", "low")
        + f"""
log "VRAM {pct}% used ({used} MB)"
{_open_dir_cmd(ctx)}
cat <<'PLAYBOOK'

  In {gname} → graphics settings:
    • Resolution scale → 85–90%
    • Texture quality → Medium
    • Disable high-res texture or asset mods

PLAYBOOK
"""
    )


def script_gtt(
    rate: float,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    return (
        _header("gpu-gtt-churn", f"Reduce shared GPU memory traffic ({rate} MB/s GTT)", "low")
        + f"""
log "GTT churn: {rate} MB/s"
cat {_gpu_sysfs()}/mem_info_gtt_used {_gpu_sysfs()}/mem_info_gtt_total 2>/dev/null || true
{_open_subdir_cmd(ctx, ".cache/Mods")}
cat <<'PLAYBOOK'

  Keep VRAM under 80% — lower textures/resolution before adding mods.

PLAYBOOK
"""
    )


def script_swap_thrash(swap_pct: float) -> str:
    return (
        _header("memory-swap-thrash", f"Stop swap thrash (swap {swap_pct}% used)", "medium")
        + """
log "=== Memory before ==="
free -h
log "swappiness: $(cat /proc/sys/vm/swappiness)"
log "Top memory consumers:"
ps aux --sort=-%mem | head -15

need_root
sysctl -w vm.swappiness=10
CONF=/etc/sysctl.d/99-gaming-swappiness.conf
echo 'vm.swappiness=10' > "$CONF"

log "Optional: drop page cache (brief stutter)"
read -r -p "Drop caches now? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
  sync
  sysctl -w vm.drop_caches=3
fi

log "=== Memory after ==="
free -h
log "Close browsers/Discord before gaming. Reboot if swap stays high."
log "Rollback swappiness: sudo sysctl vm.swappiness=180"
"""
    )


def script_dram_stall(psi: float) -> str:
    return (
        _header("memory-dram-stall", f"Reduce DRAM stall pressure (PSI {psi}%)", "medium")
        + """
log "=== Top memory ==="
ps aux --sort=-%mem | head -20
log "=== Top CPU ==="
ps aux --sort=-%cpu | head -10

cat <<'PLAYBOOK'

  Close or suspend:
    • Browsers (Firefox/Brave — hundreds of MB each)
    • Discord overlay
    • Extra game launchers if not needed
  Then re-check PSI Memory on dashboard (aim under 5%).

PLAYBOOK

log "Optional — copy and run yourself (Pulse never executes these):"
log "  flatpak kill com.brave.Browser"
log "  pkill -x firefox"
log "  pkill -x discord"
"""
    )


def script_stutter(
    score: float,
    est_ms: float,
    causes: list[str],
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    cause_txt = ", ".join(causes) if causes else "memory pressure"
    gname = _game_ctx(game_id, game_name, **kwargs)["name"]
    return (
        _header(
            "stutter-proxy",
            f"Reduce hitches (score {score}, ~{est_ms}ms est.)",
            "low",
        )
        + f"""
log "Cosmic Pulse stutter proxy — likely causes: {cause_txt}"
log "=== Memory / swap ==="
free -h
cat /proc/sys/vm/swappiness
log "=== Top memory ==="
ps aux --sort=-%mem | head -15

cat <<'PLAYBOOK'

  Hitch playbook (no true frametime — system-level proxy):
    1. Close browsers, Discord, extra launchers
    2. Let {gname} finish loading before unpausing / big camera moves
    3. If swap is active: sudo sysctl vm.swappiness=10
    4. Lower simulation speed or world detail if the game allows it
    5. Reboot if swap stayed high from a prior session

  Re-check Cosmic Pulse → Stutter panel (aim score under 30, 1% proxy under 25ms).

PLAYBOOK

read -r -p "Lower swappiness to 10 now? [y/N] " ans
if [[ "${{ans,,}}" == "y" ]]; then
  need_root
  sysctl -w vm.swappiness=10
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-gaming-swappiness.conf
fi
"""
    )


def script_page_faults(
    rate: int,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    return (
        _header("memory-page-faults", f"Reduce major page faults ({rate}/s)", "low")
        + f"""
log "Major faults indicate disk/swap backed loads."
cat <<'PLAYBOOK'

  {gname} playbook:
    1. Load save → wait until loading completes
    2. Stay paused 30s after load before unpausing
    3. Avoid alt-tab during initial catch-up
    4. If faults persist: lower detail mods / reboot before session

PLAYBOOK
log "Opening save folder..."
{_open_subdir_cmd(ctx, "Saves")}
"""
    )


def script_cpu_bound(
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    gname = _game_ctx(game_id, game_name, **kwargs)["name"]
    return (
        _header("cpu-bound", "CPU-bound — boost clocks and trim background load", "low")
        + f"""
log "=== CPU ==="
grep . /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
ps aux --sort=-%cpu | head -15

need_root
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo performance > "$g"
done

cat <<'PLAYBOOK'

  {gname} (in-game):
    • Lower simulation / crowd / AI detail if available
    • Reduce background mods or overlays
    • Cap frame rate to ease CPU load

PLAYBOOK
log "Governor set to performance"
"""
    )


def script_resolution_swap_stutter(
    swap_pct: float,
    stutter_score: float,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    return (
        _header("resolution-swap-stutter", "Free RAM before tuning graphics", "low")
        + f"""
cat <<'PLAYBOOK'

  Swap is {swap_pct:.0f}% and stutter proxy is {stutter_score:.0f}/100 while {gname} runs.
  This is not full swap thrash yet — closing memory hogs often fixes hitches before you change game settings.

  Quick wins:
    • Close browser tabs and other heavy apps
    • Check top RAM users: ps aux --sort=-%mem | head -15
    • Optional (needs sudo): sudo sysctl vm.swappiness=10

PLAYBOOK
{_open_dir_cmd(ctx)}
"""
    )


def script_resolution_load_settle(
    fault_rate: int,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    return script_page_faults(fault_rate, game_id=game_id, game_name=game_name, **kwargs)


def script_resolution_cpu_perf(
    cpu_pct: float,
    governor: str,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    gname = _game_ctx(game_id, game_name, **kwargs)["name"]
    return (
        _header("resolution-cpu-perf", "CPU-bound — switch off power-save governor", "low")
        + f"""
cat <<'PLAYBOOK'

  {gname} is CPU-limited ({cpu_pct:.0f}% game CPU) while the governor is "{governor}".
  Cores may not boost fast enough for simulation-heavy scenes.

  Until reboot (needs sudo):
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

  If on Wayland and mouse/camera acts up, see Guidance:
    Proton on Wayland — X11 override (per-game launch options).

PLAYBOOK
"""
    )


def script_gpu_fps_cap(
    busy_pct: float = 95,
    refresh_hz: int = 60,
    junction_c: float | None = None,
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    temp = f" Junction was {junction_c}°C." if junction_c else ""
    return (
        _header("gpu-fps-cap", f"Cap FPS to {refresh_hz} Hz display", "low")
        + f"""
cat <<'PLAYBOOK'

  GPU was ~{busy_pct:.0f}% busy on a {refresh_hz} Hz display.{temp}
  Rendering far above {refresh_hz} FPS wastes GPU time and heat — you cannot see those frames.

  {gname} → Options → Graphics:
    • Frame rate limit → {refresh_hz}
    • Keep VSync off if you prefer; the in-game cap is enough

  After capping, watch Pulse:
    • GPU busy% should drop (often 75–90% instead of 98–100%)
    • Junction temp should ease over a few minutes
    • Stutter proxy should improve if swap is not the main issue

PLAYBOOK
{_open_dir_cmd(ctx)}
"""
    )


def script_gpu_shader(
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    return (
        _header("gpu-shader-bound", "GPU shader bound — favor resolution over textures", "low")
        + f"""
cat <<'PLAYBOOK'

  You are GPU compute bound (not VRAM bandwidth bound).
  {gname} → graphics settings:
    • OK to raise resolution scale if thermals allow
    • Avoid max texture / asset packs
    • Watch junction temp on dashboard

PLAYBOOK
{_open_dir_cmd(ctx)}
"""
    )


def script_ccd_spread(t1: float = 0, t2: float = 0, *, cpu_model: str = "", **kwargs) -> str:
    cpu_note = cpu_model.strip() or "multi-CCD Ryzen CPUs"
    return (
        _header("cpu-ccd-spread", f"CCD thermal spread {t1}°C vs {t2}°C", "low")
        + f"""
log "Normal on {cpu_note} — game threads often favor one CCD."
sensors k10temp-pci-00c3 2>/dev/null | grep -i tccd || true
log "Optional monitoring (5s sample, Ctrl+C to stop):"
if command -v turbostat >/dev/null; then
  turbostat --show Core,CPU,Busy,MHz -- interval 5
else
  log "Install: sudo apt install linux-tools-common linux-tools-$(uname -r)"
fi
"""
    )


def script_steam_verify_files(
    *,
    appid: str | None = None,
    game_name: str | None = None,
    files_corrupt: bool = True,
    **kwargs,
) -> str:
    appid = _resolve_appid(appid=appid, **kwargs)
    game_name = _resolve_game_name(appid, game_name or kwargs.get("game_name"))
    steam = steam_root()
    steam_bin = shutil.which("steam") or str(steam / "ubuntu12_32/steam")
    why = "files flagged corrupt" if files_corrupt else "install health check"
    return (
        _header("game-files-corrupt", f"{game_name} — verify install ({why})", "medium")
        + f"""
log "Common Linux fix after Steam patches — not rig-specific."
log "Steam reported: {why}"
log ""
log "1) Quit {game_name} completely (exit to desktop, not just main menu)"
log "2) Verify game files (opens Steam)"
if [[ -n "{appid or ""}" ]]; then
  xdg-open "steam://validate/{appid}" 2>/dev/null || "{steam_bin}" "steam://validate/{appid}" &
  sleep 2
else
  log "No active AppID — Steam → game → Properties → Installed Files → Verify"
fi
log "3) Let Steam finish any downloads before relaunching"
log ""
log "If problems persist after verify:"
log "  • Steam → {game_name} → Properties → disable overlays temporarily"
log "  • Check Pulse Guidance for pending-update or shader-cache hints"
log "  • Check Pulse Guidance for GPU reset warnings (AMD mode1 reset)"
"""
    )


def script_steam_update_shader(
    *,
    appid: str | None = None,
    game_name: str | None = None,
    pending_mb: float = 0,
    stage_mb: float = 0,
    suspended: bool = False,
    shader_mb: float = 0,
    **kwargs,
) -> str:
    appid = _resolve_appid(appid=appid, **kwargs)
    game_name = _resolve_game_name(appid, game_name or kwargs.get("game_name"))
    steam = steam_root()
    steam_bin = shutil.which("steam") or str(steam / "ubuntu12_32/steam")
    if not appid:
        return (
            _header("game-update-pending", f"{game_name} — finish pending update", "medium")
            + f"""
log "No active AppID — use Steam manually:"
log "  1) Exit {game_name} to desktop"
log "  2) Steam → Downloads — let any patch finish"
xdg-open "steam://open/downloads" 2>/dev/null || "{steam_bin}" "steam://open/downloads" &
sleep 2
log "  3) Relaunch after download completes"
log "To clear shader cache: Steam → game → Properties → clear shader cache, or delete:"
log "  {steam}/steamapps/shadercache/<AppID>/fozpipelinesv6/"
"""
        )
    shader_cache = steam / "steamapps/shadercache" / str(appid)
    reason = []
    if suspended:
        reason.append("update suspended while game was running")
    if pending_mb > 0:
        reason.append(f"{pending_mb:.0f} MB download pending")
    if stage_mb > 0:
        reason.append(f"{stage_mb:.0f} MB still staging")
    why = " · ".join(reason) or "pending Steam update"
    shader_note = f" ({shader_mb:.0f} MB cached)" if shader_mb > 0 else ""
    return (
        _header("game-update-pending", f"{game_name} — finish update ({why})", "medium")
        + f"""
log "Steam update / shader cache playbook — common on Linux when a patch drops mid-session."
log "Steam reported: {why}"
log ""
log "1) Exit {game_name} to desktop (do not relaunch yet)"
log "2) Open Steam Downloads and let the patch finish"
xdg-open "steam://open/downloads" 2>/dev/null || "{steam_bin}" "steam://open/downloads" &
sleep 2
log "3) Wait until download + install complete (no progress bar on the game)"
log "4) Relaunch — first load may hitch while shaders rebuild"
log ""
log "Shader cache for {game_name}{shader_note}: {shader_cache}"
read -r -p "Clear shader cache before relaunch? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  rm -rf "{shader_cache}/fozpipelinesv6"/* 2>/dev/null || true
  rm -rf "{shader_cache}/nvidiav1"/* 2>/dev/null || true
  log "Shader cache cleared — expect extra hitching on first launch"
else
  log "Skipped shader cache clear"
fi
log ""
log "If hitching persists after a clean update:"
log "  • Lower shader / texture quality for one session"
log "  • Pulse Guidance → verify game files if crashes or missing assets appear"
"""
    )


def script_game_libs_missing(
    lib_findings: list | None = None,
    *,
    multilib: bool = False,
    apt_packages: str = "",
    **kwargs,
) -> str:
    pkgs: list[str] = []
    if apt_packages:
        pkgs.extend(apt_packages.split())
    multilib = multilib or bool(kwargs.get("lib_multilib_needed"))
    for f in lib_findings or []:
        fix = (f.get("fix") if isinstance(f, dict) else "") or ""
        if "add-architecture i386" in fix:
            multilib = True
            pkgs.extend(["libgl1:i386", "libvulkan1:i386", "libldap2:i386"])
        elif fix.startswith("sudo apt install "):
            pkgs.extend(fix.replace("sudo apt install ", "").split())
    pkgs = list(dict.fromkeys(pkgs))
    body = ""
    if multilib:
        body += """
log "Step 1 — enable 32-bit packages (one-time on Pop!_OS / Ubuntu)"
sudo dpkg --add-architecture i386
sudo apt update
"""
    if pkgs:
        body += f"""
log "Step 2 — install missing gaming libraries"
sudo apt install {" ".join(pkgs)}
"""
    else:
        body += """
log "Install common Steam / Proton dependencies:"
sudo apt install libvulkan1 mesa-vulkan-drivers libgl1 libgamemode0 libldap2 libgpg-error0
"""
    return (
        _header("game-libs-missing", "Missing gaming libraries", "medium")
        + body
        + """
log "Step 3 — verify Vulkan"
vulkaninfo --summary 2>/dev/null | head -20 || log "Install: sudo apt install vulkan-tools"
log "Relaunch the game from Steam"
"""
    )


def script_steam_disk_low(free_gb: float = 10.0, **kwargs) -> str:
    steam = steam_root()
    return (
        _header("steam-disk-low", f"Low Steam disk space ({free_gb:.1f} GB free)", "medium")
        + f"""
log "Steam volume: {steam}"
log "Free space: ~{free_gb:.1f} GB — updates and Proton prefixes need headroom"
log ""
log "1) Steam → Settings → Storage — uninstall or move large games"
xdg-open "steam://open/settings" 2>/dev/null &
sleep 2
log "2) Review largest compatdata prefixes:"
du -sh "{steam}/steamapps/compatdata"/* 2>/dev/null | sort -hr | head -15 || true
log ""
log "3) Optional — clear old shader caches (rebuilds on next launch):"
du -sh "{steam}/steamapps/shadercache"/* 2>/dev/null | sort -hr | head -10 || true
read -r -p "Clear shadercache for one AppID folder name? (empty to skip): " sid
if [[ -n "$sid" && -d "{steam}/steamapps/shadercache/$sid" ]]; then
  rm -rf "{steam}/steamapps/shadercache/$sid/fozpipelinesv6"/* 2>/dev/null || true
  log "Cleared shader cache for $sid"
fi
log "Aim for at least 15–20 GB free before large patches"
"""
    )


def script_vulkan_broken(**kwargs) -> str:
    return (
        _header("vulkan-broken", "Vulkan not working", "high")
        + """
log "Games using Proton/DXVK need a working Vulkan stack"
log ""
log "1) Reinstall Mesa Vulkan drivers"
sudo apt install --reinstall libvulkan1 mesa-vulkan-drivers vulkan-tools
log "2) Test loader"
vulkaninfo --summary 2>&1 | head -40
log "3) If laptop/hybrid GPU, test discrete GPU:"
DRI_PRIME=1 vulkaninfo --summary 2>&1 | head -40
log "Reboot if drivers were upgraded"
"""
    )


def script_game_bad_exit(
    *,
    appid: str | None = None,
    game_name: str | None = None,
    codes: str = "[]",
    **kwargs,
) -> str:
    appid = _resolve_appid(appid=appid, **kwargs)
    game_name = _resolve_game_name(appid, game_name or kwargs.get("game_name"))
    steam = steam_root()
    compat = steam / "steamapps/compatdata" / str(appid or "")
    steam_bin = shutil.which("steam") or str(steam / "ubuntu12_32/steam")
    return (
        _header("game-prefix-reset", f"{game_name} — crash / bad exit ({codes})", "high")
        + f"""
log "Recent Steam exit codes: {codes}"
log "137 = killed · 139 = segfault · 127/126 = missing binary or library"
log ""
log "Try in order:"
log "1) Verify game files"
if [[ -n "{appid or ""}" ]]; then
  xdg-open "steam://validate/{appid}" 2>/dev/null || "{steam_bin}" "steam://validate/{appid}" &
  sleep 2
else
  log "No active AppID — verify from Steam Properties → Installed Files"
fi
log "2) Check Pulse Guidance → Missing gaming libraries"
log "3) Proton prefix backup + reset (last resort)"
log "   Prefix: {compat}"
if [[ -d "{compat}" ]]; then
  read -r -p "Backup and DELETE compatdata/{appid}? [y/N] " ans
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    bk="$HOME/pulse-compat-backup-{appid}-$(date +%Y%m%d%H%M)"
    cp -a "{compat}" "$bk"
    rm -rf "{compat}"
    log "Backed up to $bk and removed prefix — Steam will recreate on next launch"
  else
    log "Skipped prefix reset"
  fi
else
  log "No prefix yet — first launch will create compatdata/{appid}"
fi
log "4) Try Proton Experimental or another Proton build in Steam → Properties → Compatibility"
"""
    )


def script_mangohud_recommended(**kwargs) -> str:
    return (
        _header("mangohud-recommended", "Install MangoHud (optional)", "low")
        + """
log "MangoHud adds an in-game overlay and CSV frametime logs"
sudo apt install -y mangohud
log ""
log "Steam → game → Properties → Launch Options:"
echo 'mangohud %command%'
log ""
log "Optional logging in ~/.config/MangoHud/MangoHud.conf:"
echo 'output_folder=$HOME/mangohud-logs'
echo 'autostart_log=5'
log "Flatpak Steam may need: flatpak override --user --env=MANGOHUD=1 com.valvesoftware.Steam"
"""
    )


def script_enable_nvme_smart(**kwargs) -> str:
    """One-time setup so Pulse can read NVMe SMART without running as root."""
    return (
        _header(
            "enable-nvme-smart",
            "Allow Cosmic Pulse to read NVMe SMART (wear / spare / TBW)",
            "low",
        )
        + r"""
log "smartctl needs read access to /dev/nvmeN (char devices are root-only by default)."
log "This script adds you to the 'disk' group and installs a udev rule."
need_root

USER_NAME="${SUDO_USER:-$USER}"
if [[ -z "$USER_NAME" || "$USER_NAME" == root ]]; then
  echo "Run as: sudo -u <you> is wrong — use: sudo bash $0  (with your login as SUDO_USER)"
  echo "Or: sudo bash $0 $USER"
  USER_NAME="${1:-}"
fi
if [[ -z "$USER_NAME" || "$USER_NAME" == root ]]; then
  echo "Pass your username: sudo bash $0 tkep"
  exit 1
fi

log "Installing smartmontools if missing…"
command -v smartctl >/dev/null || apt-get install -y smartmontools

log "Adding $USER_NAME to group 'disk'…"
usermod -aG disk "$USER_NAME"

RULE=/etc/udev/rules.d/60-nvme-smart-pulse.rules
log "Writing $RULE"
cat >"$RULE" <<'EOF'
# Cosmic Pulse — allow disk group to read NVMe controller SMART
KERNEL=="nvme[0-9]*", GROUP="disk", MODE="0660"
EOF

log "Reloading udev rules…"
udevadm control --reload-rules
udevadm trigger --subsystem-match=nvme || true
# Also chmod currently open nodes so we don't need a full reboot for the rule
for n in /dev/nvme[0-9]*; do
  [[ -e "$n" ]] || continue
  chgrp disk "$n" 2>/dev/null || true
  chmod 0660 "$n" 2>/dev/null || true
done

log "Testing smartctl as $USER_NAME…"
if command -v runuser >/dev/null; then
  runuser -u "$USER_NAME" -- smartctl -a -j /dev/nvme0 2>/dev/null | head -c 200 && echo || true
else
  smartctl -a -j /dev/nvme0 2>/dev/null | head -c 120 || true
fi

log ""
log "Done. Log out and back in (or reboot) so group membership applies to new sessions."
log "Then restart Pulse: systemctl --user restart pulse.service"
log "Dashboard → Drives should show wear % and TB written when SMART is readable."
"""
    )


def script_display_hdr_off(**kwargs) -> str:
    """Diagnose HDR and print enable paths — no DRM property writes (compositor owns that)."""
    return (
        _header_user(
            "display-hdr-off",
            "HDR capable display is in SDR — how to enable",
            "low",
        )
        + r"""
log "Reading EDID + DRM connector HDR state…"
python3 - <<'PY'
from hardware_probe import primary_display_hdr
import json
h = primary_display_hdr(0)
print(json.dumps(h, indent=2))
if not h.get("capable"):
    print("\nThis connected display did not advertise HDR static metadata in EDID.")
elif h.get("active"):
    print("\nHDR appears active already (HDR_OUTPUT_METADATA or BT.2020 colorspace).")
else:
    print("\nHDR capable but OFF — desktop is still SDR.")
    print("COSMIC currently has no Settings/cosmic-randr HDR switch.")
    print("Pulse will not force DRM Colorspace/HDR_OUTPUT_METADATA (compositor owns the pipe).")
PY

log ""
log "1) Monitor OSD — enable HDR / HDR10 if the panel has that option"
log "2) Desktop — when COSMIC adds HDR, use Settings → Displays"
log "3) Per-game nested compositor (optional):"
if command -v gamescope >/dev/null 2>&1; then
  log "   gamescope is installed: $(command -v gamescope)"
else
  log "   Install: sudo apt install gamescope"
fi
log "   Steam launch options (HDR-capable titles only):"
echo 'gamescope --hdr-enabled --adaptive-sync -- %command%'
log ""
log "4) Re-check after changing anything:"
echo 'python3 -c "from hardware_probe import primary_display_hdr; print(primary_display_hdr(0))"'
log "Done. When DRM reports active=true, Guidance will clear this card."
"""
    )


def script_gamemode_recommended(**kwargs) -> str:
    return (
        _header("gamemode-recommended", "Install GameMode (optional)", "low")
        + """
log "GameMode requests lower latency while a game runs"
sudo apt install -y gamemode
log ""
log "Steam → game → Properties → Launch Options:"
echo 'gamemoderun %command%'
log ""
log "On Wayland, also see Guidance: Proton on Wayland — X11 override (per game)."
log ""
log "Ensure gamemoded is running:"
systemctl --user enable --now gamemoded 2>/dev/null || true
gamemoded -t 2>/dev/null || log "Start gamemoded after install if needed"
"""
    )


def script_proton_wayland_launch(
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    gname = ctx["name"]
    appid = ctx.get("appid") or game_id or ""
    opts = WAYLAND_X11_LAUNCH_OPTS
    pulse_root = ROOT
    return (
        _header_user(
            "proton-wayland-launch-fix",
            f"{gname} — apply Proton Wayland X11 launch override",
            "low",
        )
        + f"""
APPID="{appid}"
GNAME="{gname.replace('"', '\\"')}"
OPTS='{opts}'
PULSE_ROOT='{pulse_root}'

if [ -z "$APPID" ]; then
  log "No Steam AppID in script context."
  log "Re-download from Guidance while the game is active, or pass AppID manually:"
  log "  APPID=3041230 bash $0"
  exit 1
fi

log "Writing X11 launch options for $GNAME (AppID $APPID)"
log "  $OPTS"
log "Target: Steam userdata localconfig.vdf (backup → .bak.pulse)"

python3 <<'PY'
import sys
from pathlib import Path

appid = "{appid}"
pulse_root = Path("{pulse_root}")
sys.path.insert(0, str(pulse_root))

from games import WAYLAND_X11_LAUNCH_OPTS, set_steam_launch_options, steam_launch_options

result = set_steam_launch_options(appid, WAYLAND_X11_LAUNCH_OPTS)
msg = result.get("message") or str(result)
print(msg)
if result.get("path"):
    print("config:", result["path"])
if result.get("backup"):
    print("backup:", result["backup"])
verified = steam_launch_options(appid)
print("launch options now:", verified or "(empty)")
if not result.get("ok"):
    raise SystemExit(1)
if not verified or "SDL_VIDEODRIVER=x11" not in verified:
    raise SystemExit("verify failed — launch options not visible in Steam config")
PY

log "Done — quit $GNAME completely, then relaunch from Steam."
log "Optional GameMode prefix (manual): gamemoderun $OPTS"
"""
    )


def script_balanced(
    *,
    game_id: str | None = None,
    game_name: str | None = None,
    **kwargs,
) -> str:
    ctx = _game_ctx(game_id, game_name, **kwargs)
    return (
        _header("system-balanced", "System healthy — maintenance checklist", "low")
        + f"""
log "No critical insights. Maintenance:"
log "  • Wayland + Proton games: see Guidance per-game X11 override if mouse/camera acts up"
log "  • Optional GameMode:"
echo '    gamemoderun %command%'
{_open_dir_cmd(ctx)}
log "Dashboard: http://localhost:8765"
"""
    )


SCRIPTS: dict[str, callable] = {
    "cpu-governor-powersave": script_governor,
    "vm-swappiness-high": script_swappiness,
    "ram-expo-verify": script_expo_verify,
    "gpu-thermal-ceiling": lambda j=100: script_gpu_thermal(j),
    "gpu-thermal-warm": lambda j=90: script_gpu_warm(j),
    "gpu-vram-bandwidth": lambda: script_vram_bandwidth(65, "?"),
    "gpu-vram-full": lambda: script_vram_low(80, 0),
    "gpu-gtt-churn": lambda: script_gtt(50),
    "memory-swap-thrash": script_swap_thrash,
    "memory-dram-stall": script_dram_stall,
    "memory-page-faults": lambda: script_page_faults(20),
    "cpu-bound": script_cpu_bound,
    "gpu-shader-bound": script_gpu_shader,
    "gpu-fps-cap": script_gpu_fps_cap,
    "resolution-swap-stutter": script_resolution_swap_stutter,
    "resolution-load-settle": script_resolution_load_settle,
    "resolution-cpu-perf": script_resolution_cpu_perf,
    "cpu-ccd-spread": script_ccd_spread,
    "game-files-corrupt": script_steam_verify_files,
    "game-update-pending": script_steam_update_shader,
    "game-libs-missing": script_game_libs_missing,
    "steam-disk-low": script_steam_disk_low,
    "vulkan-broken": script_vulkan_broken,
    "game-prefix-reset": script_game_bad_exit,
    "mangohud-recommended": script_mangohud_recommended,
    "gamemode-recommended": script_gamemode_recommended,
    "display-hdr-off": script_display_hdr_off,
    "enable-nvme-smart": script_enable_nvme_smart,
    "proton-wayland-launch-fix": script_proton_wayland_launch,
    "stutter-proxy": lambda score=0, est_ms=0, causes=None, **kw: script_stutter(
        float(score),
        float(est_ms),
        [causes] if isinstance(causes, str) else (causes or []),
        **kw,
    ),
    "system-balanced": script_balanced,
}


def _normalize_script_kwargs(kwargs: dict) -> dict:
    out = dict(kwargs)
    if out.get("game_id") and not out.get("appid"):
        out["appid"] = out["game_id"]
    return out


def get_fix_script(insight_id: str, **kwargs) -> str:
    """Return fix script for an insight_id, with optional context kwargs."""
    fn = SCRIPTS.get(insight_id)
    if not fn:
        return ""
    norm = _normalize_script_kwargs(kwargs)
    try:
        return fn(**norm).strip()
    except TypeError:
        try:
            return fn().strip()
        except TypeError:
            return ""
