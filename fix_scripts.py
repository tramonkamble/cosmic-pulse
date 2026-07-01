# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Per-issue fix scripts — one full bash script per recommendation."""

from __future__ import annotations

import shutil
from pathlib import Path

HOME = Path.home()
CS2_DIR = (
    HOME
    / ".local/share/Steam/steamapps/compatdata/949230/pfx/drive_c/users/steamuser/AppData/LocalLow/Colossal Order/Cities Skylines II"
)
PROBE = HOME / "perf-dashboard/probe_memory.py"


def _corectrl_hint() -> str:
    if shutil.which("corectrl"):
        return """log "CoreCtrl is installed — raise fan speed or set a hotter fan curve"
log "  corectrl &"
"""
    return """log "Optional: install CoreCtrl for fan curve GUI"
log "  sudo apt install corectrl   (then run CoreCtrl)"
"""


def _header(insight_id: str, title: str, risk: str = "low") -> str:
    return f"""#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cosmic Pulse · {insight_id}
# {title}
# Risk: {risk} · Review before running · Generated for {HOME}
# Usage:  chmod +x fix.sh && sudo ./fix.sh
#         — or —  bash fix.sh        (if no sudo lines)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -euo pipefail

log() {{ printf '▸ %s\\n' "$*"; }}
need_root() {{
  if [[ ${{EUID:-$(id -u)}} -ne 0 ]]; then
    echo "This script needs root. Re-run: sudo bash $0"
    exit 1
  fi
}}
"""


def script_governor() -> str:
    return _header("cpu-governor-powersave", "Switch CPU governor to performance (gaming session)", "low") + """
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


def script_swappiness(current: int) -> str:
    return _header("vm-swappiness-high", f"Lower swappiness from {current} for gaming", "low") + f"""
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


def script_expo_verify() -> str:
    return _header("ram-expo-verify", "Verify DDR5-6000 EXPO is active in firmware", "low") + f"""
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

log "If Configured Memory Speed shows 4800 not 6000:"
log "  1. Reboot → BIOS/UEFI"
log "  2. Enable AMD EXPO profile for G.Skill F5-6000J3038F16G"
log "  3. Re-run this script"
"""


def script_gpu_thermal(junction: float, *, profile: dict | None = None) -> str:
    prof = profile or {}
    arch = prof.get("label", "GPU")
    throttle = prof.get("throttle_c", 110)
    fan_help = prof.get("fan_curve_helpful", True)
    if prof.get("arch") == "rdna3":
        target_line = (
            f"log \"RDNA3 runs junction near {throttle}°C by design — only worry if clocks drop\"\n"
        )
        corectrl = _corectrl_hint() if fan_help else (
            'log "RDNA3 rarely needs a fan curve — lower in-game settings if throttling"\n'
        )
    else:
        target_line = f'log "Re-check junction on dashboard — target well below {throttle}°C sustained"\n'
        corectrl = _corectrl_hint() if fan_help else ""
    return (
        _header("gpu-thermal-ceiling", f"Cool-down playbook ({arch}, junction was {junction}°C)", "medium")
        + f"""
log "=== GPU telemetry ==="
sensors amdgpu-pci-0300 2>/dev/null | grep -E 'edge|junction|mem|fan|PPT' || true
cat /sys/class/drm/card1/device/gpu_busy_percent 2>/dev/null && echo "% GPU busy" || true

log "=== In-game (manual) ==="
cat <<'PLAYBOOK'

  Cities: Skylines II → Options → Graphics:
    • Frame rate limit → 60 or 90
    • Level of detail → Medium or lower
    • Shadow quality → Medium or lower
    • Volumetrics / depth of field → off or low

PLAYBOOK

log "Opening CS2 settings folder..."
xdg-open '{CS2_DIR}' 2>/dev/null || true

"""
        + corectrl
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


def script_vram_bandwidth(pct: int, est: str) -> str:
    return _header("gpu-vram-bandwidth", f"Reduce VRAM bandwidth load ({pct}% busy)", "low") + f"""
log "VRAM controller busy: {pct}% (~{est} GB/s est.)"
log "Opening mod cache + settings..."
xdg-open '{CS2_DIR}/.cache/Mods' 2>/dev/null || true
sleep 1
xdg-open '{CS2_DIR}' 2>/dev/null || true
cat <<'PLAYBOOK'

  In Cities 2 → Options → Graphics:
    • Texture quality → Medium
    • Asset quality → Medium or lower
  Disable asset-replacement mods temporarily and retest.

PLAYBOOK
log "Monitor mem_busy% on dashboard — aim for under 50% in normal play"
"""


def script_vram_low(pct: float, used: int) -> str:
    return _header("gpu-vram-full", f"Free VRAM headroom ({pct}% used)", "low") + f"""
log "VRAM {pct}% used ({used} MB)"
xdg-open '{CS2_DIR}' 2>/dev/null || true
cat <<'PLAYBOOK'

  Cities 2 → Options → Graphics:
    • Resolution scale → 85–90%
    • Texture quality → Medium
    • Disable high-res asset mods (Content Manager)

PLAYBOOK
"""


def script_gtt(rate: float) -> str:
    return _header("gpu-gtt-churn", f"Reduce shared GPU memory traffic ({rate} MB/s GTT)", "low") + f"""
log "GTT churn: {rate} MB/s"
cat /sys/class/drm/card1/device/mem_info_gtt_used /sys/class/drm/card1/device/mem_info_gtt_total 2>/dev/null || true
xdg-open '{CS2_DIR}/.cache/Mods' 2>/dev/null || true
cat <<'PLAYBOOK'

  Keep VRAM under 80% — lower textures/resolution before adding mods.

PLAYBOOK
"""


def script_swap_thrash(swap_pct: float) -> str:
    return _header("memory-swap-thrash", f"Stop swap thrash (swap {swap_pct}% used)", "medium") + """
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


def script_dram_stall(psi: float) -> str:
    return _header("memory-dram-stall", f"Reduce DRAM stall pressure (PSI {psi}%)", "medium") + """
log "=== Top memory ==="
ps aux --sort=-%mem | head -20
log "=== Top CPU ==="
ps aux --sort=-%cpu | head -10

cat <<'PLAYBOOK'

  Close or suspend:
    • Browsers (Firefox/Brave — hundreds of MB each)
    • Discord overlay
    • Paradox launcher if not needed
  Then re-check PSI Memory on dashboard (aim under 5%).

PLAYBOOK

log "Optional — copy and run yourself (Pulse never executes these):"
log "  flatpak kill com.brave.Browser"
log "  pkill -x firefox"
log "  pkill -x discord"
"""


def script_stutter(score: float, est_ms: float, causes: list[str]) -> str:
    cause_txt = ", ".join(causes) if causes else "memory pressure"
    return _header(
        "stutter-proxy",
        f"Reduce hitches (score {score}, ~{est_ms}ms est.)",
        "low",
    ) + f"""
log "Cosmic Pulse stutter proxy — likely causes: {cause_txt}"
log "=== Memory / swap ==="
free -h
cat /proc/sys/vm/swappiness
log "=== Top memory ==="
ps aux --sort=-%mem | head -15

cat <<'PLAYBOOK'

  Hitch playbook (no true frametime — system-level proxy):
    1. Close browsers, Discord, extra launchers
    2. Let the game finish loading before unpausing / camera moves
    3. If swap is active: sudo sysctl vm.swappiness=10
    4. Large Cities saves: drop sim speed to 1× until stable
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


def script_page_faults(rate: int) -> str:
    return _header("memory-page-faults", f"Reduce major page faults ({rate}/s)", "low") + f"""
log "Major faults indicate disk/swap backed loads."
cat <<'PLAYBOOK'

  Cities 2 playbook:
    1. Load save → wait until loading completes
    2. Stay paused 30s after load before unpausing
    3. Avoid alt-tab during initial simulation catch-up
    4. If faults persist: lower city size mods / reboot before session

PLAYBOOK
log "Opening save folder..."
xdg-open '{CS2_DIR}/Saves' 2>/dev/null || true
"""


def script_cpu_bound() -> str:
    return _header("cpu-bound", "CPU-bound — boost clocks and trim background load", "low") + """
log "=== CPU ==="
grep . /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
ps aux --sort=-%cpu | head -15

need_root
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo performance > "$g"
done

cat <<'PLAYBOOK'

  Cities 2 (in-game):
    • Simulation speed 1× on huge cities
    • Reduce traffic/agent mods
    • Lower citizen simulation detail if mod offers it

PLAYBOOK
log "Governor set to performance"
"""


def script_gpu_shader() -> str:
    return _header("gpu-shader-bound", "GPU shader bound — favor resolution over textures", "low") + f"""
cat <<'PLAYBOOK'

  You are GPU compute bound (not VRAM bandwidth bound).
  Cities 2 → Graphics:
    • OK to raise resolution scale if thermals allow
    • Avoid max texture / asset packs
    • Watch junction temp on dashboard

PLAYBOOK
xdg-open '{CS2_DIR}' 2>/dev/null || true
"""


def script_ccd_spread(t1: float, t2: float) -> str:
    return _header("cpu-ccd-spread", f"CCD thermal spread {t1}°C vs {t2}°C", "low") + f"""
log "Normal on Ryzen 7900X — game threads often favor one CCD."
sensors k10temp-pci-00c3 2>/dev/null | grep -i tccd || true
log "Optional monitoring (5s sample, Ctrl+C to stop):"
if command -v turbostat >/dev/null; then
  turbostat --show Core,CPU,Busy,MHz -- interval 5
else
  log "Install: sudo apt install linux-tools-common linux-tools-$(uname -r)"
fi
"""


def script_balanced() -> str:
    return _header("system-balanced", "System healthy — maintenance checklist", "low") + f"""
log "No critical insights. Maintenance:"
log "  • Steam launch options:"
echo '    PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%'
log "  • Optional GameMode:"
echo '    gamemoderun PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%'
xdg-open '{CS2_DIR}' 2>/dev/null || true
log "Dashboard: http://localhost:8765"
"""


SCRIPTS: dict[str, callable] = {
    "cpu-governor-powersave": script_governor,
    "vm-swappiness-high": lambda: script_swappiness(180),
    "ram-expo-verify": script_expo_verify,
    "gpu-thermal-ceiling": lambda j=100: script_gpu_thermal(j),
    "gpu-thermal-warm": lambda j=90: script_gpu_warm(j),
    "gpu-vram-bandwidth": lambda: script_vram_bandwidth(65, "?"),
    "gpu-vram-full": lambda: script_vram_low(80, 0),
    "gpu-gtt-churn": lambda: script_gtt(50),
    "memory-swap-thrash": lambda: script_swap_thrash(25),
    "memory-dram-stall": lambda: script_dram_stall(8),
    "memory-page-faults": lambda: script_page_faults(20),
    "cpu-bound": script_cpu_bound,
    "gpu-shader-bound": script_gpu_shader,
    "cpu-ccd-spread": lambda: script_ccd_spread(0, 0),
    "system-balanced": script_balanced,
}


def get_fix_script(insight_id: str, **kwargs) -> str:
    """Return fix script for an insight_id, with optional context kwargs."""
    fn = SCRIPTS.get(insight_id)
    if not fn:
        return ""
    try:
        return fn(**kwargs).strip() if kwargs else fn().strip()
    except TypeError:
        return fn().strip()