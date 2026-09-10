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
    test_pack_has_auto_dark_light()
    print("test_cosmic_theme: ok")


if __name__ == "__main__":
    run_all()
