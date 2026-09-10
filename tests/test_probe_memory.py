# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Memory probe: DMI Unknown + known G.Skill Flare X5 part."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.probe_memory import apply_part_db, parse_dmidecode


DMI = """
Handle 0x003A, DMI type 17, 92 bytes
Memory Device
	Array Handle: 0x0039
	Size: 16 GB
	Locator: DIMM 1
	Bank Locator: P0 CHANNEL A
	Type: DDR5
	Speed: 4800 MT/s
	Manufacturer: Unknown
	Part Number: F5-6000J3038F16G
	Configured Memory Speed: 4800 MT/s

Handle 0x003B, DMI type 17, 92 bytes
Memory Device
	Array Handle: 0x0039
	Size: 16 GB
	Locator: DIMM 1
	Bank Locator: P0 CHANNEL B
	Type: DDR5
	Speed: 4800 MT/s
	Manufacturer: Unknown
	Part Number: F5-6000J3038F16G
	Configured Memory Speed: 4800 MT/s

Handle 0x003C, DMI type 17, 92 bytes
Memory Device
	Size: No Module Installed
	Locator: DIMM 2
"""


def test_dmi_gskill_flare_x5_keeps_live_4800():
    spec = apply_part_db(parse_dmidecode(DMI))
    assert spec["manufacturer"] == "G.Skill"
    assert spec["kit"] == "Flare X5"
    assert spec["part"] == "F5-6000J3038F16G"
    assert spec["configured_mts"] == 4800
    assert spec["rated_mts"] == 6000
    assert spec["spd_mts"] == 4800
    assert spec["expo_active"] is False
    assert "kit 6000" in spec["label"]
    assert spec["total_gb"] == 32
    locs = [s["locator"] for s in spec["sticks"]]
    assert len(set(locs)) == 2
    assert all(s["manufacturer"] == "G.Skill" for s in spec["sticks"])


def test_blank_manufacturer_not_unknown():
    spec = parse_dmidecode(DMI)
    assert spec["manufacturer"] is None
    assert all(s["manufacturer"] == "" for s in spec["sticks"])


def test_enrich_from_existing_cache_shape():
    from cosmic_pulse.hardware_probe import enrich_memory_spec

    cached = {
        "source": "dmidecode",
        "confidence": "exact",
        "sticks": [
            {
                "size_gb": 16,
                "mts": 4800,
                "type": "DDR5",
                "manufacturer": "Unknown",
                "part": "F5-6000J3038F16G",
                "locator": "DIMM 1",
            }
        ]
        * 2,
        "total_gb": 32,
        "channels": 2,
        "configured_mts": 4800,
        "speed_mts": 4800,
        "label": "Unknown F5-6000J3038F16G · DDR5-4800 · 2×16GB",
        "manufacturer": "Unknown",
        "part": "F5-6000J3038F16G",
        "kit": "F5-6000J3038F16G",
    }
    out = enrich_memory_spec(cached)
    assert out["manufacturer"] == "G.Skill"
    assert out["kit"] == "Flare X5"
    assert out["configured_mts"] == 4800


def run_all() -> None:
    test_dmi_gskill_flare_x5_keeps_live_4800()
    test_blank_manufacturer_not_unknown()
    test_enrich_from_existing_cache_shape()
    print("test_probe_memory: ok")


if __name__ == "__main__":
    run_all()
