#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bump Cosmic Pulse 0.x.y prerelease version.

Source of truth: pyproject.toml [project].version

  python3 deploy/bump_version.py show
  python3 deploy/bump_version.py patch
  python3 deploy/bump_version.py minor
  python3 deploy/bump_version.py patch --commit --tag

Pushing a v0.x.y tag runs the GitHub prerelease workflow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cosmic_pulse.version import (  # noqa: E402
    VERSION_RE,
    bump_prerelease,
    parse_prerelease,
    read_pyproject_version,
)

PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
DEBIAN_CONTROL = ROOT / "deploy" / "debian" / "control"
README = ROOT / "README.md"
INSTALL_DOC = ROOT / "docs" / "INSTALL.md"


def _replace_once(path: Path, pattern: str, repl: str, *, flags: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"{path}: expected 1 replace for {pattern!r}, got {n}")
    path.write_text(new, encoding="utf-8")


def set_pyproject_version(new: str) -> None:
    _replace_once(PYPROJECT, r'(?m)^(version\s*=\s*")[^"]+(")', rf"\g<1>{new}\2")


def set_debian_version(new: str) -> None:
    _replace_once(DEBIAN_CONTROL, r"(?m)^(Version:\s*)\S+", rf"\g<1>{new}")


def changelog_notes(text: str, version: str) -> str:
    m = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        re.M | re.S,
    )
    body = (m.group(1).strip() if m else "") or f"Cosmic Pulse {version} (0.x prerelease)."
    return body


def rotate_changelog(text: str, version: str, date: str) -> str:
    m = re.search(r"^## \[Unreleased\]\s*$", text, re.M)
    if not m:
        raise SystemExit("CHANGELOG.md missing ## [Unreleased]")
    insert = f"## [Unreleased]\n\n## [{version}] - {date}\n"
    return text[: m.start()] + insert + text[m.end() :]


def set_readme_status(new: str) -> None:
    text = README.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r"(\*\*Status:\*\*\s*)v0\.\d+\.\d+",
        rf"\g<1>v{new}",
        text,
        count=1,
    )
    if n != 1:
        # First-time: v0.1 without patch
        new_text, n = re.subn(
            r"(\*\*Status:\*\*\s*)v0\.\d+",
            rf"\g<1>v{new}",
            text,
            count=1,
        )
    if n != 1:
        raise SystemExit(f"README.md: could not update Status version ({n} matches)")
    README.write_text(new_text, encoding="utf-8")


def set_install_deb_name(old: str, new: str) -> None:
    text = INSTALL_DOC.read_text(encoding="utf-8")
    needle = f"cosmic-pulse_{old}_all.deb"
    if needle not in text:
        # keep going if the doc already drifted; pyproject is source of truth
        return
    INSTALL_DOC.write_text(text.replace(needle, f"cosmic-pulse_{new}_all.deb"), encoding="utf-8")


def apply_version(old: str, new: str, *, date: str) -> None:
    parse_prerelease(new) if new.startswith("0.") else None
    set_pyproject_version(new)
    set_debian_version(new)
    CHANGELOG.write_text(
        rotate_changelog(CHANGELOG.read_text(encoding="utf-8"), new, date),
        encoding="utf-8",
    )
    set_readme_status(new)
    set_install_deb_name(old, new)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, text=True, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "part",
        nargs="?",
        default="show",
        choices=("show", "notes", "patch", "minor", "major"),
        help="show current version, print changelog notes, or bump patch/minor (0.x.y)",
    )
    parser.add_argument(
        "--major",
        action="store_true",
        help="allow bumping to 1.0.0 (leaves 0.x prerelease)",
    )
    parser.add_argument("--commit", action="store_true", help="git commit the version files")
    parser.add_argument("--tag", action="store_true", help="create annotated git tag vX.Y.Z")
    parser.add_argument("--push", action="store_true", help="git push commit and tag")
    parser.add_argument("--dry-run", action="store_true", help="print the new version and exit")
    args = parser.parse_args(argv)

    current = read_pyproject_version(PYPROJECT)
    if args.part == "show":
        print(current)
        return 0
    if args.part == "notes":
        print(changelog_notes(CHANGELOG.read_text(encoding="utf-8"), current))
        return 0

    if args.part == "major" and not args.major:
        print(
            "Cosmic Pulse is still 0.x.y prerelease. "
            "Use `python3 deploy/bump_version.py minor` (0.2.0) or pass --major for 1.0.0.",
            file=sys.stderr,
        )
        return 2

    new = bump_prerelease(current, args.part)
    if new.startswith("1.") and not args.major:
        print("refusing 1.0.0 without --major", file=sys.stderr)
        return 2
    if not new.startswith("0.") and not VERSION_RE.fullmatch(new) and new != "1.0.0":
        print(f"unexpected version {new}", file=sys.stderr)
        return 2

    print(f"{current} -> {new}")
    if args.dry_run:
        return 0

    today = dt.date.today().isoformat()
    apply_version(current, new, date=today)
    print("updated pyproject.toml, debian/control, CHANGELOG.md, README.md, docs/INSTALL.md")

    if args.commit:
        git(
            "add",
            "pyproject.toml",
            "deploy/debian/control",
            "CHANGELOG.md",
            "README.md",
            "docs/INSTALL.md",
        )
        git("commit", "-m", f"chore: release {new}")
        print(f"committed chore: release {new}")

    if args.tag:
        tag = f"v{new}"
        git("tag", "-a", tag, "-m", f"Cosmic Pulse {new}")
        print(f"tagged {tag}")

    if args.push:
        git("push")
        if args.tag:
            git("push", "origin", f"v{new}")
        print("pushed")

    if not args.commit and not args.tag:
        print(
            f"next: git add -u && git commit -m 'chore: release {new}' "
            f"&& git tag -a v{new} -m 'Cosmic Pulse {new}' && git push --follow-tags"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
