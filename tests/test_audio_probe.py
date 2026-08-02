# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Audio pipeline probe tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_probe import (
    _classify_sink,
    audio_metrics,
    invalidate_audio_cache,
    probe_audio,
)


def test_classify_sink_flags():
    assert _classify_sink("bluez_output.XX", "WH-1000XM")["bluetooth"]
    assert _classify_sink("alsa_output.pci-0000_03_00.1.hdmi-stereo", "Navi HDMI")["hdmi"]
    assert _classify_sink(
        "alsa_output.usb-Schiit_Audio_Schiit_Hel_-00.analog-stereo",
        "Schiit Hel+",
    )["usb_or_dac"]


def test_probe_audio_live_smoke():
    invalidate_audio_cache()
    a = probe_audio(force=True)
    assert "backend" in a
    assert "default_rate" in a
    assert "sinks" in a
    assert isinstance(a["sinks"], list)
    m = audio_metrics()
    assert "latency_ms" in m
    assert "hdmi_over_alt" in m


def test_hdmi_over_alt_detection():
    invalidate_audio_cache()
    fake_info = """
Server Name: PulseAudio (on PipeWire 1.5.0)
Server Version: 15.0.0
Default Sample Specification: float32le 2ch 48000Hz
Default Sink: alsa_output.pci-0000_03_00.1.hdmi-stereo
Default Source: alsa_input.usb-Schiit.analog-stereo
"""
    fake_sinks = """
Sink #1
	State: SUSPENDED
	Name: alsa_output.pci-0000_03_00.1.hdmi-stereo
	Description: Navi 31 HDMI/DP Audio Digital Stereo (HDMI)
	Sample Specification: s32le 2ch 48000Hz
Sink #2
	State: SUSPENDED
	Name: alsa_output.usb-Schiit_Audio_Schiit_Hel_-00.analog-stereo
	Description: Schiit Hel+ DAC/Amp (Gaming) Analog Stereo
	Sample Specification: s32le 2ch 48000Hz
"""
    fake_meta = """
Found "settings" metadata 32
update: id:0 key:'clock.rate' value:'48000' type:''
update: id:0 key:'clock.quantum' value:'1024' type:''
"""

    def fake_run(cmd, timeout=4.0):
        if cmd[:2] == ["pactl", "info"]:
            return fake_info
        if cmd[:3] == ["pactl", "list", "sinks"]:
            return fake_sinks
        if cmd[:2] == ["pw-metadata", "-n"]:
            return fake_meta
        if cmd and cmd[0] == "journalctl":
            return ""
        return ""

    with mock.patch("audio_probe._run", side_effect=fake_run):
        with mock.patch("audio_probe.shutil.which", return_value="/usr/bin/x"):
            a = probe_audio(force=True)

    assert a["default_hdmi"] is True
    assert a["hdmi_over_alt"] is True
    assert a["large_quantum"] is True
    assert a["default_rate"] == 48000
    assert a["quantum"] == 1024
    assert "Schiit" in (a.get("alt_sink_desc") or "")
    assert a["rate_odd"] is False


def test_stock_min_and_conf_not_applied():
    """Pop stock min-quantum=32 with user conf asking for 256."""
    invalidate_audio_cache()
    fake_info = """
Server Name: PulseAudio (on PipeWire 1.5.0)
Default Sample Specification: float32le 2ch 48000Hz
Default Sink: alsa_output.pci-0000_03_00.1.hdmi-stereo
"""
    fake_sinks = """
Sink #1
	State: SUSPENDED
	Name: alsa_output.pci-0000_03_00.1.hdmi-stereo
	Description: Navi HDMI
	Sample Specification: s32le 2ch 48000Hz
"""
    fake_meta = """
update: id:0 key:'clock.rate' value:'48000' type:''
update: id:0 key:'clock.quantum' value:'1024' type:''
update: id:0 key:'clock.min-quantum' value:'32' type:''
update: id:0 key:'clock.max-quantum' value:'2048' type:''
"""
    conf = {
        "user_conf_present": True,
        "conf_files": ["/home/u/.config/pipewire/pipewire.conf.d/x.conf"],
        "conf_rate": 48000,
        "conf_quantum": 512,
        "conf_min_quantum": 256,
        "conf_max_quantum": 1024,
        "conf_pulse_min_quantum": 256,
        "conf_multi_context_properties": True,
        "conf_ctx_props_blocks": 2,
    }

    def fake_run(cmd, timeout=4.0):
        if cmd[:2] == ["pactl", "info"]:
            return fake_info
        if cmd[:3] == ["pactl", "list", "sinks"]:
            return fake_sinks
        if cmd[:2] == ["pw-metadata", "-n"]:
            return fake_meta
        if cmd and cmd[0] == "journalctl":
            return ""
        return ""

    with mock.patch("audio_probe._run", side_effect=fake_run):
        with mock.patch("audio_probe.shutil.which", return_value="/usr/bin/x"):
            with mock.patch("audio_probe._scan_pipewire_conf", return_value=conf):
                with mock.patch(
                    "audio_probe._scan_wireplumber_hdmi_priority",
                    return_value={
                        "conf_hdmi_priority": 3000,
                        "conf_usb_priority": 2000,
                        "conf_hdmi_over_usb_priority": True,
                    },
                ):
                    a = probe_audio(force=True)

    assert a["stock_min_quantum"] is True
    assert a["conf_not_applied"] is True
    assert a["conf_multi_context_properties"] is True
    assert a["conf_hdmi_over_usb_priority"] is True
    assert a["min_quantum"] == 32


def test_odd_rate_and_bluetooth():
    invalidate_audio_cache()
    fake_info = """
Server Name: PulseAudio (on PipeWire 1.0)
Default Sample Specification: float32le 2ch 96000Hz
Default Sink: bluez_output.AA_BB
"""
    fake_sinks = """
Sink #3
	State: RUNNING
	Name: bluez_output.AA_BB
	Description: Bluetooth Headset
	Sample Specification: s16le 2ch 96000Hz
"""
    fake_meta = """
update: id:0 key:'clock.rate' value:'96000' type:''
update: id:0 key:'clock.quantum' value:'256' type:''
"""

    def fake_run(cmd, timeout=4.0):
        if cmd[:2] == ["pactl", "info"]:
            return fake_info
        if cmd[:3] == ["pactl", "list", "sinks"]:
            return fake_sinks
        if cmd[:2] == ["pw-metadata", "-n"]:
            return fake_meta
        if cmd and cmd[0] == "journalctl":
            return "Jul 30 pipewire: XRun on node foo"
        return ""

    with mock.patch("audio_probe._run", side_effect=fake_run):
        with mock.patch("audio_probe.shutil.which", return_value="/usr/bin/x"):
            a = probe_audio(force=True)

    assert a["default_bluetooth"] is True
    assert a["rate_odd"] is True
    assert a["xruns_recent"] is True
    assert a["latency_ms"] is not None
    assert a["latency_ms"] < 20  # 256@96k ≈ 2.7 ms


if __name__ == "__main__":
    test_classify_sink_flags()
    test_probe_audio_live_smoke()
    test_hdmi_over_alt_detection()
    test_stock_min_and_conf_not_applied()
    test_odd_rate_and_bluetooth()
    print("all ok")
