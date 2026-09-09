# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Extra Steam library folders from libraryfolders.vdf."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import games


def test_extra_library_manifests_are_visible() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "steam"
        extra = Path(raw) / "extra"
        (root / "steamapps").mkdir(parents=True)
        (extra / "steamapps" / "common" / "Team Fortress 2").mkdir(parents=True)
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            f'''
"libraryfolders"
{{
    "0"
    {{
        "path"		"{root}"
    }}
    "1"
    {{
        "path"		"{extra}"
    }}
}}
'''
        )
        (root / "steamapps" / "appmanifest_570.acf").write_text(
            '"AppState"\n{\n\t"name"\t\t"Dota 2"\n\t"installdir"\t\t"dota 2 beta"\n}\n'
        )
        (extra / "steamapps" / "appmanifest_440.acf").write_text(
            '"AppState"\n{\n\t"name"\t\t"Team Fortress 2"\n\t"installdir"\t\t"Team Fortress 2"\n}\n'
        )
        orig = games.steam_root
        games.steam_root = lambda: root
        games.clear_steam_library_cache()
        try:
            ids = games.installed_appids()
            assert "570" in ids
            assert "440" in ids
            cat = games.build_games_catalog()
            assert cat["440"]["name"] == "Team Fortress 2"
            assert games.find_appmanifest("440") == extra / "steamapps" / "appmanifest_440.acf"
            assert games.game_install_dir("440") == extra / "steamapps" / "common" / "Team Fortress 2"
        finally:
            games.steam_root = orig
            games.clear_steam_library_cache()


def test_listen_host_loopback_by_default() -> None:
    import server as srv

    old_argv = sys.argv
    old_env = os.environ.get("PULSE_LAN")
    try:
        sys.argv = ["server.py"]
        os.environ.pop("PULSE_LAN", None)
        assert srv.listen_host() == "127.0.0.1"
        sys.argv = ["server.py", "--lan"]
        assert srv.listen_host() == "0.0.0.0"
        sys.argv = ["server.py"]
        os.environ["PULSE_LAN"] = "1"
        assert srv.listen_host() == "0.0.0.0"
    finally:
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("PULSE_LAN", None)
        else:
            os.environ["PULSE_LAN"] = old_env


if __name__ == "__main__":
    test_extra_library_manifests_are_visible()
    test_listen_host_loopback_by_default()
    print("test_steam_libraries: ok")
