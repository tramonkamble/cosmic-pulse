# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""System & gaming troubleshooting — boot, Steam, libraries, logs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from games import STEAM, game_name_for_appid, installed_appids, steam_install_health

HOME = Path.home()
STEAM_LOGS = STEAM / "logs"

# journal / dmesg lines matching these are ignored (cosmetic or benign)
_NOISE_PATTERNS = re.compile(
    r"surface missing from known popups|"
    r"auth could not identify password|"
    r"conversation failed|"
    r"Bluetooth: hci0: No support for _PRR|"
    r"invalid context state for evaluate context|"
    r"xHC error in resume",
    re.I,
)

_ERROR_LINE = re.compile(
    r"error|fail|fatal|crash|segfault|sigsegv|missing|not found|"
    r"could not|unable to|vulkan|dxvk|wine: |err:|failed",
    re.I,
)

_GAME_EXIT = re.compile(
    r"AppID (\d+) no longer tracking PID \d+, exit code (-?\d+)",
    re.I,
)

_BAD_GAME_EXITS = frozenset({1, 2, 3, 126, 127, 128, 137, 139, 143, 255})

# ldconfig soname -> (apt package, description)
_GAMING_LIBS: list[tuple[str, str, str]] = [
    ("libvulkan.so.1", "libvulkan1", "Vulkan loader"),
    ("libvulkan_radeon.so", "mesa-vulkan-drivers", "AMD Vulkan (Mesa)"),
    ("libGL.so.1", "libgl1", "OpenGL"),
    ("libEGL.so.1", "libegl1", "EGL"),
    ("libdxvk_d3d11.so", "dxvk", "DXVK (optional — often bundled in Proton)"),
    ("libgamemode.so.0", "gamemode", "GameMode"),
    ("libfreetype.so.6", "libfreetype6", "FreeType (Wine UI fonts)"),
    ("libldap.so.2", "libldap2", "LDAP (Proton/Wine)"),
    ("libgpg-error.so.0", "libgpg-error0", "GPG error (Proton/Wine)"),
]

_OPTIONAL_BINS: list[tuple[str, str, str]] = [
    ("gamemoded", "gamemode", "GameMode daemon for launch options"),
    ("mangohud", "mangohud", "FPS overlay & MangoHud launch wrapper"),
    ("vulkaninfo", "vulkan-tools", "Vulkan capability check"),
    ("winetricks", "winetricks", "Wine prefix fixes"),
    ("steam", "steam-devices", "Steam (verify install)"),
]

_STEAM_LOG_FILES = (
    "gameprocess_log.txt",
    "stderr.txt",
    "console_log.txt",
    "bootstrap_log.txt",
)


def _finding(
    fid: str,
    category: str,
    severity: str,
    title: str,
    text: str,
    *,
    detail: str | None = None,
    fix: str | None = None,
    source: str | None = None,
) -> dict:
    return {
        "id": fid,
        "category": category,
        "severity": severity,
        "title": title,
        "text": text,
        "detail": detail,
        "fix": fix,
        "source": source,
    }


def _run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        return subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return ""


def _ldconfig_map() -> str:
    return _run(["ldconfig", "-p"], timeout=5)


def _check_libraries(findings: list[dict]) -> None:
    libs = _ldconfig_map()
    missing_required: list[tuple[str, str, str]] = []
    for soname, pkg, desc in _GAMING_LIBS:
        if soname.startswith("libdxvk"):
            continue  # optional — ships with Proton
        if soname not in libs:
            missing_required.append((soname, pkg, desc))

    for soname, pkg, desc in missing_required:
        findings.append(_finding(
            f"lib-missing-{soname.replace('.', '-')}",
            "libraries",
            "hot" if soname.startswith("libvulkan") or soname == "libGL.so.1" else "warn",
            f"Missing library: {desc}",
            f"`{soname}` not found via ldconfig — games may fail to start or render.",
            fix=f"sudo apt install {pkg}",
            source="ldconfig",
        ))

    if "libdxvk" not in libs and "libvulkan_radeon.so" in libs:
        findings.append(_finding(
            "lib-dxvk-bundled",
            "libraries",
            "info",
            "DXVK not in system path",
            "Normal with Proton — DXVK is usually bundled per game prefix.",
            source="ldconfig",
        ))

    for bin_name, pkg, note in _OPTIONAL_BINS:
        if bin_name == "steam" and STEAM.exists():
            continue
        if not shutil.which(bin_name):
            findings.append(_finding(
                f"bin-missing-{bin_name}",
                "libraries",
                "info",
                f"Optional tool missing: {bin_name}",
                note,
                fix=f"sudo apt install {pkg}",
                source="PATH",
            ))


def _check_boot_and_kernel(findings: list[dict]) -> None:
    failed = _run(["systemctl", "--failed", "--no-legend", "--plain"], timeout=5).strip()
    if failed:
        units = [ln.split()[0] for ln in failed.splitlines() if ln.strip()]
        findings.append(_finding(
            "systemd-failed",
            "boot",
            "warn",
            f"Failed systemd units ({len(units)})",
            "Services did not start cleanly this boot: " + ", ".join(units[:6]),
            detail=failed[:1200],
            fix="systemctl --failed · journalctl -u UNIT -b",
            source="systemctl",
        ))

    err_log = _run(["journalctl", "-b", "-p", "err", "--no-pager", "-n", "80"], timeout=10)
    err_lines = []
    for line in err_log.splitlines():
        if _NOISE_PATTERNS.search(line):
            continue
        if "error" in line.lower() or "fail" in line.lower():
            err_lines.append(line)
    if err_lines:
        uniq = list(dict.fromkeys(err_lines))[:8]
        findings.append(_finding(
            "boot-journal-errors",
            "boot",
            "warn" if len(uniq) > 3 else "info",
            f"Boot journal errors ({len(uniq)} unique)",
            "Non-fatal errors since last boot — review if games crash or hardware acts up.",
            detail="\n".join(uniq)[:2000],
            fix="journalctl -b -p err --no-pager | less",
            source="journalctl",
        ))

    gpu_warn = []
    for line in _run(["journalctl", "-b", "-k", "--no-pager", "-n", "200"], timeout=10).splitlines():
        if _NOISE_PATTERNS.search(line):
            continue
        if re.search(r"amdgpu|gpu|drm|vulkan|ring", line, re.I) and re.search(
            r"error|fail|warn|reset|hang", line, re.I
        ):
            gpu_warn.append(line)
    if gpu_warn:
        findings.append(_finding(
            "kernel-gpu-warnings",
            "driver",
            "warn",
            f"Kernel GPU messages ({len(gpu_warn)})",
            " AMDGPU / DRM warnings this boot — can cause crashes or stutter.",
            detail="\n".join(list(dict.fromkeys(gpu_warn))[:6])[:1500],
            fix="journalctl -b -k | grep -iE 'amdgpu|drm|gpu' | tail -50",
            source="journalctl -k",
        ))


def _check_updates_and_disk(findings: list[dict]) -> None:
    upgradable = _run(["apt", "list", "--upgradable"], timeout=15)
    if upgradable:
        lines = [ln for ln in upgradable.splitlines() if ln and not ln.startswith("Listing")]
        n = len(lines)
        if n >= 5:
            findings.append(_finding(
                "apt-upgrades-pending",
                "updates",
                "info" if n < 30 else "warn",
                f"{n} package updates available",
                "Pending apt upgrades — kernel/mesa updates often fix gaming issues.",
                detail="\n".join(lines[:12]) + ("\n…" if n > 12 else ""),
                fix="sudo apt update && sudo apt upgrade",
                source="apt",
            ))

    try:
        usage = shutil.disk_usage(STEAM)
        free_gb = usage.free / 1024**3
        if free_gb < 15:
            findings.append(_finding(
                "disk-steam-low",
                "storage",
                "warn" if free_gb < 8 else "info",
                f"Low disk space on Steam volume ({free_gb:.1f} GB free)",
                "Less than 15 GB free — game updates and Proton prefixes can fail.",
                fix="Clear old Proton prefixes · Steam → Settings → Storage",
                source=str(STEAM),
            ))
    except OSError:
        pass


def _scan_log_tail(path: Path, max_lines: int = 400) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = path.read_text(errors="replace")
        return data.splitlines()[-max_lines:]
    except OSError:
        return []


def _check_steam_install_health(findings: list[dict]) -> None:
    for appid in installed_appids():
        health = steam_install_health(appid)
        if not any((
            health.get("files_corrupt"),
            health.get("update_queued") and health.get("pending_download_bytes", 0) > 5_000_000,
        )):
            continue
        name = game_name_for_appid(appid)
        pending_mb = round(health["pending_download_bytes"] / 1024**2, 1)
        parts: list[str] = []
        if health.get("files_corrupt"):
            parts.append("Steam flagged game files as corrupt")
        if health.get("update_queued") and pending_mb > 0:
            parts.append(f"{pending_mb} MB update still pending")
        if health.get("update_suspended_while_running"):
            parts.append("update paused while the game was running")
        text = " · ".join(parts) or "Install health check failed"
        sev = "hot" if health.get("files_corrupt") else "warn"
        findings.append(_finding(
            f"steam-install-{appid}",
            "game",
            sev,
            f"{name}: verify game files",
            text + " — common on Linux after patches; causes crashes, missing maps, or VAC errors.",
            fix=f"Quit {name} → Steam → Properties → Installed Files → Verify · complete any pending update",
            source=str(STEAM / "steamapps" / f"appmanifest_{appid}.acf"),
        ))


def _check_steam_logs(findings: list[dict]) -> None:
    if not STEAM.exists():
        findings.append(_finding(
            "steam-missing",
            "steam",
            "hot",
            "Steam not found",
            f"Expected Steam at {STEAM}",
            fix="Install Steam from Pop!_Shop or https://store.steampowered.com",
            source="path",
        ))
        return

    # Game crash / bad exit codes from gameprocess log
    gp_lines = _scan_log_tail(STEAM_LOGS / "gameprocess_log.txt", 800)
    bad_exits: dict[str, list[int]] = {}
    for line in gp_lines:
        m = _GAME_EXIT.search(line)
        if not m:
            continue
        appid, code = m.group(1), int(m.group(2))
        if code in _BAD_GAME_EXITS:
            bad_exits.setdefault(appid, []).append(code)

    for appid, codes in bad_exits.items():
        game_name = game_name_for_appid(appid)
        recent = codes[-5:]
        findings.append(_finding(
            f"game-exit-{appid}",
            "game",
            "warn" if 139 in recent or 137 in recent else "info",
            f"{game_name} abnormal exits",
            f"Recent process exits with codes {recent} — may indicate crash or failed load.",
            fix=f"Check Steam → {game_name} → Properties → verify files · see Proton log",
            source="gameprocess_log.txt",
        ))

    # Error lines from steam logs
    for log_name in _STEAM_LOG_FILES:
        path = STEAM_LOGS / log_name
        hits = []
        for line in _scan_log_tail(path, 300):
            if not _ERROR_LINE.search(line):
                continue
            if _NOISE_PATTERNS.search(line):
                continue
            hits.append(line.strip())
        uniq = list(dict.fromkeys(hits))[-6:]
        if len(uniq) >= 2:
            findings.append(_finding(
                f"steam-log-{log_name.replace('.', '-')}",
                "steam",
                "info",
                f"Steam log: {log_name}",
                f"{len(uniq)} recent error-like lines — skim if launches fail.",
                detail="\n".join(uniq)[:1800],
                fix=f"less {path}",
                source=str(path),
            ))


def _check_game_prefixes(findings: list[dict]) -> None:
    compat_root = STEAM / "steamapps" / "compatdata"
    for appid in installed_appids():
        meta_name = game_name_for_appid(appid)
        prefix = compat_root / appid
        if not prefix.is_dir():
            findings.append(_finding(
                f"prefix-missing-{appid}",
                "game",
                "info",
                f"{meta_name}: no Proton prefix yet",
                "First launch will create compatdata — errors before that are normal.",
                source=str(prefix),
            ))
            continue
        ver_file = prefix / "version"
        if ver_file.is_file():
            try:
                ver = ver_file.read_text().strip()
                if ver and "proton" not in ver.lower() and "steam" not in ver.lower():
                    findings.append(_finding(
                        f"prefix-version-{appid}",
                        "game",
                        "info",
                        f"{meta_name} prefix version",
                        f"compatdata version: {ver}",
                        source=str(ver_file),
                    ))
            except OSError:
                pass

        # Game stderr in Proton prefix
        for pattern in ("*/logs/*.log", "*/error*.log"):
            for log_path in list(prefix.glob(pattern))[:20]:
                if log_path.stat().st_size > 5_000_000:
                    continue
                err_lines = [
                    ln.strip() for ln in _scan_log_tail(log_path, 80)
                    if _ERROR_LINE.search(ln) and not _NOISE_PATTERNS.search(ln)
                ]
                if len(err_lines) >= 3:
                    findings.append(_finding(
                        f"game-log-{appid}-{log_path.name}",
                        "game",
                        "info",
                        f"{game_name_for_appid(appid)} log errors",
                        f"Errors in {log_path.relative_to(prefix)}",
                        detail="\n".join(list(dict.fromkeys(err_lines))[-5:])[:1200],
                        fix=f"xdg-open '{log_path.parent}'",
                        source=str(log_path),
                    ))
                    break


def _check_vulkan(findings: list[dict]) -> None:
    if not shutil.which("vulkaninfo"):
        return
    out = _run(["vulkaninfo", "--summary"], timeout=12)
    if not out:
        return
    if "ERROR" in out or "Cannot" in out:
        findings.append(_finding(
            "vulkaninfo-error",
            "driver",
            "hot",
            "Vulkan not working",
            "vulkaninfo reported errors — games using Vulkan/Proton may fail.",
            detail=out[:1500],
            fix="sudo apt install mesa-vulkan-drivers libvulkan1 · reboot",
            source="vulkaninfo",
        ))
    elif "deviceName" not in out and "deviceType" not in out and "GPU" not in out:
        findings.append(_finding(
            "vulkan-device-mismatch",
            "driver",
            "warn",
            "Vulkan GPU not detected",
            "vulkaninfo ran but no discrete GPU device was reported.",
            detail=out[:800],
            fix="DRI_PRIME=1 vulkaninfo --summary",
            source="vulkaninfo",
        ))


def run_diagnostics() -> dict:
    findings: list[dict] = []
    _check_libraries(findings)
    _check_boot_and_kernel(findings)
    _check_updates_and_disk(findings)
    _check_steam_logs(findings)
    _check_steam_install_health(findings)
    _check_game_prefixes(findings)
    _check_vulkan(findings)

    order = {"hot": 0, "warn": 1, "info": 2, "ok": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["category"], f["title"]))

    counts = {k: 0 for k in ("hot", "warn", "info", "ok")}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    if not findings:
        findings.append(_finding(
            "all-clear",
            "system",
            "ok",
            "No issues detected",
            "Boot, libraries, Steam logs, and Vulkan look clean.",
            source="pulse",
        ))
        counts["ok"] = 1

    return {
        "scanned_at": time.time(),
        "counts": counts,
        "findings": findings,
        "categories": sorted({f["category"] for f in findings}),
    }


_cache: tuple[float, dict] = (0.0, {})


def get_diagnostics(ttl_sec: float = 90.0) -> dict:
    global _cache
    now = time.time()
    if now - _cache[0] < ttl_sec and _cache[1]:
        return _cache[1]
    result = run_diagnostics()
    _cache = (now, result)
    return result