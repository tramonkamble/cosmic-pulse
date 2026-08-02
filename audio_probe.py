# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""PipeWire / PulseAudio pipeline probe for gaming Guidance.

Cheap, cached (~20s). Not on the 1 Hz metrics path — only for rule packs /
diagnostics / Guidance open.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Idle sinks are normally SUSPENDED under PipeWire — not an error.
_ODD_RATES = frozenset({8000, 11025, 16000, 22050, 32000, 88200, 96000, 176400, 192000})
_OK_RATES = frozenset({44100, 48000})

# Latency (ms) = quantum / rate * 1000
_LARGE_QUANTUM_MS = 20.0  # soft info for gaming (1024@48k ≈ 21 ms)
_VERY_LARGE_QUANTUM_MS = 40.0

# Pop/Ubuntu stock default.clock.min-quantum is 32 — clients can request
# tiny buffers and crackle under gaming load (common community report).
_STOCK_MIN_QUANTUM = 32
_SAFE_MIN_QUANTUM = 256  # common gaming floor

_BT_RE = re.compile(r"bluez|bluetooth", re.I)
_HDMI_RE = re.compile(r"hdmi|displayport|dp\b|navi.*hdmi|hda ati hdmi", re.I)
_USB_RE = re.compile(r"\busb\b|usb-audio|schiit|dac|headset|headphone", re.I)
_META_KV = re.compile(
    r"key:'(?P<key>[^']+)'\s+value:'(?P<val>[^']*)'",
    re.I,
)
_CONF_CLOCK_RE = re.compile(
    r"default\.clock\.(?P<key>rate|quantum|min-quantum|max-quantum)\s*=\s*(?P<val>\d+)",
    re.I,
)
_CONF_PULSE_MIN_RE = re.compile(
    r"pulse\.min\.quantum\s*=\s*(?P<num>\d+)\s*/\s*(?P<den>\d+)",
    re.I,
)
_CONF_CTX_PROPS_RE = re.compile(r"\bcontext\.properties\s*=", re.I)
_PRIO_BLOCK_RE = re.compile(
    r"matches\s*=\s*\[(?P<body>.*?)\]\s*actions\s*=\s*\{(?P<act>.*?)\n\s*\}",
    re.I | re.S,
)
_PRIO_SESSION_RE = re.compile(r"priority\.session\s*=\s*(\d+)", re.I)
_NODE_NAME_RE = re.compile(r'node\.name\s*=\s*"([^"]+)"', re.I)
_DEVICE_NAME_RE = re.compile(r'device\.name\s*=\s*"([^"]+)"', re.I)

_cache: tuple[float, dict[str, Any]] = (0.0, {})
_CACHE_TTL = 20.0


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        return subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return ""


def _parse_pw_settings() -> dict[str, Any]:
    """clock.rate / clock.quantum from `pw-metadata -n settings`."""
    out: dict[str, Any] = {}
    if not shutil.which("pw-metadata"):
        return out
    text = _run(["pw-metadata", "-n", "settings"], timeout=3)
    for m in _META_KV.finditer(text):
        key = m.group("key")
        val = m.group("val")
        if key in (
            "clock.rate",
            "clock.quantum",
            "clock.min-quantum",
            "clock.max-quantum",
            "clock.force-quantum",
            "clock.force-rate",
        ):
            try:
                out[key.split(".", 1)[-1].replace("-", "_")] = int(val)
            except ValueError:
                out[key.split(".", 1)[-1].replace("-", "_")] = val
        elif key == "clock.allowed-rates":
            nums = [int(x) for x in re.findall(r"\d+", val)]
            out["allowed_rates"] = nums
    # Normalize keys we care about
    rate = out.get("rate")
    quantum = out.get("quantum")
    if isinstance(rate, int) and isinstance(quantum, int) and rate > 0:
        out["latency_ms"] = round(1000.0 * quantum / rate, 2)
    return out


def _pactl_server() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if not shutil.which("pactl"):
        return info
    text = _run(["pactl", "info"], timeout=3)
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "Server Name":
            info["server_name"] = v
            info["pipewire"] = "pipewire" in v.lower()
            info["pulse_native"] = "pulseaudio" in v.lower() and "pipewire" not in v.lower()
        elif k == "Server Version":
            info["server_version"] = v
        elif k == "Default Sample Specification":
            info["default_spec"] = v
            # e.g. float32le 2ch 48000Hz
            m = re.search(r"(\d+)\s*Hz", v, re.I)
            if m:
                info["default_rate"] = int(m.group(1))
        elif k == "Default Sink":
            info["default_sink"] = v
        elif k == "Default Source":
            info["default_source"] = v
    return info


def _classify_sink(name: str, desc: str) -> dict[str, bool]:
    blob = f"{name} {desc}"
    return {
        "bluetooth": bool(_BT_RE.search(blob)),
        "hdmi": bool(_HDMI_RE.search(blob)),
        "usb_or_dac": bool(_USB_RE.search(blob)) or "usb-" in name.lower(),
    }


def _is_listening_alt(sink: dict[str, Any]) -> bool:
    """True if sink is a plausible game/headset output (not SPDIF-only junk)."""
    if sink.get("bluetooth") or sink.get("hdmi"):
        return False
    if sink.get("usb_or_dac"):
        return True
    name = (sink.get("name") or "").lower()
    desc = (sink.get("description") or "").lower()
    if "analog" in name or "analog" in desc:
        return True
    if "headphone" in desc or "headset" in desc:
        return True
    # Digital-only motherboard outs — not a useful alt for "switch off HDMI"
    if "iec958" in name or "spdif" in name or "digital stereo" in desc:
        return False
    return False


def _pactl_sinks() -> list[dict[str, Any]]:
    sinks: list[dict[str, Any]] = []
    if not shutil.which("pactl"):
        return sinks
    text = _run(["pactl", "list", "sinks"], timeout=5)
    if not text:
        return sinks
    cur: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("Sink #"):
            if cur:
                sinks.append(cur)
            cur = {
                "index": line.split("#", 1)[-1].strip(),
                "name": "",
                "description": "",
                "state": "",
                "rate": None,
                "channels": None,
            }
            continue
        if not cur:
            continue
        s = line.strip()
        if s.startswith("Name:"):
            cur["name"] = s.split(":", 1)[1].strip()
        elif s.startswith("Description:"):
            cur["description"] = s.split(":", 1)[1].strip()
        elif s.startswith("State:"):
            cur["state"] = s.split(":", 1)[1].strip().upper()
        elif s.startswith("Sample Specification:"):
            spec = s.split(":", 1)[1].strip()
            cur["spec"] = spec
            m = re.search(r"(\d+)ch", spec)
            if m:
                cur["channels"] = int(m.group(1))
            m = re.search(r"(\d+)\s*Hz", spec, re.I)
            if m:
                cur["rate"] = int(m.group(1))
    if cur:
        sinks.append(cur)
    for s in sinks:
        flags = _classify_sink(s.get("name") or "", s.get("description") or "")
        s.update(flags)
    return sinks


def _conf_search_paths() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".config" / "pipewire",
        home / ".config" / "wireplumber",
        Path("/etc/pipewire"),
        Path("/etc/wireplumber"),
    ]
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if p.suffix in (".conf", ".yml", ".yaml") and p.is_file():
                    paths.append(p)
        except OSError:
            continue
    return paths


def _scan_pipewire_conf() -> dict[str, Any]:
    """Parse user/system drop-ins for known-bad Pop/PipeWire patterns."""
    clock: dict[str, int] = {}
    pulse_min_nums: list[int] = []
    ctx_props_blocks = 0
    conf_files: list[str] = []
    user_conf = False
    for path in _conf_search_paths():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        conf_files.append(str(path))
        if str(Path.home()) in str(path):
            user_conf = True
        ctx_props_blocks += len(_CONF_CTX_PROPS_RE.findall(text))
        for m in _CONF_CLOCK_RE.finditer(text):
            key = m.group("key").replace("-", "_")
            try:
                clock[key] = int(m.group("val"))
            except ValueError:
                pass
        for m in _CONF_PULSE_MIN_RE.finditer(text):
            try:
                pulse_min_nums.append(int(m.group("num")))
            except ValueError:
                pass

    # Multiple context.properties = { } in one drop-in can overwrite earlier
    # clock settings (second block wins). Count only user files for the smell.
    multi_ctx = False
    for path in _conf_search_paths():
        if str(Path.home()) not in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(_CONF_CTX_PROPS_RE.findall(text)) >= 2:
            multi_ctx = True
            break

    pulse_min = min(pulse_min_nums) if pulse_min_nums else None
    return {
        "user_conf_present": user_conf,
        "conf_files": conf_files[:12],
        "conf_rate": clock.get("rate"),
        "conf_quantum": clock.get("quantum"),
        "conf_min_quantum": clock.get("min_quantum"),
        "conf_max_quantum": clock.get("max_quantum"),
        "conf_pulse_min_quantum": pulse_min,
        "conf_multi_context_properties": multi_ctx,
        "conf_ctx_props_blocks": ctx_props_blocks,
    }


def _scan_wireplumber_hdmi_priority() -> dict[str, Any]:
    """Detect conf that ranks HDMI higher than a USB DAC (gaming trap)."""
    hdmi_prio: int | None = None
    usb_prio: int | None = None
    for path in _conf_search_paths():
        if "wireplumber" not in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Crude block walk: priority near hdmi/usb name hints
        for block in re.split(r"\{\s*matches", text):
            prio_m = _PRIO_SESSION_RE.search(block)
            if not prio_m:
                continue
            prio = int(prio_m.group(1))
            blob = block.lower()
            if "hdmi" in blob or "displayport" in blob:
                hdmi_prio = max(hdmi_prio or 0, prio)
            if (
                "usb-" in blob
                or "schiit" in blob
                or "dac" in blob
                or "headset" in blob
                or "headphone" in blob
            ):
                usb_prio = max(usb_prio or 0, prio)
    return {
        "conf_hdmi_priority": hdmi_prio,
        "conf_usb_priority": usb_prio,
        "conf_hdmi_over_usb_priority": bool(
            hdmi_prio is not None
            and usb_prio is not None
            and hdmi_prio > usb_prio
        ),
    }


def _recent_xrun_hints() -> dict[str, Any]:
    """Cheap journal scan for underrun/xrun mentions (last ~2h)."""
    if not shutil.which("journalctl"):
        return {"xrun_mentions": 0, "sample": None}
    text = _run(
        [
            "journalctl",
            "--user",
            "-u",
            "pipewire",
            "-u",
            "pipewire-pulse",
            "-u",
            "wireplumber",
            "--since",
            "2 hours ago",
            "-p",
            "warning",
            "--no-pager",
            "-n",
            "80",
        ],
        timeout=4,
    )
    if not text:
        # system journal fallback (some installs)
        text = _run(
            [
                "journalctl",
                "-u",
                "pipewire",
                "--since",
                "2 hours ago",
                "-p",
                "warning",
                "--no-pager",
                "-n",
                "40",
            ],
            timeout=4,
        )
    hits = []
    for line in text.splitlines():
        low = line.lower()
        if "xrun" in low or "underrun" in low or "overrun" in low:
            hits.append(line.strip()[:200])
    return {
        "xrun_mentions": len(hits),
        "sample": hits[0] if hits else None,
    }


def probe_audio(*, force: bool = False) -> dict[str, Any]:
    """Snapshot of the audio graph relevant to gaming stutter / routing."""
    global _cache
    now = time.time()
    if not force and _cache[1] and now - _cache[0] < _CACHE_TTL:
        return dict(_cache[1])

    server = _pactl_server()
    settings = _parse_pw_settings()
    sinks = _pactl_sinks()
    xruns = _recent_xrun_hints()
    conf = _scan_pipewire_conf()
    wp_prio = _scan_wireplumber_hdmi_priority()

    default_name = server.get("default_sink") or ""
    default = next((s for s in sinks if s.get("name") == default_name), None)
    if not default and default_name:
        default = {
            "name": default_name,
            "description": default_name,
            "state": "UNKNOWN",
            **_classify_sink(default_name, default_name),
        }

    rate = settings.get("rate") or server.get("default_rate")
    if default and default.get("rate") and not rate:
        rate = default["rate"]

    quantum = settings.get("quantum")
    latency_ms = settings.get("latency_ms")
    if latency_ms is None and isinstance(rate, int) and isinstance(quantum, int) and rate > 0:
        latency_ms = round(1000.0 * quantum / rate, 2)

    other_sinks = [s for s in sinks if s.get("name") != default_name]
    # Prefer real listening devices over unused SPDIF/IEC958 motherboard outs
    listening_alts = [s for s in other_sinks if _is_listening_alt(s)]

    default_missing = not bool(default_name)
    # Name set but not in sink list (device gone / profile off)
    default_not_listed = bool(default_name) and not any(
        s.get("name") == default_name for s in sinks
    )
    state = ((default or {}).get("state") or "").upper()
    # SUSPENDED / IDLE / RUNNING are normal PipeWire states — not errors
    default_unavailable = default_not_listed or state in (
        "ERROR",
        "UNLINKED",
        "INIT",
    )

    rate_odd = bool(rate) and int(rate) not in _OK_RATES
    rate_very_odd = bool(rate) and int(rate) in _ODD_RATES

    large_quantum = (
        latency_ms is not None and float(latency_ms) >= _LARGE_QUANTUM_MS
    )
    very_large_quantum = (
        latency_ms is not None and float(latency_ms) >= _VERY_LARGE_QUANTUM_MS
    )

    min_quantum = settings.get("min_quantum")
    # Stock Pop/Ubuntu: min-quantum 32 lets games request tiny buffers → crackles
    stock_min_quantum = (
        isinstance(min_quantum, int) and min_quantum <= _STOCK_MIN_QUANTUM
    )
    # Conf asks for a safer floor but live graph still has stock min
    conf_min = conf.get("conf_min_quantum")
    conf_not_applied = bool(
        conf_min
        and isinstance(min_quantum, int)
        and conf_min >= _SAFE_MIN_QUANTUM
        and min_quantum < conf_min
    )
    # Aggressive pulse min (≤256) is the common Ubuntu crackling default under load
    pulse_min = conf.get("conf_pulse_min_quantum")
    aggressive_pulse_min = pulse_min is not None and int(pulse_min) <= 256
    multi_ctx = bool(conf.get("conf_multi_context_properties"))

    default_bt = bool(default and default.get("bluetooth"))
    default_hdmi = bool(default and default.get("hdmi"))
    # Gaming-relevant: HDMI/monitor is default while a USB DAC / analog/headset exists.
    # Ignore orphan SPDIF/IEC958 digital outs — they are not a realistic game path.
    hdmi_over_dac = default_hdmi and bool(listening_alts)
    alt_sink = (listening_alts or [None])[0]
    hdmi_prio_conf = bool(wp_prio.get("conf_hdmi_over_usb_priority"))

    backend = "none"
    if server.get("pipewire"):
        backend = "pipewire"
    elif server.get("pulse_native"):
        backend = "pulse"
    elif shutil.which("pipewire") or shutil.which("pw-cli"):
        backend = "pipewire-missing-pactl"
    elif shutil.which("pulseaudio"):
        backend = "pulse-missing-pactl"

    result: dict[str, Any] = {
        "present": backend in ("pipewire", "pulse") or bool(sinks),
        "backend": backend,
        "pipewire": backend == "pipewire" or bool(server.get("pipewire")),
        "server_name": server.get("server_name"),
        "server_version": server.get("server_version"),
        "default_rate": int(rate) if rate else None,
        "quantum": int(quantum) if quantum is not None else None,
        "min_quantum": int(min_quantum) if min_quantum is not None else None,
        "max_quantum": settings.get("max_quantum"),
        "force_quantum": settings.get("force_quantum"),
        "latency_ms": latency_ms,
        # Pop stock / conf-health signals
        "stock_min_quantum": stock_min_quantum,
        "conf_not_applied": conf_not_applied,
        "conf_min_quantum": conf_min,
        "conf_quantum": conf.get("conf_quantum"),
        "conf_pulse_min_quantum": pulse_min,
        "aggressive_pulse_min": aggressive_pulse_min,
        "conf_multi_context_properties": multi_ctx,
        "user_conf_present": bool(conf.get("user_conf_present")),
        "conf_hdmi_over_usb_priority": hdmi_prio_conf,
        "conf_hdmi_priority": wp_prio.get("conf_hdmi_priority"),
        "conf_usb_priority": wp_prio.get("conf_usb_priority"),
        "allowed_rates": settings.get("allowed_rates") or [],
        "default_sink": default_name or None,
        "default_sink_desc": (default or {}).get("description") or default_name or None,
        "default_sink_state": (default or {}).get("state") or None,
        "default_source": server.get("default_source"),
        "sink_count": len(sinks),
        "sinks": [
            {
                "name": s.get("name"),
                "description": s.get("description"),
                "state": s.get("state"),
                "rate": s.get("rate"),
                "bluetooth": bool(s.get("bluetooth")),
                "hdmi": bool(s.get("hdmi")),
                "usb_or_dac": bool(s.get("usb_or_dac")),
            }
            for s in sinks
        ],
        "default_missing": default_missing,
        "default_not_listed": default_not_listed,
        "default_unavailable": default_unavailable or default_not_listed,
        "default_bluetooth": default_bt,
        "default_hdmi": default_hdmi,
        "hdmi_over_alt": hdmi_over_dac,
        "alt_sink_name": (alt_sink or {}).get("name") if alt_sink else None,
        "alt_sink_desc": (alt_sink or {}).get("description") if alt_sink else None,
        "rate_odd": rate_odd,
        "rate_very_odd": rate_very_odd,
        "large_quantum": large_quantum,
        "very_large_quantum": very_large_quantum,
        "xrun_mentions": int(xruns.get("xrun_mentions") or 0),
        "xrun_sample": xruns.get("sample"),
        "xruns_recent": int(xruns.get("xrun_mentions") or 0) > 0,
        "probed_at": now,
    }
    _cache = (now, result)
    return dict(result)


def invalidate_audio_cache() -> None:
    global _cache
    _cache = (0.0, {})


def audio_metrics() -> dict[str, Any]:
    """Flat metrics for rule-pack detect / templates (audio.*)."""
    a = probe_audio()
    return {
        "present": bool(a.get("present")),
        "backend": a.get("backend") or "none",
        "pipewire": bool(a.get("pipewire")),
        "default_rate": a.get("default_rate") or 0,
        "quantum": a.get("quantum") or 0,
        "latency_ms": float(a.get("latency_ms") or 0),
        "default_sink": a.get("default_sink") or "",
        "default_sink_desc": a.get("default_sink_desc") or "no sink",
        "default_sink_state": a.get("default_sink_state") or "",
        "sink_count": int(a.get("sink_count") or 0),
        "default_missing": bool(a.get("default_missing")),
        "default_unavailable": bool(a.get("default_unavailable")),
        "default_bluetooth": bool(a.get("default_bluetooth")),
        "default_hdmi": bool(a.get("default_hdmi")),
        "hdmi_over_alt": bool(a.get("hdmi_over_alt")),
        "alt_sink_name": a.get("alt_sink_name") or "",
        "alt_sink_desc": a.get("alt_sink_desc") or "",
        "rate_odd": bool(a.get("rate_odd")),
        "rate_very_odd": bool(a.get("rate_very_odd")),
        "large_quantum": bool(a.get("large_quantum")),
        "very_large_quantum": bool(a.get("very_large_quantum")),
        "min_quantum": int(a.get("min_quantum") or 0),
        "stock_min_quantum": bool(a.get("stock_min_quantum")),
        "conf_not_applied": bool(a.get("conf_not_applied")),
        "conf_min_quantum": int(a.get("conf_min_quantum") or 0),
        "conf_quantum": int(a.get("conf_quantum") or 0),
        "conf_pulse_min_quantum": int(a.get("conf_pulse_min_quantum") or 0),
        "aggressive_pulse_min": bool(a.get("aggressive_pulse_min")),
        "conf_multi_context_properties": bool(a.get("conf_multi_context_properties")),
        "user_conf_present": bool(a.get("user_conf_present")),
        "conf_hdmi_over_usb_priority": bool(a.get("conf_hdmi_over_usb_priority")),
        "xrun_mentions": int(a.get("xrun_mentions") or 0),
        "xruns_recent": bool(a.get("xruns_recent")),
        "xrun_sample": a.get("xrun_sample") or "",
    }
