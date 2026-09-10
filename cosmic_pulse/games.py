# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dynamic Steam game detection — AppID from launch context, PIDs from process tree."""

from __future__ import annotations

import os
import re
import threading
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


def _prune_stale_cache(
    cache: dict[str, tuple[float, object]], ttl: float, *, now: float | None = None
) -> None:
    """Drop expired cache entries so AppID keys do not accumulate forever."""
    ts = time.monotonic() if now is None else now
    for key in [k for k, (cached_at, _) in cache.items() if ts - cached_at >= ttl]:
        del cache[key]


HOME = Path.home()

APPID_RE = re.compile(r"AppId=(\d+)", re.I)
COMPAT_RE = re.compile(r"compatdata[/\\](\d+)", re.I)
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
_PACK_DATA_LOCK = threading.Lock()


def _load_legacy_game_ids() -> dict[str, str]:
    global _LEGACY_ID_CACHE
    if _LEGACY_ID_CACHE is not None:
        return _LEGACY_ID_CACHE
    with _PACK_DATA_LOCK:
        if _LEGACY_ID_CACHE is not None:
            return _LEGACY_ID_CACHE
        try:
            from .rule_packs import get_legacy_game_ids

            _LEGACY_ID_CACHE = get_legacy_game_ids()
        except Exception:
            return {}
        return _LEGACY_ID_CACHE


def _load_game_overrides() -> dict[str, dict]:
    global _GAME_OVERRIDE_CACHE
    if _GAME_OVERRIDE_CACHE is not None:
        return _GAME_OVERRIDE_CACHE
    with _PACK_DATA_LOCK:
        if _GAME_OVERRIDE_CACHE is not None:
            return _GAME_OVERRIDE_CACHE
        try:
            from .rule_packs import get_game_overrides

            _GAME_OVERRIDE_CACHE = get_game_overrides()
        except Exception:
            return {}
        return _GAME_OVERRIDE_CACHE


class _LazyDict:
    """Dict-like view loaded from rule packs on first access."""

    __slots__ = ("_loader", "_cache", "_lock")

    def __init__(self, loader):
        self._loader = loader
        self._cache: dict | None = None
        self._lock = threading.Lock()

    def _data(self) -> dict:
        if self._cache is not None:
            return self._cache
        with self._lock:
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
    with _PACK_DATA_LOCK:
        _GAME_OVERRIDE_CACHE = None
        _LEGACY_ID_CACHE = None
    for view in (LEGACY_GAME_IDS, GAME_OVERRIDES):
        with view._lock:
            view._cache = None


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


_LIB_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')
_library_cache: tuple[float, tuple[Path, ...]] | None = None


def _parse_libraryfolders_vdf(path: Path) -> list[Path]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    out: list[Path] = []
    for match in _LIB_PATH_RE.finditer(text):
        raw = match.group(1).replace("\\\\", "/").replace("\\", "/")
        p = Path(raw)
        if p.is_dir():
            out.append(p)
    return out


def steam_library_roots() -> list[Path]:
    """Steam install + extra libraries from libraryfolders.vdf."""
    global _library_cache
    root = steam_root()
    vdfs = (
        root / "steamapps" / "libraryfolders.vdf",
        root / "config" / "libraryfolders.vdf",
    )
    mtime = 0.0
    for vdf in vdfs:
        try:
            if vdf.is_file():
                mtime = max(mtime, vdf.stat().st_mtime)
        except OSError:
            pass
    if _library_cache and _library_cache[0] == mtime:
        return list(_library_cache[1])
    seen: set[str] = set()
    roots: list[Path] = []

    def _add(p: Path) -> None:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        if not (p / "steamapps").is_dir() and not p.is_dir():
            return
        seen.add(key)
        roots.append(p)

    _add(root)
    for vdf in vdfs:
        if vdf.is_file():
            for extra in _parse_libraryfolders_vdf(vdf):
                _add(extra)
    _library_cache = (mtime, tuple(roots))
    return list(roots)


def steamapps_dirs() -> list[Path]:
    return [r / "steamapps" for r in steam_library_roots() if (r / "steamapps").is_dir()]


def find_appmanifest(appid: str) -> Path | None:
    name = f"appmanifest_{appid}.acf"
    for sa in steamapps_dirs():
        path = sa / name
        if path.is_file():
            return path
    return None


def clear_steam_library_cache() -> None:
    global _library_cache
    _library_cache = None
    _read_manifest.cache_clear()


_LOCALCONFIG_CACHE: tuple[float, str] = (0.0, "")
_STEAM_ID64_BASE = 76561197960265728


WAYLAND_X11_LAUNCH_OPTS = (
    "PROTON_ENABLE_WAYLAND=0 PROTON_USE_WAYLAND=0 SDL_VIDEODRIVER=x11 %command%"
)


def session_is_wayland() -> bool:
    st = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if st == "wayland":
        return True
    if st == "x11":
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


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
        "proton_enable_wayland=0" in o or "proton_use_wayland=0" in o or "sdl_videodriver=x11" in o
    )


def _env_blob_has_wayland_fix(blob: bytes) -> bool:
    low = blob.lower()
    return (
        b"proton_enable_wayland=0" in low
        or b"proton_use_wayland=0" in low
        or b"sdl_videodriver=x11" in low
    )


def proc_has_wayland_fix(pid: int | None, *, depth: int = 0) -> bool:
    """True when pid or its parents already export the Wayland→X11 launch override."""
    if not pid or depth > 8:
        return False
    blob = _proc_environ_blob(pid)
    if blob and _env_blob_has_wayland_fix(blob):
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        ppid = int(stat.split()[3])
    except (OSError, ValueError, IndexError):
        return False
    return proc_has_wayland_fix(ppid, depth=depth + 1)


def _proc_environ_blob(pid: int) -> bytes:
    try:
        return Path(f"/proc/{pid}/environ").read_bytes().replace(b"\0", b" ")
    except OSError:
        return b""


def proc_uses_proton(pid: int | None, *, depth: int = 0) -> bool:
    """True when pid or its parents show an active Proton/Wine game session."""
    if not pid or depth > 8:
        return False
    blob = _proc_environ_blob(pid)
    if blob:
        wine = b"WINEDLLPATH" in blob or any(k in blob for k in STEAM_ENV_APPID_KEYS)
        if wine and (
            b"STEAM_COMPAT_PROTON=" in blob
            or b"STEAM_COMPAT_DATA_PATH=" in blob
            or b"STEAM_COMPAT_CLIENT=" in blob
        ):
            return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        ppid = int(stat.split()[3])
    except (OSError, ValueError, IndexError):
        return False
    return proc_uses_proton(ppid, depth=depth + 1)


def game_uses_proton(
    appid: str | None,
    primary_pid: int | None,
    *,
    primary_name: str | None = None,
) -> bool:
    """Proton/Wine session — env walk plus compatdata when metering a .exe title."""
    if proc_uses_proton(primary_pid):
        return True
    if not appid:
        return False
    compat = steam_root() / "steamapps" / "compatdata" / str(appid)
    if compat.is_dir() and (primary_name or "").lower().endswith(".exe"):
        return True
    return False


def _indent_launch_options_line(block: str) -> str:
    for line in block.splitlines():
        if line.strip().startswith('"') and "LaunchOptions" not in line:
            m = re.match(r"^(\s+)", line)
            if m:
                return m.group(1)
    for line in block.splitlines():
        m = re.match(r"^(\s+)", line)
        if m:
            return m.group(1)
    return "\t\t\t\t\t\t"


def set_steam_launch_options(appid: str | None, options: str) -> dict:
    """Write per-game LaunchOptions into Steam localconfig.vdf (user-owned, no sudo)."""
    aid = (appid or "").strip()
    opts = (options or "").strip()
    if not aid:
        return {"ok": False, "message": "No Steam AppID — launch the game from Steam first."}
    if not opts:
        return {"ok": False, "message": "Launch options string is empty."}
    path = _steam_localconfig_path()
    if not path:
        return {
            "ok": False,
            "message": "Steam localconfig not found — sign into Steam on this machine.",
        }
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        return {"ok": False, "message": f"Cannot read Steam config: {exc}"}
    block = _extract_vdf_block(text, aid)
    if not block:
        return {
            "ok": False,
            "message": f"App {aid} not in Steam config — launch once from Steam, then retry.",
        }
    escaped = opts.replace("\\", "\\\\").replace('"', '\\"')
    if re.search(r'"LaunchOptions"\s*"', block):
        new_block = re.sub(
            r'"LaunchOptions"\s*"[^"]*"',
            f'"LaunchOptions"\t\t"{escaped}"',
            block,
            count=1,
        )
    else:
        indent = _indent_launch_options_line(block)
        trimmed = block.rstrip()
        if trimmed.endswith("}"):
            trimmed = trimmed[:-1].rstrip()
        close = indent[:-1] if len(indent) > 0 else ""
        new_block = f'{trimmed}\n{indent}"LaunchOptions"\t\t"{escaped}"\n{close}}}'
    if new_block == block:
        return {"ok": True, "message": "Launch options already set.", "path": str(path)}
    new_text = text.replace(block, new_block, 1)
    backup = path.with_suffix(path.suffix + ".bak.pulse")
    try:
        if path.exists():
            backup.write_text(text, encoding="utf-8")
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "message": f"Cannot write Steam config: {exc}"}
    global _LOCALCONFIG_CACHE
    _LOCALCONFIG_CACHE = (0.0, "")
    return {
        "ok": True,
        "message": "Saved Steam launch options — restart the game for the X11 override.",
        "path": str(path),
        "backup": str(backup),
    }


def game_session_launch_metrics(
    appid: str | None,
    primary_pid: int | None = None,
    *,
    primary_name: str | None = None,
) -> dict[str, bool | str]:
    """Proton session + whether Wayland→X11 override is missing in Steam and runtime."""
    opts = steam_launch_options(appid)
    fix_in_opts = launch_has_wayland_fix(opts)
    fix_runtime = proc_has_wayland_fix(primary_pid)
    return {
        "proton": game_uses_proton(appid, primary_pid, primary_name=primary_name),
        "wayland_fix_missing": not (fix_in_opts or fix_runtime),
        "wayland_fix_in_launch_options": fix_in_opts,
        "wayland_fix_runtime": fix_runtime,
        "launch_options": opts,
    }


def _short_name(name: str) -> str:
    words = (name or "").split()
    if len(words) <= 3:
        return name
    return " ".join(words[:3])


@lru_cache(maxsize=256)
def _read_manifest(appid: str) -> dict[str, str]:
    path = find_appmanifest(appid)
    if not path or not path.is_file():
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


_STEAM_ASSET_CDN = "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps"
_STEAM_LEGACY_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"


def steam_art_urls(appid: str) -> list[str]:
    """Steam CDN art candidates — newer titles often lack header.jpg (use library_hero)."""
    appid = normalize_game_id(appid) or appid
    if not appid or not str(appid).isdigit():
        return []
    base = f"{_STEAM_ASSET_CDN}/{appid}"
    return [
        f"{base}/library_hero.jpg",
        f"{base}/header.jpg",
        f"{base}/capsule_616x353.jpg",
        f"{_STEAM_LEGACY_CDN}/{appid}/header.jpg",
    ]


def build_games_catalog() -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for steamapps in steamapps_dirs():
        for path in steamapps.glob("appmanifest_*.acf"):
            appid = path.name.removeprefix("appmanifest_").removesuffix(".acf")
            if appid in catalog:
                continue
            meta = game_meta(appid)
            catalog[appid] = {
                "name": meta["name"],
                "short": meta["short"],
                "appid": appid,
                "art_urls": steam_art_urls(appid),
            }
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
    clear_steam_library_cache()


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
    _prune_stale_cache(_SHADER_SIZE_CACHE, _SHADER_SIZE_TTL, now=now)
    cached = _SHADER_SIZE_CACHE.get(appid)
    if cached and now - cached[0] < _SHADER_SIZE_TTL:
        return cached[1]
    size = _dir_size_bytes(shader_cache_dir(appid))
    _SHADER_SIZE_CACHE[appid] = (now, size)
    return size


def shader_cache_dir(appid: str) -> Path:
    for sa in steamapps_dirs():
        path = sa / "shadercache" / str(appid)
        if path.is_dir():
            return path
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
        _prune_stale_cache(_STEAM_HEALTH_CACHE, _STEAM_HEALTH_TTL, now=now)
        hit = _STEAM_HEALTH_CACHE.get(appid)
        if hit and now - hit[0] < _STEAM_HEALTH_TTL:
            return hit[1]

    manifest_path = find_appmanifest(appid)
    ints: dict[str, int] = {}
    if manifest_path and manifest_path.is_file():
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
        for sa in steamapps_dirs():
            path = sa / "common" / idir
            if path.is_dir():
                return path
        return steamapps_dirs()[0] / "common" / idir if steamapps_dirs() else steam_root() / "steamapps" / "common" / idir
    return steam_root() / "steamapps" / "common"


def game_compat_dir(appid: str) -> Path:
    for sa in steamapps_dirs():
        path = sa / "compatdata" / str(appid)
        if path.is_dir():
            return path
    return steam_root() / "steamapps" / "compatdata" / str(appid)


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
    """Context dict for hints and game-scoped Guidance."""
    gt = game_totals or {}
    appid = gt.get("game_id") if gt.get("running") else None
    paths = game_data_paths(appid)
    if appid and gt.get("game_name"):
        paths["name"] = gt["game_name"]
    return paths


def _norm_cpu(raw: float) -> float:
    threads = psutil.cpu_count(logical=True) or 1
    return round(min(100.0, raw / threads), 1)


# Process-tree walks are decoupled from the 1 Hz metrics loop (auditor: CACHE_TTL_SEC).
# Max delay to notice a newly launched game ≈ this TTL.
CACHE_TTL_SEC = 3.0
_EMPTY_SNAPSHOT_TTL = CACHE_TTL_SEC
_empty_snapshot_cache: tuple[float, tuple[set[str], dict[str, set[int]], list]] | None = None

# Name-first filter: never open cmdline/environ for every PID on the box.
# Launch helpers carry AppId=; game binaries use .exe / .x86_64 / pack main_exe.
# Avoid bare "steam" so steamwebhelper (dozens of procs) is not scanned.
GAME_RUNTIME_NAME_RE = re.compile(
    r"(^reaper$|wine|proton|gamemode|mangohud|pressure-vessel|"
    r"gameoverlayui|pv-adverb|srt-bwrap|steam-runtime|steam-launch|"
    r"steamlaunch|compatdata"
    r"|\.x86_64$|\.x86$|\.exe$|\.bin$)",
    re.IGNORECASE,
)

# Cheap substring gates before regex — most desktop /proc rows never match.
_APPID_CMD_HINTS = (
    "AppId=",
    "AppID=",
    "appid=",
    "compatdata/",
    "compatdata\\",
    "-gameid",
    "-gameId",
    "SteamAppId",
    "SteamGameId",
    "STEAM_COMPAT_APP_ID",
)


def _cmd_has_appid_hint(cmd: str) -> bool:
    """True if cmdline is worth running AppID regexes on."""
    if not cmd:
        return False
    # Case variants covered by explicit tokens + one lower pass for -gameid
    if any(h in cmd for h in _APPID_CMD_HINTS):
        return True
    cl = cmd.lower()
    return "compatdata/" in cl or "compatdata\\" in cl or "gameid" in cl or "appid=" in cl


def _extract_appids_from_cmd(cmd: str, active: set[str]) -> bool:
    """Parse AppIDs from a Steam/Proton cmdline into *active*. Returns True if any found."""
    if not _cmd_has_appid_hint(cmd):
        return False
    found = False
    for match in APPID_RE.finditer(cmd):
        active.add(match.group(1))
        found = True
    compat = COMPAT_RE.search(cmd)
    if compat:
        active.add(compat.group(1))
        found = True
    gid = GAMEID_RE.search(cmd)
    if gid:
        active.add(gid.group(1))
        found = True
    return found


def _is_overlay_proc(name: str) -> bool:
    return "gameoverlayui" in (name or "").lower()


def _worth_enriching(name: str, cmd: str) -> bool:
    """Keep only Steam/Proton/game-like rows for memory_info + cpu_percent.

    Launch helpers (reaper, proton) are used for AppID discovery only and are
    not metered — they stay out of the phase-2 list.
    """
    nl = (name or "").lower()
    if not nl and not cmd:
        return False
    if _is_overlay_proc(nl):
        return False  # overlay maps PIDs; not a metered game process
    if nl in SKIP_PROCS or nl in AUXILIARY_EXES:
        return False
    if _is_game_binary(nl):
        return True
    cl = (cmd or "").lower().replace("\\", "/")
    if not cl:
        return False
    # Install / Proton paths — native Linux titles under steamapps/common
    if "steamapps/" in cl or "compatdata/" in cl:
        return True
    if "proton" in cl or "steam-runtime" in cl or "pressure-vessel" in cl:
        # Helpers only — real game binaries usually also match .exe / common/
        if _is_game_binary(_exe_basename_from_cmdline(cmd)):
            return True
        # Still keep waitforexitandrun children often look like wine + path
        if ".exe" in cl or "/common/" in cl:
            return True
        return False
    if "wine" in nl or nl.startswith("wine"):
        return True
    # Short Wine names sometimes appear only in cmdline basename
    if _is_game_binary(_exe_basename_from_cmdline(cmd)):
        return True
    return False


def _main_exe_name_set() -> set[str]:
    """Lowercase main_exe basenames from enabled pack game_overrides."""
    names: set[str] = set()
    try:
        for ov in GAME_OVERRIDES.values():
            if not isinstance(ov, dict):
                continue
            main = ov.get("main_exe") or []
            if isinstance(main, str):
                main = [main]
            for m in main:
                if m:
                    names.add(str(m).lower())
    except Exception:
        return names
    return names


def _name_warrants_cmdline(name: str, *, main_exes: set[str] | None = None) -> bool:
    """True if we should open cmdline (and maybe environ) for this process name.

    Fast path: process_iter only requests pid+name. Full attributes are gated here
    so desktop noise never pays a /proc cmdline read.
    """
    if not name:
        return False
    nl = name.lower()
    if GAME_RUNTIME_NAME_RE.search(name):
        return True
    if _is_game_binary(nl):
        return True
    if main_exes is not None and nl in main_exes:
        return True
    return False


def _collect_process_snapshot() -> tuple[set[str], dict[str, set[int]], list[dict]]:
    """Discover Steam AppIDs and (only if any) enrich game-like proc rows.

    Performance (auditor-aligned):
    1. One ``process_iter(['pid', 'name'])`` — keep the ``proc`` handle.
    2. Open cmdline only when the **name** looks like a gaming runtime / binary /
       pack ``main_exe`` (see ``_name_warrants_cmdline``).
    3. If AppIDs appear, a second pass over the *same* list opens cmdline for
       remaining native titles under steamapps (e.g. factorio).
    4. memory_info / cpu_percent on the retained ``proc`` (no second ``Process(pid)``).
    5. Empty snapshots reuse ``CACHE_TTL_SEC`` cache.

    AppID extractors (``_extract_appids_from_cmd``, overlay -gameid, etc.) unchanged.
    """
    global _empty_snapshot_cache
    now = time.time()
    if _empty_snapshot_cache is not None:
        cached_at, cached = _empty_snapshot_cache
        if now - cached_at < _EMPTY_SNAPSHOT_TTL and not cached[0]:
            return cached[0], cached[1], cached[2]

    active_appids: set[str] = set()
    overlay_map: dict[str, set[int]] = {}
    # (proc, pid, name, cmd) — cmd empty until we open it
    pending: list[tuple[object, int, str]] = []
    opened: dict[int, tuple[object, str, str]] = {}
    light: list[tuple[object, int, str, str]] = []
    main_exes = _main_exe_name_set()

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.info["pid"]
            name = proc.info["name"] or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        pending.append((proc, pid, name))

    def _open_cmd(proc, pid: int, name: str) -> str:
        try:
            cmdline = proc.cmdline() or []
            return " ".join(cmdline) if cmdline else ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return ""

    def _ingest(proc, pid: int, name: str, cmd: str) -> None:
        opened[pid] = (proc, name, cmd)
        _extract_appids_from_cmd(cmd, active_appids)
        if _is_overlay_proc(name):
            gid_m = GAMEID_RE.search(cmd)
            pid_m = OVERLAY_PID_RE.search(cmd)
            if gid_m and pid_m:
                try:
                    overlay_map.setdefault(gid_m.group(1), set()).add(int(pid_m.group(1)))
                except ValueError:
                    pass
            return
        if _worth_enriching(name, cmd):
            light.append((proc, pid, name, cmd))

    for proc, pid, name in pending:
        if not _name_warrants_cmdline(name, main_exes=main_exes):
            continue
        cmd = _open_cmd(proc, pid, name)
        if not cmd:
            continue
        _ingest(proc, pid, name, cmd)

    for appid in overlay_map:
        active_appids.add(appid)

    # Native Steam titles with plain names — only when an AppID is already live.
    if active_appids:
        for proc, pid, name in pending:
            if pid in opened:
                continue
            nl = (name or "").lower()
            if not nl or nl in SKIP_PROCS or nl in AUXILIARY_EXES:
                continue
            if _is_overlay_proc(nl):
                continue
            if "." in nl and not _is_game_binary(nl):
                continue
            cmd = _open_cmd(proc, pid, name)
            if not cmd:
                continue
            cl = cmd.lower().replace("\\", "/")
            if "steamapps/" not in cl and "compatdata/" not in cl:
                continue
            _ingest(proc, pid, name, cmd)

    if not active_appids:
        empty: tuple[set[str], dict[str, set[int]], list] = (set(), {}, [])
        _empty_snapshot_cache = (now, empty)
        return empty

    _empty_snapshot_cache = None
    rows: list[dict] = []
    for proc, pid, name, cmd in light:
        try:
            with proc.oneshot():
                mi = proc.memory_info()
                raw_cpu = proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
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


# Detect result cache — always CACHE_TTL_SEC (idle and in-game). Metrics stay 1 Hz.
_detect_result_cache: tuple[float, dict[str, dict]] | None = None


def invalidate_detect_games_cache() -> None:
    """Drop throttled detect cache and empty /proc snapshot cache."""
    global _detect_result_cache, _empty_snapshot_cache
    _detect_result_cache = None
    _empty_snapshot_cache = None


def _detect_games_uncached() -> dict[str, dict]:
    """Process snapshot + classification (no rate throttle)."""
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


def detect_games(*, force: bool = False) -> dict[str, dict]:
    """Return per-AppID running state for Steam-launched games.

    Process-tree scans are cached for ``CACHE_TTL_SEC`` (default 3s) so the 1 Hz
    metrics sampler does not re-walk /proc every tick. Pass ``force=True`` to
    bypass (e.g. prime_game_cpu).
    """
    global _detect_result_cache
    now = time.time()
    if not force and _detect_result_cache is not None:
        cached_at, cached_state = _detect_result_cache
        if (now - cached_at) < CACHE_TTL_SEC:
            return cached_state

    state = _detect_games_uncached()
    _detect_result_cache = (now, state)
    return state


def prime_game_cpu() -> None:
    """Warm psutil cpu_percent baseline for game processes (one detect_games pass)."""
    detect_games(force=True)


def running_game_ids(state: dict[str, dict]) -> list[str]:
    return [gid for gid, g in state.items() if g.get("running")]


def primary_active_game(state: dict[str, dict]) -> dict | None:
    running = [g for g in state.values() if g.get("running")]
    if not running:
        return None
    return max(running, key=lambda g: (g.get("cpu_pct") or 0, g.get("rss_mb") or 0))


GAME_LINGER_SEC = 10.0
_game_linger: dict | None = None


def reset_game_linger() -> None:
    """Clear linger state (tests / session boundaries)."""
    global _game_linger
    _game_linger = None


def primary_active_game_with_linger(
    state: dict[str, dict],
    now: float | None = None,
) -> dict | None:
    """Hold the active game visible briefly after its PID vanishes (Proton load gaps)."""
    global _game_linger
    ts = time.time() if now is None else now
    live = primary_active_game(state)

    if live and live.get("running"):
        snap = dict(live)
        snap.pop("lingering", None)
        snap.pop("linger_remaining_sec", None)
        _game_linger = {"last_live_ts": ts, "game": snap}
        return snap

    if not _game_linger:
        return None

    age = ts - _game_linger["last_live_ts"]
    if age >= GAME_LINGER_SEC:
        _game_linger = None
        return None

    stale = dict(_game_linger["game"])
    stale["running"] = True
    stale["lingering"] = True
    stale["linger_remaining_sec"] = round(max(0.0, GAME_LINGER_SEC - age), 1)
    stale["primary_pid"] = None
    stale["cpu_pct"] = 0.0
    stale["rss_mb"] = 0.0
    stale["tree_rss_mb"] = 0.0
    stale["proc_count"] = 0
    stale["procs"] = []
    return stale


def installed_appids() -> list[str]:
    ids: set[str] = set()
    for steamapps in steamapps_dirs():
        for p in steamapps.glob("appmanifest_*.acf"):
            ids.add(p.name.removeprefix("appmanifest_").removesuffix(".acf"))
    return sorted(ids)
