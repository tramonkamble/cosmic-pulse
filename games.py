# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic Steam game detection — AppID from launch context, PIDs from process tree."""

from __future__ import annotations

import os
import re
import time
from functools import lru_cache
from pathlib import Path

import psutil

_STEAM_HEALTH_CACHE: dict[str, tuple[float, dict]] = {}
_CONTENT_LOG_CACHE: tuple[float, list[str]] = (0.0, [])
_SHADER_SIZE_CACHE: dict[str, tuple[float, int]] = {}
_STEAM_HEALTH_TTL = 45.0
_CONTENT_LOG_TTL = 30.0
_SHADER_SIZE_TTL = 300.0

HOME = Path.home()

APPID_RE = re.compile(r"AppId=(\d+)", re.I)
COMPAT_RE = re.compile(r"compatdata/(\d+)", re.I)
GAMEID_RE = re.compile(r"-gameid\s+(\d+)", re.I)
OVERLAY_PID_RE = re.compile(r"-pid\s+(\d+)", re.I)
STEAM_ENV_APPID_KEYS = (
    b"STEAM_COMPAT_APP_ID=",
    b"SteamAppId=",
    b"SteamGameId=",
)
GAME_BINARY_SUFFIXES = (".exe", ".x86_64", ".x86", ".bin")
MANIFEST_NAME_RE = re.compile(r'"name"\s*"([^"]+)"')
MANIFEST_DIR_RE = re.compile(r'"installdir"\s*"([^"]+)"')

SKIP_PROCS = frozenset(
    {
        "wineserver",
        "winedevice.exe",
        "wineboot.exe",
        "wine64-preloader",
        "wine-preloader",
        "crashpad_handler",
        "crashpad_handle",
        "xalia.exe",
        "steam.exe",
        "steamwebhelper",
        "fossilize_replay.exe",
        "reaper",
        "explorer.exe",
        "tabtip.exe",
        "sh",
        "python3",
        "python",
        "systemd",
        "gamemoded",
        "gamemoderun",
        "srt-bwrap",
        "rpcss.exe",
        "services.exe",
        "svchost.exe",
        "plugplay.exe",
        "steam-runtime",
        "pv-adverb",
        "steam-launch-wrapper",
        "proton",
        "pressure-vessel",
        "srt-logger",
    }
)

LAUNCHER_EXES = frozenset(
    {
        "dowser.exe",
        "launcher.exe",
        "launch.exe",
        "unityplayer.exe",
    }
)

# Helpers / crash reporters — never meter as the game.
AUXILIARY_EXES = frozenset(
    {
        "unitycrashhandler64.exe",
        "unitycrashhandler.exe",
        "crashpad_handler.exe",
        "crashpad_handler.dll",
        "gameoverlayui",
    }
)

# Populated from rule packs (see get_game_overrides / get_legacy_game_ids).
_GAME_OVERRIDE_CACHE: dict[str, dict] | None = None
_LEGACY_ID_CACHE: dict[str, str] | None = None


def _load_legacy_game_ids() -> dict[str, str]:
    global _LEGACY_ID_CACHE
    if _LEGACY_ID_CACHE is not None:
        return _LEGACY_ID_CACHE
    try:
        from rule_packs import get_legacy_game_ids

        _LEGACY_ID_CACHE = get_legacy_game_ids()
    except Exception:
        return {}
    return _LEGACY_ID_CACHE


def _load_game_overrides() -> dict[str, dict]:
    global _GAME_OVERRIDE_CACHE
    if _GAME_OVERRIDE_CACHE is not None:
        return _GAME_OVERRIDE_CACHE
    try:
        from rule_packs import get_game_overrides

        _GAME_OVERRIDE_CACHE = get_game_overrides()
    except Exception:
        return {}
    return _GAME_OVERRIDE_CACHE


class _LazyDict:
    """Dict-like view loaded from rule packs on first access."""

    __slots__ = ("_loader", "_cache")

    def __init__(self, loader):
        self._loader = loader
        self._cache: dict | None = None

    def _data(self) -> dict:
        if self._cache is None:
            self._cache = self._loader()
        return self._cache

    def get(self, key, default=None):
        return self._data().get(key, default)

    def __getitem__(self, key):
        return self._data()[key]

    def keys(self):
        return self._data().keys()

    def items(self):
        return self._data().items()

    def values(self):
        return self._data().values()

    def __iter__(self):
        return iter(self._data())

    def __contains__(self, key):
        return key in self._data()

    def __len__(self):
        return len(self._data())


LEGACY_GAME_IDS = _LazyDict(_load_legacy_game_ids)
GAME_OVERRIDES = _LazyDict(_load_game_overrides)


def reload_game_pack_data() -> None:
    """Invalidate cached pack-derived game tables (pack hot-reload / tests)."""
    global _GAME_OVERRIDE_CACHE, _LEGACY_ID_CACHE
    _GAME_OVERRIDE_CACHE = None
    _LEGACY_ID_CACHE = None
    LEGACY_GAME_IDS._cache = None
    GAME_OVERRIDES._cache = None


def normalize_game_id(game_id: str | None) -> str | None:
    if not game_id:
        return None
    return _load_legacy_game_ids().get(game_id, game_id)


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


_LOCALCONFIG_CACHE: tuple[float, str] = (0.0, "")
_STEAM_ID64_BASE = 76561197960265728


def session_is_wayland() -> bool:
    return (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland"


def _steam_account_id(steam_id64: str) -> str:
    return str(int(steam_id64) - _STEAM_ID64_BASE)


def _extract_vdf_block(text: str, key: str) -> str:
    needle = f'"{key}"'
    pos = 0
    while True:
        idx = text.find(needle, pos)
        if idx == -1:
            return ""
        tail = text[idx + len(needle) : idx + len(needle) + 48]
        if re.match(r"\s*\{", tail):
            start = text.index("{", idx)
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
        pos = idx + 1


def _most_recent_steam_localconfig_path() -> Path | None:
    loginusers = steam_root() / "config" / "loginusers.vdf"
    userdata = steam_root() / "userdata"
    if loginusers.is_file() and userdata.is_dir():
        try:
            text = loginusers.read_text(errors="ignore")
        except OSError:
            text = ""
        for steam_id64 in re.findall(r'"(\d{17})"', text):
            block = _extract_vdf_block(text, steam_id64)
            if block and re.search(r'"MostRecent"\s*"1"', block):
                path = userdata / _steam_account_id(steam_id64) / "config" / "localconfig.vdf"
                if path.is_file():
                    return path
    return None


def _steam_localconfig_path() -> Path | None:
    recent = _most_recent_steam_localconfig_path()
    if recent:
        return recent
    userdata = steam_root() / "userdata"
    if not userdata.is_dir():
        return None
    for account in sorted(userdata.iterdir()):
        if not account.is_dir() or not account.name.isdigit():
            continue
        path = account / "config" / "localconfig.vdf"
        if path.is_file():
            return path
    return None


def _read_localconfig_text() -> str:
    global _LOCALCONFIG_CACHE
    path = _steam_localconfig_path()
    if not path:
        return ""
    try:
        mtime = path.stat().st_mtime
        if mtime <= _LOCALCONFIG_CACHE[0] and _LOCALCONFIG_CACHE[1]:
            return _LOCALCONFIG_CACHE[1]
        text = path.read_text(errors="ignore")
    except OSError:
        return ""
    _LOCALCONFIG_CACHE = (mtime, text)
    return text


def steam_launch_options(appid: str | None) -> str:
    """Per-game Steam LaunchOptions from localconfig.vdf (empty when unset)."""
    if not appid:
        return ""
    text = _read_localconfig_text()
    if not text:
        return ""
    block = _extract_vdf_block(text, appid)
    if not block:
        return ""
    match = re.search(r'"LaunchOptions"\s*"([^"]*)"', block)
    return match.group(1) if match else ""


def launch_has_wayland_fix(opts: str | None) -> bool:
    """True when launch options already force Proton/X11 instead of native Wayland."""
    o = (opts or "").lower()
    return (
        "proton_enable_wayland=0" in o
        or "proton_use_wayland=0" in o
        or "sdl_videodriver=x11" in o
    )


def _proc_environ_blob(pid: int) -> bytes:
    try:
        return Path(f"/proc/{pid}/environ").read_bytes().replace(b"\0", b" ")
    except OSError:
        return b""


def proc_uses_proton(pid: int | None, *, depth: int = 0) -> bool:
    """True when pid or its parents show an active Proton/Wine game session."""
    if not pid or depth > 6:
        return False
    blob = _proc_environ_blob(pid)
    if blob and b"STEAM_COMPAT_PROTON=1" in blob and (
        b"WINEDLLPATH" in blob or b"SteamAppId=" in blob
    ):
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        ppid = int(stat.split()[3])
    except (OSError, ValueError, IndexError):
        return False
    return proc_uses_proton(ppid, depth=depth + 1)


def game_session_launch_metrics(
    appid: str | None,
    primary_pid: int | None = None,
) -> dict[str, bool | str]:
    """Proton session + whether Steam launch options lack the Wayland→X11 override."""
    opts = steam_launch_options(appid)
    return {
        "proton": proc_uses_proton(primary_pid),
        "wayland_fix_missing": not launch_has_wayland_fix(opts),
        "launch_options": opts,
    }


def _short_name(name: str) -> str:
    words = (name or "").split()
    if len(words) <= 3:
        return name
    return " ".join(words[:3])


@lru_cache(maxsize=256)
def _read_manifest(appid: str) -> dict[str, str]:
    path = steam_root() / "steamapps" / f"appmanifest_{appid}.acf"
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
    appid = normalize_game_id(appid) or appid
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
    steamapps = steam_root() / "steamapps"
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
        catalog.setdefault(
            appid,
            {
                "name": meta["name"],
                "short": meta["short"],
                "appid": appid,
            },
        )
    return catalog


def game_name_for_appid(appid: str) -> str:
    return game_meta(appid)["name"]


_MANIFEST_INT = re.compile(r'"(\w+)"\s*"(\d+)"')
_CONTENT_LOG_TAIL = 1200
_CONTENT_SUSPENDED_LOOKBACK = 8
_STATE_CORRUPT_RE = re.compile(
    r"AppID\s+(\d+)\s+state changed\s+:.*Files Corrupt",
    re.I,
)
_STATE_RUNNING_RE = re.compile(
    r"AppID\s+(\d+)\s+state changed\s+:.*App Running",
    re.I,
)
_SCHEDULER_SUSPENDED_RE = re.compile(
    r"AppID\s+(\d+)\s+scheduler finished\s+:.*result Suspended",
    re.I,
)
_STATE_CHANGED_RE = re.compile(r"AppID\s+(\d+)\s+state changed\s*:(.*)", re.I)
_UPDATE_BUSY_RE = re.compile(
    r"AppID\s+(\d+)\s+(?:App|Shader) update changed\s*:.*"
    r"(?:Downloading|Staging|Preallocating|Verifying|Committing)",
    re.I,
)
_SCHEDULER_MISSING_RE = re.compile(
    r"AppID\s+(\d+)\s+scheduler finished\s+:.*Missing game files",
    re.I,
)


def clear_steam_health_caches() -> None:
    """Reset cached Steam health reads (tests / forced diagnostics refresh)."""
    global _CONTENT_LOG_CACHE
    _STEAM_HEALTH_CACHE.clear()
    _CONTENT_LOG_CACHE = (0.0, [])
    _SHADER_SIZE_CACHE.clear()


def _tail_lines(path: Path, max_lines: int = 500, *, tail_bytes: int = 384 * 1024) -> list[str]:
    """Read only the tail of a log file (content_log can grow for months)."""
    if not path.is_file():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - tail_bytes))
            data = handle.read().decode("utf-8", errors="replace")
        return data.splitlines()[-max_lines:]
    except OSError:
        return []


def _cached_content_log_lines(max_lines: int = _CONTENT_LOG_TAIL) -> list[str]:
    global _CONTENT_LOG_CACHE
    now = time.monotonic()
    if now - _CONTENT_LOG_CACHE[0] < _CONTENT_LOG_TTL:
        return _CONTENT_LOG_CACHE[1]
    lines = _tail_lines(steam_root() / "logs" / "content_log.txt", max_lines)
    _CONTENT_LOG_CACHE = (now, lines)
    return lines


def _dir_size_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _shader_cache_bytes(appid: str) -> int:
    now = time.monotonic()
    cached = _SHADER_SIZE_CACHE.get(appid)
    if cached and now - cached[0] < _SHADER_SIZE_TTL:
        return cached[1]
    size = _dir_size_bytes(shader_cache_dir(appid))
    _SHADER_SIZE_CACHE[appid] = (now, size)
    return size


def shader_cache_dir(appid: str) -> Path:
    return steam_root() / "steamapps" / "shadercache" / str(appid)


def _content_log_success(line: str, appid: str) -> bool:
    if f"AppID {appid}" not in line:
        return False
    if "finished update" in line:
        return True
    return (
        "scheduler finished" in line
        and "result No Error" in line
        and "removed from schedule" in line
    )


def _content_log_corrupt(line: str, appid: str) -> bool:
    m = _STATE_CORRUPT_RE.search(line)
    return bool(m and m.group(1) == appid)


def _content_log_suspended(line: str, appid: str) -> bool:
    m = _SCHEDULER_SUSPENDED_RE.search(line)
    return bool(m and m.group(1) == appid)


def _same_app_running_near(lines: list[str], idx: int, appid: str) -> bool:
    """True when this AppID was running near a scheduler Suspended line (not another game)."""
    start = max(0, idx - _CONTENT_SUSPENDED_LOOKBACK)
    for w in lines[start : idx + 1]:
        m = _STATE_RUNNING_RE.search(w)
        if m and m.group(1) == appid:
            return True
    return False


def parse_content_log(appid: str, lines: list[str]) -> dict[str, bool]:
    """Derive install/update signals for one AppID from content_log lines."""
    last_success = -1
    corrupt_idx: int | None = None
    suspended_idx: int | None = None
    missing_idx: int | None = None
    update_active = False
    last_state = ""

    for i, line in enumerate(lines):
        if f"AppID {appid}" not in line:
            continue
        if _content_log_success(line, appid):
            last_success = i
            corrupt_idx = None
            suspended_idx = None
            missing_idx = None
            update_active = False
        elif _content_log_corrupt(line, appid):
            corrupt_idx = i
        elif _content_log_suspended(line, appid) and _same_app_running_near(lines, i, appid):
            suspended_idx = i
        else:
            busy = _UPDATE_BUSY_RE.search(line)
            if busy and busy.group(1) == appid and i > last_success:
                update_active = True
            missing = _SCHEDULER_MISSING_RE.search(line)
            if missing and missing.group(1) == appid:
                missing_idx = i
            state = _STATE_CHANGED_RE.search(line)
            if state and state.group(1) == appid:
                last_state = state.group(2)
                if (
                    "Update Running" in last_state or "Update Started" in last_state
                ) and i > last_success:
                    update_active = True

    files_corrupt = corrupt_idx is not None and corrupt_idx > last_success
    update_suspended = suspended_idx is not None and suspended_idx > last_success
    missing_game_files = missing_idx is not None and missing_idx > last_success
    update_delayed = "Update delayed for" in last_state
    manifest_pending_stale = (
        last_success >= 0
        and "Fully Installed" in last_state
        and "Update Running" not in last_state
        and "Update Started" not in last_state
        and not update_active
    )

    return {
        "files_corrupt": files_corrupt,
        "update_suspended_while_running": update_suspended,
        "update_active": update_active,
        "update_delayed": update_delayed,
        "manifest_pending_stale": manifest_pending_stale,
        "missing_game_files": missing_game_files,
    }


def content_log_health(appid: str, lines: list[str]) -> tuple[bool, bool]:
    """Return (files_corrupt, update_suspended_while_running) from content_log lines."""
    parsed = parse_content_log(appid, lines)
    return parsed["files_corrupt"], parsed["update_suspended_while_running"]


def _effective_pending_bytes(health: dict) -> tuple[int, int]:
    """Manifest pending bytes adjusted using content_log (stale counters are common)."""
    if health.get("manifest_pending_stale"):
        return 0, 0
    return (
        int(health.get("pending_download_bytes") or 0),
        int(health.get("pending_stage_bytes") or 0),
    )


def steam_update_needs_attention(health: dict, *, running: bool = False) -> bool:
    """True when a real in-progress or broken update needs user action."""
    if health.get("missing_game_files"):
        return True
    if health.get("update_suspended_while_running"):
        return True
    if health.get("update_delayed") and not health.get("update_active"):
        return False
    threshold = 5 if running else 20
    pending, stage = _effective_pending_bytes(health)
    pending_mb = pending / 1024**2
    stage_mb = stage / 1024**2
    if pending_mb <= threshold and stage_mb <= threshold:
        return False
    if health.get("update_active"):
        return True
    return not health.get("manifest_pending_stale")


def steam_update_summary_parts(health: dict) -> list[str]:
    """Human-readable update issue fragments (generic, any AppID)."""
    parts: list[str] = []
    if health.get("update_suspended_while_running"):
        parts.append("update paused while the game was running")
    if health.get("missing_game_files"):
        parts.append("Steam reported missing game files on the last update attempt")
    pending, stage = _effective_pending_bytes(health)
    pending_mb = pending / 1024**2
    stage_mb = stage / 1024**2
    if pending_mb > 0:
        parts.append(f"{pending_mb:.0f} MB download still pending")
    if stage_mb > 0:
        parts.append(f"{stage_mb:.0f} MB still staging")
    return parts


def steam_install_health(appid: str, *, cache: bool = True) -> dict:
    """Parse Steam manifest + content_log for corrupt files / stalled updates."""
    now = time.monotonic()
    if cache:
        hit = _STEAM_HEALTH_CACHE.get(appid)
        if hit and now - hit[0] < _STEAM_HEALTH_TTL:
            return hit[1]

    manifest_path = steam_root() / "steamapps" / f"appmanifest_{appid}.acf"
    ints: dict[str, int] = {}
    if manifest_path.is_file():
        try:
            for key, val in _MANIFEST_INT.findall(manifest_path.read_text(errors="ignore")):
                if key in {
                    "BytesToDownload",
                    "BytesDownloaded",
                    "BytesToStage",
                    "BytesStaged",
                    "UpdateResult",
                    "StateFlags",
                }:
                    ints[key] = int(val)
        except OSError:
            pass

    to_dl = ints.get("BytesToDownload", 0)
    downloaded = ints.get("BytesDownloaded", 0)
    pending = max(0, to_dl - downloaded)
    to_stage = ints.get("BytesToStage", 0)
    staged = ints.get("BytesStaged", 0)
    pending_stage = max(0, to_stage - staged)
    shader_path = shader_cache_dir(appid)
    shader_bytes = _shader_cache_bytes(appid)

    recent = _cached_content_log_lines()
    log_flags = parse_content_log(appid, recent)
    eff_pending = 0 if log_flags["manifest_pending_stale"] else pending
    eff_stage = 0 if log_flags["manifest_pending_stale"] else pending_stage

    result = {
        "appid": appid,
        "files_corrupt": log_flags["files_corrupt"],
        "pending_download_bytes": pending,
        "pending_stage_bytes": pending_stage,
        "effective_pending_download_bytes": eff_pending,
        "effective_pending_stage_bytes": eff_stage,
        "update_queued": eff_pending > 0 or eff_stage > 0,
        "update_active": log_flags["update_active"],
        "update_delayed": log_flags["update_delayed"],
        "manifest_pending_stale": log_flags["manifest_pending_stale"],
        "missing_game_files": log_flags["missing_game_files"],
        "update_suspended_while_running": log_flags["update_suspended_while_running"],
        "update_result": ints.get("UpdateResult"),
        "shader_cache_bytes": shader_bytes,
        "shader_cache_path": str(shader_path) if shader_path.is_dir() else None,
    }
    if cache:
        _STEAM_HEALTH_CACHE[appid] = (now, result)
    return result


def game_install_dir(appid: str) -> Path:
    meta = game_meta(appid)
    idir = (meta.get("installdir") or "").strip()
    if idir:
        return steam_root() / "steamapps" / "common" / idir
    return steam_root() / "steamapps" / "common"


def game_compat_dir(appid: str) -> Path:
    return steam_root() / "steamapps" / "compatdata" / appid


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


def _norm_cpu(raw: float) -> float:
    threads = psutil.cpu_count(logical=True) or 1
    return round(min(100.0, raw / threads), 1)


def _collect_process_snapshot() -> tuple[set[str], dict[str, set[int]], list[dict]]:
    """Single psutil pass: active AppIDs, overlay PID map, rows for classification."""
    active_appids: set[str] = set()
    overlay_map: dict[str, set[int]] = {}
    rows: list[dict] = []

    for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
            cmd = " ".join(proc.info["cmdline"] or [])
            mi = proc.info["memory_info"]
            raw_cpu = proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if cmd:
            for match in APPID_RE.finditer(cmd):
                active_appids.add(match.group(1))
            compat = COMPAT_RE.search(cmd)
            if compat:
                active_appids.add(compat.group(1))
            gid = GAMEID_RE.search(cmd)
            if gid:
                active_appids.add(gid.group(1))

        if "gameoverlayui" in name.lower() and cmd:
            gid_m = GAMEID_RE.search(cmd)
            pid_m = OVERLAY_PID_RE.search(cmd)
            if gid_m and pid_m:
                overlay_map.setdefault(gid_m.group(1), set()).add(int(pid_m.group(1)))

        rows.append(
            {
                "pid": pid,
                "name": name,
                "cmd": cmd,
                "memory_info": mi,
                "raw_cpu": raw_cpu,
            }
        )

    return active_appids, overlay_map, rows


def scan_active_appids() -> set[str]:
    active, _, _ = _collect_process_snapshot()
    return active


def scan_overlay_game_pids() -> dict[str, set[int]]:
    _, overlay_map, _ = _collect_process_snapshot()
    return overlay_map


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
                val = entry[len(prefix) :].decode("utf-8", errors="ignore").strip()
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


def _candidate_appids_for_proc(
    cmd: str,
    pid: int,
    exe_l: str,
    active_appids: set[str],
    overlay_map: dict[str, set[int]],
    metas: dict[str, dict],
    env_cache: dict[int, str | None],
    cwd_cache: dict[int, str | None],
) -> set[str]:
    """Narrow AppID checks before expensive classify (env/cwd reads)."""
    candidates: set[str] = set()
    cl = cmd.lower().replace("\\", "/")
    cl_compact = cl.replace(" ", "")

    for appid in active_appids:
        aid = appid.lower()
        if f"compatdata/{aid}" in cl or f"appid={aid}" in cl_compact:
            candidates.add(appid)
            continue
        installdir = metas.get(appid, {}).get("installdir", "")
        if installdir:
            idir = installdir.lower().replace("\\", "/")
            if f"common/{idir}" in cl:
                candidates.add(appid)
                continue
        override = GAME_OVERRIDES.get(appid, {})
        main_exes = override.get("main_exe")
        if main_exes and exe_l in main_exes:
            candidates.add(appid)
            continue
        if overlay_map.get(appid) and pid in overlay_map[appid]:
            candidates.add(appid)

    if pid not in env_cache:
        env_cache[pid] = _proc_steam_appid(pid)
    env_appid = env_cache[pid]
    if env_appid and env_appid in active_appids:
        candidates.add(env_appid)

    if _is_game_binary(exe_l):
        if pid not in cwd_cache:
            cwd_cache[pid] = _proc_cwd(pid)
        cwd = cwd_cache[pid]
        if cwd:
            for appid, meta in metas.items():
                if _cwd_matches_installdir(cwd, meta.get("installdir", "")):
                    candidates.add(appid)
    return candidates


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
    active_appids, overlay_map, proc_rows = _collect_process_snapshot()
    if not active_appids:
        return {}

    buckets: dict[str, list[dict]] = {appid: [] for appid in active_appids}
    metas = {appid: game_meta(appid) for appid in active_appids}
    env_cache: dict[int, str | None] = {}
    cwd_cache: dict[int, str | None] = {}

    for row in proc_rows:
        pid = row["pid"]
        name = row["name"]
        cmd = row["cmd"]
        mi = row["memory_info"]
        raw_cpu = row["raw_cpu"]
        name_l = name.lower()
        exe_l = _effective_exe_name(name, cmd)
        if name_l in SKIP_PROCS or exe_l in SKIP_PROCS or exe_l in AUXILIARY_EXES:
            continue

        candidates = _candidate_appids_for_proc(
            cmd,
            pid,
            exe_l,
            active_appids,
            overlay_map,
            metas,
            env_cache,
            cwd_cache,
        )
        if not candidates:
            continue

        display_name = exe_l if _is_game_binary(exe_l) else name
        proc_row = {
            "pid": pid,
            "name": display_name,
            "cpu_threads_pct": round(raw_cpu, 1),
            "cpu_pct": _norm_cpu(raw_cpu),
            "rss_mb": round(mi.rss / 1024**2, 1) if mi else 0,
        }

        for appid in candidates:
            tier = _classify_proc(
                appid,
                name,
                cmd,
                metas[appid],
                pid=pid,
                overlay_pids=overlay_map.get(appid),
                env_cache=env_cache,
                cwd_cache=cwd_cache,
            )
            if tier:
                buckets[appid].append({**proc_row, "tier": tier})

    out: dict[str, dict] = {}
    for appid, meta in metas.items():
        rows = buckets[appid]
        rows.sort(
            key=lambda x: (
                0 if x["tier"] == "main" else 1 if x["tier"] == "child" else 2,
                -x["rss_mb"],
            )
        )
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
    """Warm psutil cpu_percent baseline for game processes (one detect_games pass)."""
    detect_games()


def running_game_ids(state: dict[str, dict]) -> list[str]:
    return [gid for gid, g in state.items() if g.get("running")]


def primary_active_game(state: dict[str, dict]) -> dict | None:
    running = [g for g in state.values() if g.get("running")]
    if not running:
        return None
    return max(running, key=lambda g: (g.get("cpu_pct") or 0, g.get("rss_mb") or 0))


def installed_appids() -> list[str]:
    steamapps = steam_root() / "steamapps"
    if not steamapps.is_dir():
        return list(GAME_OVERRIDES.keys())
    ids = [
        p.name.removeprefix("appmanifest_").removesuffix(".acf")
        for p in steamapps.glob("appmanifest_*.acf")
    ]
    return sorted(set(ids) | set(GAME_OVERRIDES.keys()))
