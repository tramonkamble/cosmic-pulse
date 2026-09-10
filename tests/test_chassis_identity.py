# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Chassis tile identity: System76 vs Dell vs DIY desktop."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.benchmarks import chassis_identity


def test_system76_thelio():
    d = chassis_identity("thelio-major-b4-n2", "pop-os", "System76")
    assert d["kind"] == "system76"
    assert d["brand"] == "System76"
    assert "thelio" in d["model"].lower()


def test_dell_xps():
    d = chassis_identity("XPS 15 9520", "xps-15", "Dell Inc.")
    assert d["kind"] == "oem"
    assert d["brand"] == "Dell"
    assert "XPS" in d["model"]
    assert d["brand"] != "System76"


def test_lenovo_thinkpad():
    d = chassis_identity("ThinkPad T14s Gen 3", "t14s", "LENOVO")
    assert d["brand"] == "Lenovo"
    assert d["kind"] == "oem"


def test_framework():
    d = chassis_identity("Laptop 13 (AMD Ryzen 7040Series)", "fw13", "Framework")
    assert d["brand"] == "Framework"
    assert d["kind"] == "oem"


def test_asus_zephyrus_laptop_not_desktop():
    d = chassis_identity("ROG Zephyrus G16", "g16", "ASUSTeK COMPUTER INC.")
    assert d["kind"] == "oem"
    assert d["brand"] == "ASUS"


def test_personal_build_asus_board():
    d = chassis_identity(
        "System Product Name (System Version)",
        "pop-os",
        "ASUSTeK COMPUTER INC.",
        "ROG STRIX B650-A GAMING WIFI",
    )
    assert d["kind"] == "desktop"
    assert d["brand"] is None
    assert "STRIX" in d["model"] or "B650" in d["model"]


def test_personal_build_junk_dmi_falls_to_hostname():
    d = chassis_identity(
        "To Be Filled By O.E.M.",
        "workshop",
        "To Be Filled By O.E.M.",
        "Default string",
    )
    assert d["kind"] == "desktop"
    assert d["brand"] is None
    assert d["model"] == "workshop"


def run_all() -> None:
    test_system76_thelio()
    test_dell_xps()
    test_lenovo_thinkpad()
    test_framework()
    test_asus_zephyrus_laptop_not_desktop()
    test_personal_build_asus_board()
    test_personal_build_junk_dmi_falls_to_hostname()
    print("test_chassis_identity: ok")


if __name__ == "__main__":
    run_all()
