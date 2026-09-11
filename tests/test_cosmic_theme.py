# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""COSMIC dark/light pack loading."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.cosmic_theme import get_cosmic_theme, get_cosmic_theme_pack, load_cosmic_theme


def test_force_dark_and_light_differ():
    dark = load_cosmic_theme(force="dark")
    light = load_cosmic_theme(force="light")
    assert dark["is_dark"] is True
    assert light["is_dark"] is False
    assert dark["bg"] != light["bg"]
    assert light["text"] != dark["text"]


def test_share_pack_without_user_config():
    """Packaged COSMIC Light/Dark still load if ~/.config/cosmic is missing."""
    from cosmic_pulse import cosmic_theme as ct

    orig = ct.COSMIC_ROOT
    ct.COSMIC_ROOT = Path("/tmp/pulse-no-cosmic-home")
    ct._THEME_CACHE = {}
    ct._LAST_MTIME = -1.0
    try:
        light = ct.load_cosmic_theme(force="light")
        dark = ct.load_cosmic_theme(force="dark")
        assert light["is_dark"] is False
        assert dark["is_dark"] is True
        share_light = Path("/usr/share/cosmic/com.system76.CosmicTheme.Light/v1/background")
        if share_light.is_file():
            assert light["available"] is True
            assert light["bg"] != "#1b1b1b"
    finally:
        ct.COSMIC_ROOT = orig
        ct._THEME_CACHE = {}
        ct._LAST_MTIME = -1.0


def test_pack_has_auto_dark_light():
    pack = get_cosmic_theme_pack()
    assert set(pack) >= {"auto", "dark", "light"}
    assert pack["dark"]["is_dark"] is True
    assert pack["light"]["is_dark"] is False
    auto = get_cosmic_theme()
    assert auto["is_dark"] in (True, False)
    assert auto["bg"] in (pack["dark"]["bg"], pack["light"]["bg"])


def run_all() -> None:
    test_force_dark_and_light_differ()
    test_share_pack_without_user_config()
    test_pack_has_auto_dark_light()
    print("test_cosmic_theme: ok")


if __name__ == "__main__":
    run_all()
