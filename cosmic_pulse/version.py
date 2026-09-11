# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Package version — source of truth is pyproject.toml [project].version.

Stay on 0.x.y while Cosmic Pulse is prerelease.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSION_RE = re.compile(r"^0\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def pyproject_path() -> Path:
    return Path(__file__).resolve().parent.parent / "pyproject.toml"


def read_pyproject_version(path: Path | None = None) -> str:
    src = path or pyproject_path()
    try:
        import tomllib
    except ImportError:  # pragma: no cover — requires-python >= 3.11
        raise RuntimeError("Python 3.11+ required to read pyproject.toml") from None
    data = tomllib.loads(src.read_text(encoding="utf-8"))
    ver = str((data.get("project") or {}).get("version") or "").strip()
    if not ver:
        raise RuntimeError(f"no [project].version in {src}")
    return ver


def installed_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("cosmic-pulse")
    except Exception:
        return None


def package_version() -> str:
    path = pyproject_path()
    if path.is_file():
        return read_pyproject_version(path)
    inst = installed_version()
    if inst:
        return inst
    return "0.1.0"


def parse_prerelease(ver: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(ver):
        raise ValueError(f"not a 0.x.y prerelease version: {ver!r}")
    major, minor, patch = ver.split(".")
    return int(major), int(minor), int(patch)


def bump_prerelease(ver: str, part: str) -> str:
    major, minor, patch = parse_prerelease(ver)
    if part == "patch":
        return f"0.{minor}.{patch + 1}"
    if part == "minor":
        return f"0.{minor + 1}.0"
    if part == "major":
        return "1.0.0"
    raise ValueError(f"unknown bump part {part!r} (use patch, minor, or major)")


__version__ = package_version()
