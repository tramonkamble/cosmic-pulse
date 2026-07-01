"""Steam game registry and process detection for Pulse."""

from __future__ import annotations

from pathlib import Path

import psutil

HOME = Path.home()
STEAM = HOME / ".local/share/Steam"

SKIP_PROCS = frozenset({
    "wineserver", "winedevice.exe", "wineboot.exe", "wine64-preloader", "wine-preloader",
    "crashpad_handler", "crashpad_handle", "xalia.exe", "steam.exe", "steamwebhelper",
    "fossilize_replay.exe", "reaper", "explorer.exe", "tabtip.exe", "sh", "python3",
    "python", "systemd", "gamemoded", "gamemoderun", "srt-bwrap",
})

GAMES: dict[str, dict] = {
    "cities2": {
        "id": "cities2",
        "name": "Cities II",
        "short": "Cities II",
        "appid": "949230",
        "main_exe": frozenset({"cities2.exe", "citiesskylinesii.exe", "citiesii.exe"}),
        "compat": f"compatdata/949230",
    },
    "counterstrike2": {
        "id": "counterstrike2",
        "name": "Counter-Strike 2",
        "short": "CS2",
        "appid": "730",
        "main_exe": frozenset({"cs2.exe"}),
        "compat": "compatdata/730",
    },
}

ALL_GAME_IDS = list(GAMES.keys())


def _classify_proc(game_id: str, name: str, cmd: str) -> str | None:
    meta = GAMES[game_id]
    name_l = (name or "").lower()
    if name_l in SKIP_PROCS:
        return None
    if name_l in meta["main_exe"]:
        return "main"
    if meta["compat"] not in cmd and meta["appid"] not in cmd:
        return None
    if name_l.endswith(".exe"):
        return "child"
    return None


def _norm_cpu(raw: float) -> float:
    threads = psutil.cpu_count(logical=True) or 1
    return round(min(100.0, raw / threads), 1)


def detect_games() -> dict[str, dict]:
    """Return per-game running state, processes, and primary stats."""
    buckets: dict[str, list[dict]] = {gid: [] for gid in GAMES}

    for p in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
        try:
            name = p.info["name"] or ""
            cmd = " ".join(p.info["cmdline"] or []).lower()
            mi = p.info["memory_info"]
            for gid, meta in GAMES.items():
                tier = _classify_proc(gid, name, cmd)
                if not tier:
                    continue
                raw_cpu = p.cpu_percent(interval=None)
                buckets[gid].append({
                    "pid": p.info["pid"],
                    "name": name,
                    "tier": tier,
                    "cpu_threads_pct": round(raw_cpu, 1),
                    "cpu_pct": _norm_cpu(raw_cpu),
                    "rss_mb": round(mi.rss / 1024**2, 1) if mi else 0,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    out: dict[str, dict] = {}
    for gid, meta in GAMES.items():
        rows = buckets[gid]
        rows.sort(key=lambda x: (0 if x["tier"] == "main" else 1, -x["rss_mb"]))
        mains = [r for r in rows if r["tier"] == "main"]
        primary_exe = next(iter(meta["main_exe"]))
        primary = next((r for r in mains if r["name"].lower() == primary_exe), mains[0] if mains else None)
        out[gid] = {
            "id": gid,
            "name": meta["name"],
            "short": meta["short"],
            "appid": meta["appid"],
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
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = p.info["name"] or ""
            cmd = " ".join(p.info["cmdline"] or []).lower()
            for gid in GAMES:
                if _classify_proc(gid, name, cmd):
                    p.cpu_percent(interval=None)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def running_game_ids(state: dict[str, dict]) -> list[str]:
    return [gid for gid, g in state.items() if g.get("running")]


def primary_active_game(state: dict[str, dict]) -> dict | None:
    """Prefer Cities II, else highest-RSS running game."""
    if state.get("cities2", {}).get("running"):
        return state["cities2"]
    running = [g for g in state.values() if g.get("running")]
    if not running:
        return None
    return max(running, key=lambda g: g.get("rss_mb") or 0)