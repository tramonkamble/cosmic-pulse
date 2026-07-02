# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic Steam game detection — AppID from launch context, PIDs from process tree."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import psutil

HOME = Path.home()

APPID_RE = re.compile(r"AppId=(\d+)", re.I)
COMPAT_RE = re.compile(r"compatdata/(\d+)", re.I)
GAMEID_RE = re.compile(r"-gameid\s+(\d+)", re.I)
OVERLAY_GAMEID_RE = re.compile(r"-gameid\s+(\d+)", re.I)
OVERLAY_PID_RE = re.compile(r"-pid\s+(\d+)", re.I)
STEAM_ENV_APPID_KEYS = (
    b"STEAM_COMPAT_APP_ID=",
    b"SteamAppId=",
    b"SteamGameId=",
)
GAME_BINARY_SUFFIXES = (".exe", ".x86_64", ".x86", ".bin")
MANIFEST_NAME_RE = re.compile(r'"name"\s*"([^"]+)"')
MANIFEST_DIR_RE = re.compile(r'"installdir"\s*"([^"]+)"')

SKIP_PROCS = frozenset({
    "wineserver", "winedevice.exe", "wineboot.exe", "wine64-preloader", "wine-preloader",
    "crashpad_handler", "crashpad_handle", "xalia.exe", "steam.exe", "steamwebhelper",
    "fossilize_replay.exe", "reaper", "explorer.exe", "tabtip.exe", "sh", "python3",
    "python", "systemd", "gamemoded", "gamemoderun", "srt-bwrap", "rpcss.exe",
    "services.exe", "svchost.exe", "plugplay.exe", "tabtip.exe", "steam-runtime",
    "pv-adverb", "steam-launch-wrapper", "proton", "pressure-vessel", "srt-logger",
})

LAUNCHER_EXES = frozenset({
    "dowser.exe", "launcher.exe", "launch.exe", "unityplayer.exe",
})

# Helpers / crash reporters — never meter as the game.
AUXILIARY_EXES = frozenset({
    "unitycrashhandler64.exe", "unitycrashhandler.exe",
    "crashpad_handler.exe", "crashpad_handler.dll", "gameoverlayui",
})

# Optional per-AppID detection tuning (main_exe / exclude_exe only — names from manifests).
GAME_OVERRIDES: dict[str, dict] = {
    "730": {
        "main_exe": frozenset({"cs2.exe", "cs2"}),
        "short": "CS2",
    },
}

# Back-compat alias for diagnostics and docs.
GAMES: dict[str, dict] = {
    appid: {
        "id": appid,
        "appid": appid,
        "name": meta.get("name") or f"AppID {appid}",
        "short": meta.get("short") or f"AppID {appid}",
        "compat": f"compatdata/{appid}",
    }
    for appid, meta in GAME_OVERRIDES.items()
}


def steam_root() -> Path:
    env = os.environ.get("STEAM_BASE") or os.environ.get("STEAM_BASE_FOLDER")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for candidate in (
        HOME / ".local/share/Steam",
        HOME / ".steam" / "steam",
        HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ):
        if (candidate / "steamapps").is_dir():
            return candidate
    return HOME / ".local/share/Steam"


STEAM = steam_root()


def _short_name(name: str) -> str:
    words = (name or "").split()
    if len(words) <= 3:
        return name
    return " ".join(words[:3])


@lru_cache(maxsize=256)
def _read_manifest(appid: str) -> dict[str, str]:
    path = STEAM / "steamapps" / f"appmanifest_{appid}.acf"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return {}
    name_m = MANIFEST_NAME_RE.search(text)
    dir_m = MANIFEST_DIR_RE.search(text)
    out: dict[str, str] = {}
    if name_m:
        out["name"] = name_m.group(1).strip()
    if dir_m:
        out["installdir"] = dir_m.group(1).strip()
    return out


def game_meta(appid: str) -> dict:
    manifest = _read_manifest(appid)
    override = GAME_OVERRIDES.get(appid, {})
    name = override.get("name") or manifest.get("name") or f"AppID {appid}"
    short = override.get("short") or _short_name(name)
    return {
        "id": appid,
        "appid": appid,
        "name": name,
        "short": short,
        "installdir": manifest.get("installdir", ""),
        "compat": f"compatdata/{appid}",
    }


def build_games_catalog() -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    steamapps = STEAM / "steamapps"
    if steamapps.is_dir():
        for path in steamapps.glob("appmanifest_*.acf"):
            appid = path.name.removeprefix("appmanifest_").removesuffix(".acf")
            meta = game_meta(appid)
            catalog[appid] = {
                "name": meta["name"],
                "short": meta["short"],
                "appid": appid,
            }
    for appid in GAME_OVERRIDES:
        meta = game_meta(appid)
        catalog.setdefault(appid, {
            "name": meta["name"],
            "short": meta["short"],
            "appid": appid,
        })
    return catalog


def game_name_for_appid(appid: str) -> str:
    return game_meta(appid)["name"]


_MANIFEST_INT = re.compile(r'"(\w+)"\s*"(\d+)"')
_CONTENT_CORRUPT_RE = re.compile(r"AppID\s+(\d+)\s+state changed\s+:.*Files Corrupt", re.I)
_CONTENT_SUSPENDED_RE = re.compile(
    r"AppID\s+(\d+)\s+scheduler finished\s+:.*result Suspended", re.I,
)


def _tail_lines(path: Path, max_lines: int = 500) -> list[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(errors="replace").splitlines()[-max_lines:]
    except OSError:
        return []


def steam_install_health(appid: str) -> dict:
    """Parse Steam manifest + content_log for corrupt files / stalled updates."""
    manifest_path = STEAM / "steamapps" / f"appmanifest_{appid}.acf"
    ints: dict[str, int] = {}
    if manifest_path.is_file():
        try:
            for key, val in _MANIFEST_INT.findall(manifest_path.read_text(errors="ignore")):
                if key in {
                    "BytesToDownload", "BytesDownloaded", "BytesToStage", "BytesStaged",
                    "UpdateResult", "StateFlags",
                }:
                    ints[key] = int(val)
        except OSError:
            pass

    to_dl = ints.get("BytesToDownload", 0)
    downloaded = ints.get("BytesDownloaded", 0)
    pending = max(0, to_dl - downloaded)

    files_corrupt = False
    update_suspended = False
    recent = _tail_lines(STEAM / "logs" / "content_log.txt", 600)
    for i, line in enumerate(recent):
        if f"AppID {appid}" not in line:
            continue
        if _CONTENT_CORRUPT_RE.search(line):
            files_corrupt = True
        if "Files Corrupt" in line and "App Running" in line:
            files_corrupt = True
        if _CONTENT_SUSPENDED_RE.search(line):
            window = recent[max(0, i - 8): i + 1]
            if any("App Running" in w for w in window):
                update_suspended = True

    return {
        "appid": appid,
        "files_corrupt": files_corrupt,
        "pending_download_bytes": pending,
        "update_queued": pending > 0,
        "update_suspended_while_running": update_suspended,
        "update_result": ints.get("UpdateResult"),
    }


def game_install_dir(appid: str) -> Path:
    meta = game_meta(appid)
    idir = (meta.get("installdir") or "").strip()
    if idir:
        return STEAM / "steamapps" / "common" / idir
    return STEAM / "steamapps" / "common"


def game_compat_dir(appid: str) -> Path:
    return STEAM / "steamapps" / "compatdata" / appid


def game_proton_userdata_dirs(appid: str) -> list[Path]:
    """Proton prefix LocalLow folders (publisher/game) when present."""
    base = game_compat_dir(appid) / "pfx/drive_c/users/steamuser/AppData/LocalLow"
    if not base.is_dir():
        return []
    dirs: list[Path] = []
    for publisher in sorted(base.iterdir()):
        if not publisher.is_dir():
            continue
        for title in sorted(publisher.iterdir()):
            if title.is_dir():
                dirs.append(title)
    return dirs


def game_data_paths(appid: str | None) -> dict:
    """Best-effort folders for the active game (install, compat, userdata)."""
    if not appid:
        return {
            "appid": None,
            "name": "your game",
            "install": None,
            "compat": None,
            "userdata": None,
            "open_dir": None,
        }
    meta = game_meta(appid)
    install = game_install_dir(appid)
    compat = game_compat_dir(appid)
    userdata_dirs = game_proton_userdata_dirs(appid)
    userdata = userdata_dirs[0] if userdata_dirs else None
    open_dir = None
    if userdata and userdata.is_dir():
        open_dir = userdata
    elif install.is_dir():
        open_dir = install
    elif compat.is_dir():
        open_dir = compat
    return {
        "appid": appid,
        "name": meta.get("name") or f"AppID {appid}",
        "install": install if install.is_dir() else None,
        "compat": compat if compat.is_dir() else None,
        "userdata": userdata,
        "open_dir": open_dir,
    }


def active_game_context(game_totals: dict | None) -> dict:
    """Context dict for hints, fix scripts, and one-click fixes."""
    gt = game_totals or {}
    appid = gt.get("game_id") if gt.get("running") else None
    paths = game_data_paths(appid)
    if appid and gt.get("game_name"):
        paths["name"] = gt["game_name"]
    return paths


ALL_GAME_IDS = list(build_games_catalog().keys())


def _norm_cpu(raw: float) -> float:
    threads = psutil.cpu_count(logical=True) or 1
    return round(min(100.0, raw / threads), 1)


def scan_active_appids() -> set[str]:
    appids: set[str] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not cmd:
            continue
        for match in APPID_RE.finditer(cmd):
            appids.add(match.group(1))
        compat = COMPAT_RE.search(cmd)
        if compat:
            appids.add(compat.group(1))
        overlay = GAMEID_RE.search(cmd)
        if overlay:
            appids.add(overlay.group(1))
    return appids


def scan_overlay_game_pids() -> dict[str, set[int]]:
    """Map AppID -> game PIDs from Steam gameoverlayui (-gameid / -pid)."""
    out: dict[str, set[int]] = {}
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "gameoverlayui" not in name:
                continue
            cmd = " ".join(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        gid_m = OVERLAY_GAMEID_RE.search(cmd)
        pid_m = OVERLAY_PID_RE.search(cmd)
        if gid_m and pid_m:
            out.setdefault(gid_m.group(1), set()).add(int(pid_m.group(1)))
    return out


def _proc_steam_appid(pid: int) -> str | None:
    """Read Proton/Steam AppID from /proc/pid/environ (short Wine cmdlines omit paths)."""
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        for prefix in STEAM_ENV_APPID_KEYS:
            if entry.startswith(prefix):
                val = entry[len(prefix):].decode("utf-8", errors="ignore").strip()
                if val.isdigit():
                    return val
    return None


def _proc_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _cwd_matches_installdir(cwd: str, installdir: str) -> bool:
    if not installdir:
        return False
    cl = cwd.replace("\\", "/").lower().rstrip("/")
    idir = installdir.replace("\\", "/").lower().strip("/")
    return cl.endswith(f"/common/{idir}") or f"/common/{idir}/" in f"{cl}/"


def _proc_matches_appid(
    cmd: str,
    appid: str,
    installdir: str,
    exe_l: str = "",
    *,
    pid: int | None = None,
    overlay_pids: set[int] | None = None,
    env_cache: dict[int, str | None] | None = None,
    cwd_cache: dict[int, str | None] | None = None,
) -> bool:
    cl = cmd.lower().replace("\\", "/")
    aid = appid.lower()
    if f"compatdata/{aid}" in cl:
        return True
    if f"appid={aid}" in cl.replace(" ", ""):
        return True
    if installdir:
        idir = installdir.lower().replace("\\", "/")
        if f"common/{idir}" in cl:
            return True
    override = GAME_OVERRIDES.get(appid, {})
    main_exes = override.get("main_exe")
    if main_exes and exe_l in main_exes:
        return True
    if pid is None:
        return False
    if overlay_pids and pid in overlay_pids:
        return True
    if env_cache is not None:
        if pid not in env_cache:
            env_cache[pid] = _proc_steam_appid(pid)
        if env_cache[pid] == appid:
            return True
    if installdir and cwd_cache is not None:
        if pid not in cwd_cache:
            cwd_cache[pid] = _proc_cwd(pid)
        cwd = cwd_cache[pid]
        if cwd and _cwd_matches_installdir(cwd, installdir):
            return True
    return False


def _is_game_binary(name: str) -> bool:
    base = (name or "").lower()
    return any(base.endswith(suffix) for suffix in GAME_BINARY_SUFFIXES)


def _exe_basename_from_cmdline(cmd: str) -> str:
    """Recover game binary from cmdline (Wine truncates psutil names to 15 chars)."""
    cl = cmd.replace("\\", "/")
    matches = re.findall(
        r"([^/\s]+\.(?:x86_64|exe|x86|bin))",
        cl,
        re.I,
    )
    if not matches:
        return ""
    for segment in reversed(matches):
        base = segment.lower()
        if base not in LAUNCHER_EXES and base not in SKIP_PROCS:
            return base
    return matches[-1].lower()


def _effective_exe_name(name: str, cmd: str) -> str:
    name_l = (name or "").lower()
    from_cmd = _exe_basename_from_cmdline(cmd)
    if from_cmd and _is_game_binary(from_cmd):
        return from_cmd
    if _is_game_binary(name_l):
        return name_l
    return from_cmd or name_l


def _classify_proc(
    appid: str,
    name: str,
    cmd: str,
    meta: dict,
    *,
    pid: int | None = None,
    overlay_pids: set[int] | None = None,
    env_cache: dict[int, str | None] | None = None,
    cwd_cache: dict[int, str | None] | None = None,
) -> str | None:
    name_l = (name or "").lower()
    exe_l = _effective_exe_name(name, cmd)
    if name_l in SKIP_PROCS or exe_l in SKIP_PROCS or exe_l in AUXILIARY_EXES:
        return None
    if not _proc_matches_appid(
        cmd,
        appid,
        meta.get("installdir", ""),
        exe_l,
        pid=pid,
        overlay_pids=overlay_pids,
        env_cache=env_cache,
        cwd_cache=cwd_cache,
    ):
        return None

    override = GAME_OVERRIDES.get(appid, {})
    main_exes = override.get("main_exe")
    if main_exes and exe_l in main_exes:
        return "main"
    exclude = override.get("exclude_exe", ())
    if exe_l in exclude or name_l in exclude:
        return None
    if not _is_game_binary(exe_l):
        return None
    if exe_l in LAUNCHER_EXES:
        return "launcher"
    if main_exes:
        return "child"
    return "main"


def _pick_primary(rows: list[dict], *, require_main: bool = False) -> dict | None:
    if not rows:
        return None
    mains = [r for r in rows if r["tier"] == "main"]
    if mains:
        return max(mains, key=lambda r: (r["cpu_pct"], r["rss_mb"]))
    if require_main:
        return None
    children = [r for r in rows if r["tier"] == "child"]
    if children:
        return max(children, key=lambda r: (r["cpu_pct"], r["rss_mb"]))
    launchers = [r for r in rows if r["tier"] == "launcher"]
    if launchers:
        return max(launchers, key=lambda r: (r["rss_mb"], r["cpu_pct"]))
    return max(rows, key=lambda r: (r["cpu_pct"], r["rss_mb"]))


def detect_games() -> dict[str, dict]:
    """Return per-AppID running state for Steam-launched games."""
    active_appids = scan_active_appids()
    if not active_appids:
        return {}

    buckets: dict[str, list[dict]] = {appid: [] for appid in active_appids}
    metas = {appid: game_meta(appid) for appid in active_appids}
    overlay_map = scan_overlay_game_pids()
    env_cache: dict[int, str | None] = {}
    cwd_cache: dict[int, str | None] = {}

    for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
            cmd = " ".join(proc.info["cmdline"] or [])
            mi = proc.info["memory_info"]
            raw_cpu = proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        for appid, meta in metas.items():
            tier = _classify_proc(
                appid,
                name,
                cmd,
                meta,
                pid=pid,
                overlay_pids=overlay_map.get(appid),
                env_cache=env_cache,
                cwd_cache=cwd_cache,
            )
            if not tier:
                continue
            display_name = _effective_exe_name(name, cmd)
            buckets[appid].append({
                "pid": proc.info["pid"],
                "name": display_name if _is_game_binary(display_name) else name,
                "tier": tier,
                "cpu_threads_pct": round(raw_cpu, 1),
                "cpu_pct": _norm_cpu(raw_cpu),
                "rss_mb": round(mi.rss / 1024**2, 1) if mi else 0,
            })

    out: dict[str, dict] = {}
    for appid, meta in metas.items():
        rows = buckets[appid]
        rows.sort(key=lambda x: (0 if x["tier"] == "main" else 1 if x["tier"] == "child" else 2, -x["rss_mb"]))
        require_main = bool(GAME_OVERRIDES.get(appid, {}).get("main_exe"))
        primary = _pick_primary(rows, require_main=require_main)
        out[appid] = {
            **meta,
            "running": primary is not None,
            "primary_name": primary["name"] if primary else None,
            "primary_pid": primary["pid"] if primary else None,
            "cpu_pct": primary["cpu_pct"] if primary else 0.0,
            "rss_mb": primary["rss_mb"] if primary else 0.0,
            "tree_rss_mb": round(sum(r["rss_mb"] for r in rows), 1),
            "proc_count": len(rows),
            "procs": rows[:12],
        }
    return out


def prime_game_cpu() -> None:
    active = scan_active_appids()
    if not active:
        return
    metas = {appid: game_meta(appid) for appid in active}
    overlay_map = scan_overlay_game_pids()
    env_cache: dict[int, str | None] = {}
    cwd_cache: dict[int, str | None] = {}
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
            cmd = " ".join(proc.info["cmdline"] or [])
            for appid, meta in metas.items():
                if _classify_proc(
                    appid,
                    name,
                    cmd,
                    meta,
                    pid=pid,
                    overlay_pids=overlay_map.get(appid),
                    env_cache=env_cache,
                    cwd_cache=cwd_cache,
                ):
                    proc.cpu_percent(interval=None)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def running_game_ids(state: dict[str, dict]) -> list[str]:
    return [gid for gid, g in state.items() if g.get("running")]


def primary_active_game(state: dict[str, dict]) -> dict | None:
    running = [g for g in state.values() if g.get("running")]
    if not running:
        return None
    return max(running, key=lambda g: (g.get("cpu_pct") or 0, g.get("rss_mb") or 0))


def installed_appids() -> list[str]:
    steamapps = STEAM / "steamapps"
    if not steamapps.is_dir():
        return list(GAME_OVERRIDES.keys())
    ids = [
        p.name.removeprefix("appmanifest_").removesuffix(".acf")
        for p in steamapps.glob("appmanifest_*.acf")
    ]
    return sorted(set(ids) | set(GAME_OVERRIDES.keys()))