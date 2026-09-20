# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Steam library-cache art lookup is sandboxed to numeric AppIDs."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse import games


def _steam_tree(tmp: Path) -> Path:
    steam = tmp / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    cache = steam / "appcache" / "librarycache" / "730"
    cache.mkdir(parents=True)
    (cache / "library_600x900.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (cache / "library_hero.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    return steam


def test_cdn_urls_need_numeric_appid() -> None:
    assert games.steam_art_urls("730")
    assert any("library_600x900" in u for u in games.steam_art_urls("730", kind="capsule"))
    assert any("library_hero" in u for u in games.steam_art_urls("730", kind="hero"))
    assert games.steam_art_urls("../etc/passwd") == []
    assert games.steam_art_urls("not-an-id") == []
    assert games.steam_art_urls("") == []


def test_local_librarycache_capsule_and_hero() -> None:
    tmp = Path(tempfile.mkdtemp())
    steam = _steam_tree(tmp)
    prev = os.environ.get("STEAM_BASE")
    os.environ["STEAM_BASE"] = str(steam)
    games._library_cache = None
    try:
        cap = games.local_steam_art_path("730", kind="capsule")
        hero = games.local_steam_art_path("730", kind="hero")
        assert cap is not None and cap.name == "library_600x900.jpg"
        assert hero is not None and hero.name == "library_hero.jpg"
        assert games.local_steam_art_path("../730") is None
        assert games.local_steam_art_path("730/../../passwd") is None
        hit = games.game_art_file("730", kind="capsule")
        assert hit and hit[1] == "image/jpeg"
    finally:
        if prev is None:
            os.environ.pop("STEAM_BASE", None)
        else:
            os.environ["STEAM_BASE"] = prev
        games._library_cache = None


def run_all() -> None:
    test_cdn_urls_need_numeric_appid()
    test_local_librarycache_capsule_and_hero()
    print("test_game_art: ok")


if __name__ == "__main__":
    run_all()
