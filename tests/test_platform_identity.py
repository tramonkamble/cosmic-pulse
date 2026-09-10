# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Desktop, GPU stack, and RAM identity for non-AMD / non-KDE hosts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hardware_probe import (
    _FIRST_CLASS_DESKTOPS,
    _is_igpu,
    _normalize_de_id,
    parse_nvidia_smi_csv,
    platform_identity,
)
from probe_memory import apply_part_db, normalize_manufacturer, parse_dmidecode
from rule_packs import _platform_flags


def test_top_seven_gaming_desktops():
    cases = {
        "cosmic": "COSMIC",
        "ubuntu:GNOME": "GNOME",
        "KDE": "KDE Plasma",
        "plasma": "KDE Plasma",
        "X-Cinnamon": "Cinnamon",
        "XFCE": "XFCE",
        "Hyprland": "Hyprland",
        "gamescope-session": "Gamescope",
        "steamos": "Gamescope",
    }
    for raw, label in cases.items():
        de_id, de_label = _normalize_de_id(raw)
        assert de_id in _FIRST_CLASS_DESKTOPS, raw
        assert de_label == label, (raw, de_label)


def test_generic_de_still_surfaces():
    de_id, de_label = _normalize_de_id("LXQt")
    assert de_id == "lxqt"
    assert de_label == "LXQt"


def test_nvidia_smi_csv_parses():
    row = parse_nvidia_smi_csv("12, 34, 2048, 8192, 61, 120.5, 2100, 9001, 45")
    assert row["busy_pct"] == 12
    assert row["vram_used_mb"] == 2048
    assert row["vram_total_mb"] == 8192
    assert row["vram_pct"] == 25.0
    assert row["junction_c"] == 61
    assert row["power_w"] == 120.5
    assert row["fan_pct"] == 45


def test_nvidia_smi_na_fields():
    row = parse_nvidia_smi_csv("0, [N/A], 0, 8192, 42, N/A, 300, 405, [N/A]")
    assert row["busy_pct"] == 0
    assert row["mem_busy_pct"] is None
    assert row["power_w"] is None
    assert row["fan_pct"] is None


def test_intel_igpu_vs_arc():
    assert _is_igpu("8086:A7A1", vram_bytes=0, driver="i915") is True
    assert _is_igpu("8086:56A0", vram_bytes=8 * 1024**3, driver="i915") is False
    assert _is_igpu("1002:164E") is True
    assert _is_igpu("10DE:2684") is False


def test_corsair_dmi_brand_and_ddr4_label():
    dmi = """
Handle 0x003A, DMI type 17, 92 bytes
Memory Device
	Size: 16 GB
	Locator: DIMM_A1
	Type: DDR4
	Speed: 3200 MT/s
	Manufacturer: Corsair
	Part Number: CMK32GX4M2B3200C16
	Configured Memory Speed: 3200 MT/s

Handle 0x003B, DMI type 17, 92 bytes
Memory Device
	Size: 16 GB
	Locator: DIMM_B1
	Type: DDR4
	Speed: 3200 MT/s
	Manufacturer: Corsair
	Part Number: CMK32GX4M2B3200C16
	Configured Memory Speed: 3200 MT/s
"""
    spec = apply_part_db(parse_dmidecode(dmi))
    assert spec["manufacturer"] == "Corsair"
    assert spec["kit"] == "Vengeance"
    assert spec["type"] == "DDR4"
    assert "DDR4-3200" in spec["label"]
    assert spec["total_gb"] == 32


def test_jedec_hex_manufacturer_dropped():
    assert normalize_manufacturer("04CB") is None
    assert normalize_manufacturer("Unknown") is None
    assert normalize_manufacturer("Kingston") == "Kingston"


def test_platform_flags_include_de_and_gpu():
    fake = {
        "is_pop": False,
        "is_cosmic": False,
        "is_system76": False,
        "is_kde": True,
        "is_gnome": False,
        "is_xfce": False,
        "is_cinnamon": False,
        "is_hyprland": False,
        "is_gamescope": False,
        "is_nvidia": True,
        "is_amd_gpu": False,
        "is_intel_gpu": False,
        "gpu_driver": "nvidia",
        "gpu_stack": "nvidia",
        "desktop": {"id": "kde"},
        "gpu": {"vendor": "nvidia", "driver": "nvidia", "stack": "nvidia"},
    }
    with patch("hardware_probe.platform_identity", return_value=fake):
        flags = _platform_flags()
    assert flags["is_kde"] is True
    assert flags["is_nvidia"] is True
    assert flags["gpu_driver"] == "nvidia"
    assert flags["gpu_stack"] == "nvidia"
    assert flags["desktop"] == "kde"


def test_platform_identity_nvidia_badge(monkeypatch=None):
    desktop = {
        "id": "gnome",
        "name": "GNOME",
        "detail": "Wayland",
        "is_cosmic": False,
        "cosmic_available": False,
        "title": "GNOME · wayland",
    }
    gpu = {
        "vendor": "nvidia",
        "driver": "nvidia",
        "stack": "nvidia",
        "pci_id": "10DE:2684",
        "nvidia": {"present": True, "version": "550.54", "name": "RTX 4070", "source": "nvidia-smi"},
        "mesa": {"present": False, "version": None},
    }
    with (
        patch("hardware_probe.detect_running_desktop", return_value=desktop),
        patch("hardware_probe.detect_gpu_stack", return_value=gpu),
        patch("hardware_probe._read_os_release", return_value={"ID": "fedora", "NAME": "Fedora Linux", "PRETTY_NAME": "Fedora Linux 41"}),
        patch("hardware_probe._read_dmi", return_value=""),
    ):
        ident = platform_identity()
    assert ident["is_gnome"] is True
    assert ident["is_nvidia"] is True
    ids = [b["id"] for b in ident["badges"]]
    assert "gnome" in ids
    assert "nvidia" in ids
    assert "mesa" not in ids


def run_all() -> None:
    test_top_seven_gaming_desktops()
    test_generic_de_still_surfaces()
    test_nvidia_smi_csv_parses()
    test_nvidia_smi_na_fields()
    test_intel_igpu_vs_arc()
    test_corsair_dmi_brand_and_ddr4_label()
    test_jedec_hex_manufacturer_dropped()
    test_platform_flags_include_de_and_gpu()
    test_platform_identity_nvidia_badge()
    print("test_platform_identity: ok")


if __name__ == "__main__":
    run_all()
