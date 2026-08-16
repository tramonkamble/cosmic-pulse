# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""System & gaming troubleshooting — boot, Steam, libraries, logs.

Design (experiment redo): findings must be *actionable* for a second-monitor
coach. Prefer silence over “8 error-like lines in bootstrap_log.” Scans run on
a background thread so journalctl never blocks the 1 Hz metrics loop.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from games import (
    game_name_for_appid,
    installed_appids,
    steam_install_health,
    steam_root,
    steam_update_needs_attention,
)

HOME = Path.home()


def _steam_logs() -> Path:
    return steam_root() / "logs"


# journal / dmesg lines matching these are ignored (cosmetic or benign)
_NOISE_PATTERNS = re.compile(
    r"surface missing from known popups|"
    r"auth could not identify password|"
    r"conversation failed|"
    r"Bluetooth: hci0: No support for _PRR|"
    r"invalid context state for evaluate context|"
    r"xHC error in resume|"
    # Optical tray / empty media — not gaming-relevant
    r"\bdev sr\d+\b|"
    r"critical medium error|"
    r"Buffer I/O error on dev sr|"
    r"Sense Key :|"
    r"Add\. Sense:|"
    r"I/O error.*cdrom|"
    r"UDF-fs:|"
    r"ISOFS:",
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
_PROMOTE_SEVERITIES = frozenset({"hot", "warn"})

# i386 soname -> (apt package, description) — needs `dpkg --add-architecture i386`
_GAMING_LIBS_I386: list[tuple[str, str, str]] = [
    ("libGL.so.1", "libgl1:i386", "OpenGL (32-bit)"),
    ("libvulkan.so.1", "libvulkan1:i386", "Vulkan loader (32-bit)"),
    ("libldap.so.2", "libldap2:i386", "LDAP (32-bit Proton/Wine)"),
]

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
    primary_hint: str | None = None,
) -> dict:
    """One finding. ``fix`` must be a *single* shell line (or plain UI step)."""
    cmd = (fix or "").strip()
    # Refuse multi-command “·” glue — that broke copy-paste in the failed experiment.
    if " · " in cmd:
        cmd = cmd.split(" · ")[0].strip()
    return {
        "id": fid,
        "category": category,
        "severity": severity,
        "title": title,
        "text": text,
        "detail": detail,
        "fix": cmd or None,
        "source": source,
        "primary_hint": primary_hint,  # short “do this first” line for UI
        "read_only": True,
    }


def _run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return ""


def _ldconfig_map() -> str:
    return _run(["ldconfig", "-p"], timeout=5)


def _ldconfig_has_i386_soname(libs: str, soname: str) -> bool:
    """True if soname is registered for 32-bit (Pop/Ubuntu ldconfig uses (libc6) on i386 paths)."""
    for line in libs.splitlines():
        if soname not in line:
            continue
        if "(libc6,i386)" in line:
            return True
        if "i386-linux-gnu" in line:
            return True
    return False


def _foreign_architectures() -> set[str]:
    out = _run(["dpkg", "--print-foreign-architectures"], timeout=5)
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _check_multilib(findings: list[dict]) -> None:
    arches = _foreign_architectures()
    if "i386" not in arches:
        findings.append(
            _finding(
                "lib-multilib-missing",
                "libraries",
                "warn",
                "32-bit multilib not enabled",
                "Steam and Proton need i386 libraries for many Windows games. "
                "Enable the architecture once, then install common 32-bit packages.",
                fix=(
                    "sudo dpkg --add-architecture i386 && sudo apt update && "
                    "sudo apt install libgl1:i386 libvulkan1:i386 libldap2:i386"
                ),
                source="dpkg",
            )
        )
        return
    libs = _ldconfig_map()
    missing_i386: list[tuple[str, str, str]] = []
    for soname, pkg, desc in _GAMING_LIBS_I386:
        if not _ldconfig_has_i386_soname(libs, soname):
            missing_i386.append((soname, pkg, desc))
    for soname, pkg, desc in missing_i386:
        findings.append(
            _finding(
                f"lib-missing-i386-{soname.replace('.', '-')}",
                "libraries",
                "warn",
                f"Missing 32-bit library: {desc}",
                f"`{soname}` (i386) not found — Proton games may fail to start or show a blank window.",
                fix=f"sudo apt install {pkg}",
                source="ldconfig-i386",
            )
        )


def _check_libraries(findings: list[dict]) -> None:
    _check_multilib(findings)
    libs = _ldconfig_map()
    missing_required: list[tuple[str, str, str]] = []
    for soname, pkg, desc in _GAMING_LIBS:
        if soname.startswith("libdxvk"):
            continue  # optional — ships with Proton
        if soname not in libs:
            missing_required.append((soname, pkg, desc))

    for soname, pkg, desc in missing_required:
        findings.append(
            _finding(
                f"lib-missing-{soname.replace('.', '-')}",
                "libraries",
                "hot" if soname.startswith("libvulkan") or soname == "libGL.so.1" else "warn",
                f"Missing library: {desc}",
                f"`{soname}` not found via ldconfig — games may fail to start or render.",
                fix=f"sudo apt install {pkg}",
                source="ldconfig",
            )
        )

    # No "DXVK not in system path" — normal with Proton (bundled per prefix).

    for bin_name, pkg, note in _OPTIONAL_BINS:
        if bin_name == "steam" and steam_root().exists():
            continue
        if not shutil.which(bin_name):
            findings.append(
                _finding(
                    f"bin-missing-{bin_name}",
                    "libraries",
                    "info",
                    f"Optional tool missing: {bin_name}",
                    note,
                    fix=f"sudo apt install {pkg}",
                    source="PATH",
                )
            )


def _check_boot_and_kernel(findings: list[dict]) -> None:
    failed = _run(["systemctl", "--failed", "--no-legend", "--plain"], timeout=5).strip()
    if failed:
        units = [ln.split()[0] for ln in failed.splitlines() if ln.strip()]
        # One unit to inspect — not a wall of systemctl prose
        first = units[0] if units else "UNIT"
        findings.append(
            _finding(
                "systemd-failed",
                "boot",
                "warn",
                f"Failed systemd units ({len(units)})",
                "Services did not start cleanly this boot: " + ", ".join(units[:6]),
                detail=failed[:1200],
                fix=f"journalctl -b -u {first} --no-pager | tail -80",
                primary_hint=f"Inspect failed unit: {first}",
                source="systemctl",
            )
        )

    # Priority 3+ this boot: GPU driver only (not optical / BT spam)
    err_lines = _run(
        ["journalctl", "-b", "0", "-p", "3", "--no-pager", "-n", "200"],
        timeout=12,
    ).splitlines()
    gpu_err: list[str] = []
    for line in err_lines:
        if _NOISE_PATTERNS.search(line):
            continue
        if re.search(r"\b(amdgpu|nvidia|nvrm|drm)\b", line, re.I):
            gpu_err.append(line.strip())
    if gpu_err:
        hard = any(re.search(r"reset|hang|segfault|panic|fault|oom", x, re.I) for x in gpu_err)
        findings.append(
            _finding(
                "journal-gpu-errors",
                "driver",
                "hot" if hard else "warn",
                "GPU driver errors this boot",
                (
                    "Kernel logged GPU errors (amdgpu/nvidia/drm). "
                    "If games crash or the display freezes, this is the trail."
                ),
                detail="\n".join(list(dict.fromkeys(gpu_err))[:6])[:1500],
                fix="journalctl -b 0 -p 3 --no-pager | grep -iE 'amdgpu|nvidia|drm' | tail -40",
                primary_hint="Check GPU journal errors from this boot",
                source="journalctl -b 0 -p 3",
            )
        )
        return  # don't also dump weaker -k noise for the same story

    gpu_warn = []
    for line in _run(
        ["journalctl", "-b", "-k", "--no-pager", "-n", "120"], timeout=8
    ).splitlines():
        if _NOISE_PATTERNS.search(line):
            continue
        if re.search(r"\b(amdgpu|nvidia|drm)\b", line, re.I) and re.search(
            r"error|fail|reset|hang|fault", line, re.I
        ):
            gpu_warn.append(line)
    if gpu_warn:
        findings.append(
            _finding(
                "kernel-gpu-warnings",
                "driver",
                "warn",
                "Kernel GPU warnings",
                "GPU-related kernel warnings this boot — watch if you see hitching or black screens.",
                detail="\n".join(list(dict.fromkeys(gpu_warn))[:5])[:1200],
                fix="journalctl -b -k --no-pager | grep -iE 'amdgpu|nvidia|drm' | tail -40",
                primary_hint="Review kernel GPU warnings",
                source="journalctl -k",
            )
        )


def _check_disk(findings: list[dict]) -> None:
    """Steam volume free space only — no package-manager update nagging."""
    try:
        usage = shutil.disk_usage(steam_root())
        free_gb = usage.free / 1024**3
        if free_gb < 15:
            findings.append(
                _finding(
                    "disk-steam-low",
                    "storage",
                    "warn" if free_gb < 8 else "info",
                    f"Low disk space on Steam volume ({free_gb:.1f} GB free)",
                    "Less than 15 GB free — game updates and Proton prefixes can fail.",
                    fix="steam steam://settings/storage",
                    primary_hint="Free space: Steam → Settings → Storage (clear old prefixes)",
                    source=str(steam_root()),
                )
            )
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


def _is_background_steam_title(name: str, appid: str) -> bool:
    """Redistributables / runtimes — not what a gamer means by 'my game is broken'."""
    n = (name or "").lower()
    if re.search(
        r"redistributable|steamworks|proton\b|runtime|steam linux|directx|vcredist|dotnet",
        n,
    ):
        return True
    # Known Steamworks redistributable appids (common noise)
    if appid in {"228980", "1070560", "1391110", "1628350"}:
        return True
    return False


def _check_steam_install_health(findings: list[dict]) -> None:
    for appid in installed_appids():
        health = steam_install_health(appid)
        name = game_name_for_appid(appid)
        manifest = str(steam_root() / "steamapps" / f"appmanifest_{appid}.acf")
        background = _is_background_steam_title(name, appid)

        if health.get("files_corrupt") and not background:
            findings.append(
                _finding(
                    f"steam-corrupt-{appid}",
                    "game",
                    "hot",
                    f"{name}: verify game files",
                    "Steam flagged game files as corrupt — common after patches; "
                    "causes crashes or missing content.",
                    fix=f"steam steam://validate/{appid}",
                    primary_hint=f"Verify integrity for {name}",
                    source=manifest,
                )
            )

        if steam_update_needs_attention(health, running=False):
            # Pending redistributable updates are almost never the user's problem.
            if background:
                continue
            from games import steam_update_summary_parts

            shader_mb = round(health.get("shader_cache_bytes", 0) / 1024**2, 1)
            parts = steam_update_summary_parts(health)
            if shader_mb > 200:
                parts.append(f"{shader_mb} MB shader cache")
            text = " · ".join(parts) or "Steam update incomplete"
            findings.append(
                _finding(
                    f"steam-update-{appid}",
                    "game",
                    "warn",
                    f"{name}: finish pending update",
                    text + " — half-patched builds hitch and rebuild shaders.",
                    fix="steam steam://open/downloads",
                    primary_hint=f"Finish the Steam update for {name}",
                    source=manifest,
                )
            )


def _check_steam_logs(findings: list[dict]) -> None:
    steam = steam_root()
    if not steam.exists():
        findings.append(
            _finding(
                "steam-missing",
                "steam",
                "hot",
                "Steam not found",
                f"Expected Steam at {steam}",
                fix="Install Steam from Pop!_Shop or https://store.steampowered.com",
                source="path",
            )
        )
        return

    # Game crash / bad exit codes from gameprocess log
    gp_lines = _scan_log_tail(_steam_logs() / "gameprocess_log.txt", 800)
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
        if _is_background_steam_title(game_name, appid):
            continue
        recent = codes[-5:]
        crashy = 139 in recent or 137 in recent or 134 in recent
        findings.append(
            _finding(
                f"game-exit-{appid}",
                "game",
                "warn" if crashy else "info",
                f"{game_name} closed with errors",
                f"Recent exit codes {recent} — crash or failed load.",
                fix=f"steam steam://validate/{appid}",
                primary_hint=f"Verify {game_name} if it keeps crashing",
                source="gameprocess_log.txt",
            )
        )

    # Steam logs: only surface when lines look *game-breaking*, not perpetual client noise.
    _CRASHISH = re.compile(
        r"segfault|sigsegv|fatal|crash|assert|exception|out of memory|oom|"
        r"failed to initialize|could not load|missing shared libraries",
        re.I,
    )
    # Prefer error.log; only touch chatty logs if crashish
    for log_name in ("error.log", "stderr.txt", "gameprocess_log.txt"):
        path = _steam_logs() / log_name
        if not path.is_file():
            continue
        hits = []
        for line in _scan_log_tail(path, 250):
            if _NOISE_PATTERNS.search(line):
                continue
            if not _CRASHISH.search(line) and log_name != "error.log":
                continue
            if log_name == "error.log" and not (_ERROR_LINE.search(line) or _CRASHISH.search(line)):
                continue
            hits.append(line.strip())
        uniq = list(dict.fromkeys(hits))[-5:]
        if not uniq:
            continue
        if log_name != "error.log" and len(uniq) < 2:
            continue
        findings.append(
            _finding(
                f"steam-log-{log_name.replace('.', '-')}",
                "steam",
                "warn" if any(_CRASHISH.search(x) for x in uniq) else "info",
                "Steam logged a serious error" if log_name == "error.log" else f"Steam {log_name}",
                "Crash- or load-related lines in Steam logs — useful after a failed launch.",
                detail="\n".join(uniq)[:1500],
                fix=f"tail -n 80 '{path}'",
                primary_hint="Read the latest Steam error lines",
                source=str(path),
            )
        )


def _check_game_prefixes(findings: list[dict]) -> None:
    """Scan existing Proton prefixes for version oddities and error logs.

    Missing compatdata is intentionally not reported: Steam Linux Runtimes,
    redistributables, native Linux titles, and not-yet-played games all lack
    prefixes normally — that is not an actionable issue.
    """
    compat_root = steam_root() / "steamapps" / "compatdata"
    for appid in installed_appids():
        prefix = compat_root / appid
        if not prefix.is_dir():
            continue

        # Game stderr in Proton prefix
        for pattern in ("*/logs/*.log", "*/error*.log"):
            for log_path in list(prefix.glob(pattern))[:20]:
                if log_path.stat().st_size > 5_000_000:
                    continue
                err_lines = [
                    ln.strip()
                    for ln in _scan_log_tail(log_path, 80)
                    if _ERROR_LINE.search(ln) and not _NOISE_PATTERNS.search(ln)
                ]
                if len(err_lines) >= 3:
                    findings.append(
                        _finding(
                            f"game-log-{appid}-{log_path.name}",
                            "game",
                            "info",
                            f"{game_name_for_appid(appid)} log errors",
                            f"Errors in {log_path.relative_to(prefix)}",
                            detail="\n".join(list(dict.fromkeys(err_lines))[-5:])[:1200],
                            fix=f"xdg-open '{log_path.parent}'",
                            source=str(log_path),
                        )
                    )
                    break


def _check_vulkan(findings: list[dict]) -> None:
    if not shutil.which("vulkaninfo"):
        return
    out = _run(["vulkaninfo", "--summary"], timeout=12)
    if not out:
        return
    if "ERROR" in out or "Cannot" in out:
        findings.append(
            _finding(
                "vulkaninfo-error",
                "driver",
                "hot",
                "Vulkan not working",
                "vulkaninfo reported errors — games using Vulkan/Proton may fail.",
                detail=out[:1500],
                fix="sudo apt install mesa-vulkan-drivers libvulkan1",
                primary_hint="Install Vulkan drivers, then reboot",
                source="vulkaninfo",
            )
        )
    elif "deviceName" not in out and "deviceType" not in out and "GPU" not in out:
        findings.append(
            _finding(
                "vulkan-device-mismatch",
                "driver",
                "warn",
                "Vulkan GPU not detected",
                "vulkaninfo ran but no discrete GPU device was reported.",
                detail=out[:800],
                fix="DRI_PRIME=1 vulkaninfo --summary",
                primary_hint="Check which GPU Vulkan sees",
                source="vulkaninfo",
            )
        )


def run_diagnostics() -> dict:
    findings: list[dict] = []
    _check_libraries(findings)
    _check_boot_and_kernel(findings)
    _check_disk(findings)
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
        findings.append(
            _finding(
                "all-clear",
                "system",
                "ok",
                "No issues detected",
                "Boot, libraries, Steam logs, and Vulkan look clean.",
                source="pulse",
            )
        )
        counts["ok"] = 1

    return {
        "scanned_at": time.time(),
        "counts": counts,
        "findings": findings,
        "categories": sorted({f["category"] for f in findings}),
    }


_cache: tuple[float, dict] = (0.0, {})

_scan_lock = threading.Lock()
_scan_thread: threading.Thread | None = None
_scan_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "result": None,
}


def invalidate_diagnostics_cache(*, rescan: bool = True) -> None:
    """Drop cached diagnostics so the next read is not stuck on a stale async result.

    Clears both the legacy ``_cache`` tuple and the background job's last result
    marker. By default also kicks a quiet background rescan so Options "Clear
    scan cache" and DIAG-backed auto-resolve actually get fresh findings.
    """
    global _cache
    _cache = (0.0, {})
    with _scan_lock:
        # Keep last result visible until the new scan finishes — only mark stale.
        _scan_state["status"] = "idle"
        _scan_state["error"] = None
        # scanned_at stays on result so UI can show age; force path starts new work.
        if _scan_state.get("result") is not None:
            # Stamp so TTL logic treats it as expired even if wall clock is weird.
            result = dict(_scan_state["result"])
            result["_stale"] = True
            _scan_state["result"] = result
    if rescan:
        request_diagnostics_scan()


def scan_findings(findings: list[dict], *, skip_ids: set[str] | None = None) -> list[dict]:
    """Findings for Guidance Scan (excludes promoted cards / all-clear filler)."""
    skip = skip_ids or set()
    return [f for f in findings if f["id"] not in skip and f["id"] != "all-clear"]


def primary_finding(findings: list[dict] | None) -> dict | None:
    """Single 'do this first' finding — hot > warn > info. Silence if nothing real."""
    order = {"hot": 0, "warn": 1, "info": 2}
    real = [
        f
        for f in (findings or [])
        if f.get("id") != "all-clear" and f.get("severity") in order
    ]
    if not real:
        return None
    real.sort(key=lambda f: (order.get(f.get("severity") or "info", 9), f.get("title") or ""))
    return real[0]


def _empty_diagnostics(*, pending: bool = False) -> dict:
    return {
        "scanned_at": None,
        "counts": {"hot": 0, "warn": 0, "info": 0, "ok": 0},
        "findings": [],
        "categories": [],
        "pending": pending,
    }


def get_diagnostics(ttl_sec: float = 90.0, *, force: bool = False) -> dict:
    """Cached diagnostics. Never blocks the caller on journalctl / Steam walks.

    force=True kicks a background rescan and returns the last good result (or
    a pending shell) immediately. First paint with an empty cache also starts
    a background scan instead of freezing the HTTP thread.

    When a completed result is older than ``ttl_sec``, a quiet background rescan
    is requested while the last findings keep serving (no HTTP stall).
    """
    global _cache
    now = time.time()
    if force:
        request_diagnostics_scan()

    with _scan_lock:
        ready_result = None
        if _scan_state.get("result"):
            ready_result = dict(_scan_state["result"])
        running = _scan_state.get("status") == "running"
        status = _scan_state.get("status") or "idle"

    if ready_result is not None:
        scanned_at = ready_result.get("scanned_at")
        try:
            age = now - float(scanned_at) if scanned_at is not None else None
        except (TypeError, ValueError):
            age = None
        stale = bool(ready_result.get("_stale")) or (age is not None and age > ttl_sec)
        # Quiet TTL refresh — never block the request path on journalctl.
        if stale and not running and not force:
            request_diagnostics_scan()
        ready_result = dict(ready_result)
        ready_result.pop("_stale", None)
        if running or (stale and status != "ready"):
            ready_result["pending"] = True
        return ready_result

    if not force and now - _cache[0] < ttl_sec and _cache[1]:
        return _cache[1]
    if _cache[1]:
        # Cache present but past TTL — refresh in background, still serve it.
        if not running and now - _cache[0] >= ttl_sec:
            request_diagnostics_scan()
        return _cache[1]

    # Cold start — never sync-run under an HTTP thread
    if not running:
        request_diagnostics_scan()
    return _empty_diagnostics(pending=True)


def _background_scan_worker() -> None:
    global _cache, _scan_thread
    try:
        result = run_diagnostics()
        now = time.time()
        with _scan_lock:
            _scan_state["status"] = "ready"
            _scan_state["finished_at"] = now
            _scan_state["error"] = None
            _scan_state["result"] = result
        _cache = (now, result)
    except Exception as exc:
        with _scan_lock:
            _scan_state["status"] = "error"
            _scan_state["finished_at"] = time.time()
            _scan_state["error"] = str(exc)[:400]
    finally:
        with _scan_lock:
            _scan_thread = None


def request_diagnostics_scan() -> dict:
    """Kick a background scan; never blocks the caller on journalctl."""
    global _scan_thread
    with _scan_lock:
        if _scan_state.get("status") == "running" and _scan_thread and _scan_thread.is_alive():
            return diagnostics_job_status()
        _scan_state["status"] = "running"
        _scan_state["started_at"] = time.time()
        _scan_state["finished_at"] = None
        _scan_state["error"] = None
        # Keep previous result visible while rescanning (don't wipe UI to empty)
        t = threading.Thread(
            target=_background_scan_worker,
            daemon=True,
            name="pulse-diagnostics-scan",
        )
        _scan_thread = t
        t.start()
    return diagnostics_job_status()


def diagnostics_job_status() -> dict:
    with _scan_lock:
        status = _scan_state.get("status") or "idle"
        result = _scan_state.get("result")
        out = {
            "status": status,
            "started_at": _scan_state.get("started_at"),
            "finished_at": _scan_state.get("finished_at"),
            "error": _scan_state.get("error"),
            "running": status == "running",
            # ready = at least one completed result available (even mid-rescan)
            "ready": bool(result),
            "has_result": bool(result),
        }
        if result:
            out["scanned_at"] = result.get("scanned_at")
            out["counts"] = result.get("counts")
            out["findings"] = result.get("findings")
            out["primary"] = primary_finding(result.get("findings") or [])
        return out
