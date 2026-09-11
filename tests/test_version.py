# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Version is 0.x.y and matches pyproject.toml everywhere."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cosmic_pulse import __version__  # noqa: E402
from cosmic_pulse.version import (  # noqa: E402
    VERSION_RE,
    bump_prerelease,
    parse_prerelease,
    read_pyproject_version,
)


def test_pyproject_is_prerelease() -> None:
    ver = read_pyproject_version(ROOT / "pyproject.toml")
    assert VERSION_RE.fullmatch(ver), ver
    major, minor, patch = parse_prerelease(ver)
    assert major == 0
    assert minor >= 0 and patch >= 0


def test_package_matches_pyproject() -> None:
    ver = read_pyproject_version(ROOT / "pyproject.toml")
    assert __version__ == ver


def test_debian_control_matches() -> None:
    ver = read_pyproject_version(ROOT / "pyproject.toml")
    control = (ROOT / "deploy" / "debian" / "control").read_text(encoding="utf-8")
    m = re.search(r"(?m)^Version:\s*(\S+)", control)
    assert m, "debian control missing Version"
    assert m.group(1) == ver


def test_bump_math() -> None:
    assert bump_prerelease("0.1.0", "patch") == "0.1.1"
    assert bump_prerelease("0.1.9", "patch") == "0.1.10"
    assert bump_prerelease("0.1.3", "minor") == "0.2.0"
    assert bump_prerelease("0.9.4", "major") == "1.0.0"


def test_changelog_has_unreleased() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[Unreleased\]\s*$", text, re.M)


def test_changelog_rotate_and_notes() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bump_version", ROOT / "deploy" / "bump_version.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    src = "## [Unreleased]\n\n### Added\n- thing\n\n## [0.1.0] - 2026-01-01\n\nold\n"
    out = mod.rotate_changelog(src, "0.1.1", "2026-09-10")
    assert out.startswith("## [Unreleased]\n\n## [0.1.1] - 2026-09-10\n")
    assert "### Added\n- thing" in out
    notes = mod.changelog_notes(out, "0.1.1")
    assert "thing" in notes


def run_all() -> None:
    test_pyproject_is_prerelease()
    test_package_matches_pyproject()
    test_debian_control_matches()
    test_bump_math()
    test_changelog_has_unreleased()
    test_changelog_rotate_and_notes()
    print("test_version: ok")


if __name__ == "__main__":
    run_all()
