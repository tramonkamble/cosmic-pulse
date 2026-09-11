# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""CLI flags for server.py / cosmic-pulse."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "server.py"), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_help() -> None:
    proc = _run("--help")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout + proc.stderr
    assert "--lan" in out
    assert "--port" in out
    assert "--open" in out
    assert "--version" in out


def test_version() -> None:
    proc = _run("--version")
    assert proc.returncode == 0, proc.stderr
    from cosmic_pulse.version import read_pyproject_version

    ver = read_pyproject_version(ROOT / "pyproject.toml")
    out = (proc.stdout + proc.stderr).strip()
    assert ver in out, out


def test_parse_args_port() -> None:
    sys.path.insert(0, str(ROOT))
    from cosmic_pulse import server

    args = server.parse_args(["--port", "9999", "--lan"])
    assert args.port == 9999
    assert args.lan is True
    old = os.environ.get("PULSE_PORT")
    old_lan = os.environ.get("PULSE_LAN")
    try:
        server.apply_cli(args)
        assert os.environ.get("PULSE_PORT") == "9999"
        assert os.environ.get("PULSE_LAN") == "1"
        assert server.listen_host() == "0.0.0.0"
    finally:
        if old is None:
            os.environ.pop("PULSE_PORT", None)
        else:
            os.environ["PULSE_PORT"] = old
        if old_lan is None:
            os.environ.pop("PULSE_LAN", None)
        else:
            os.environ["PULSE_LAN"] = old_lan
        server.PORT = int(os.environ.get("PULSE_PORT", "8765"))


if __name__ == "__main__":
    test_help()
    test_version()
    test_parse_args_port()
    print("ok")
