# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Library detection tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnostics import _ldconfig_has_i386_soname, run_diagnostics


def test_ldconfig_i386_pop_format():
    sample = """
        libGL.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libGL.so.1
        libGL.so.1 (libc6) => /lib/i386-linux-gnu/libGL.so.1
        libvulkan.so.1 (libc6) => /lib/i386-linux-gnu/libvulkan.so.1
    """
    assert _ldconfig_has_i386_soname(sample, "libGL.so.1")
    assert _ldconfig_has_i386_soname(sample, "libvulkan.so.1")
    assert not _ldconfig_has_i386_soname(sample, "libldap.so.2")


def test_no_false_missing_i386_when_installed():
    findings = run_diagnostics()["findings"]
    missing_i386 = [f for f in findings if f["id"].startswith("lib-missing-i386-")]
    assert not missing_i386, missing_i386


if __name__ == "__main__":
    test_ldconfig_i386_pop_format()
    test_no_false_missing_i386_when_installed()
    print("all ok")
