# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Memory probe: DMI Unknown + known G.Skill Flare X5 part."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmic_pulse.probe_memory import (
    apply_part_db,
    lookup_part_prefix,
    normalize_manufacturer,
    parse_dmidecode,
)


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


def test_memory_makers_beyond_gskill() -> None:
    assert normalize_manufacturer("Corsair") == "Corsair"
    assert normalize_manufacturer("Kingston") == "Kingston"
    assert normalize_manufacturer("Crucial Technology") == "Crucial"
    assert normalize_manufacturer("Patriot Memory") == "Patriot"
    assert normalize_manufacturer("TeamGroup") == "TeamGroup"
    assert normalize_manufacturer("ADATA") == "ADATA"
    assert lookup_part_prefix("CMK32GX5M2B6000C30")["manufacturer"] == "Corsair"
    assert lookup_part_prefix("KF560C36-16")["kit"] == "Fury Beast"
    assert lookup_part_prefix("CT16G48C40U5.C8FF")["manufacturer"] == "Crucial"
    assert lookup_part_prefix("PVVR532G600C30")["manufacturer"] == "Patriot"
    corsair = apply_part_db(
        parse_dmidecode(
            """
Handle 0x003A, DMI type 17, 92 bytes
Memory Device
	Size: 16 GB
	Type: DDR5
	Speed: 4800 MT/s
	Manufacturer: Unknown
	Part Number: CMK32GX5M2B6000C30
	Configured Memory Speed: 4800 MT/s
"""
        )
    )
    assert corsair["manufacturer"] == "Corsair"
    assert corsair["kit"] == "Vengeance"
    assert corsair["rated_mts"] == 6000


def test_cache_path_matches_collectors() -> None:
    from cosmic_pulse.collectors import MEMORY_CACHE
    from cosmic_pulse.paths import data_dir
    from cosmic_pulse.probe_memory import memory_cache_path, probe_script_path

    assert memory_cache_path() == data_dir() / ".memory_cache.json"
    assert MEMORY_CACHE == memory_cache_path()
    script = probe_script_path()
    assert script.name == "probe_memory.py"
    assert script.parent.name == "cosmic_pulse"
    assert script.is_file()
    # Package move left no root shim — API/UI must not point here.
    assert not (script.parent.parent / "probe_memory.py").exists()


def test_http_api_probes_package_script() -> None:
    src = (Path(__file__).resolve().parents[1] / "cosmic_pulse" / "http_api.py").read_text(
        encoding="utf-8"
    )
    assert "ROOT / \"probe_memory.py\"" not in src
    assert "probe_script_path" in src


def run_all() -> None:
    test_dmi_gskill_flare_x5_keeps_live_4800()
    test_blank_manufacturer_not_unknown()
    test_enrich_from_existing_cache_shape()
    test_cache_path_matches_collectors()
    test_memory_makers_beyond_gskill()
    test_http_api_probes_package_script()
    print("test_probe_memory: ok")


if __name__ == "__main__":
    run_all()
