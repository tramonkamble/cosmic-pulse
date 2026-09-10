#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Start Cosmic Pulse. Implementation lives in the cosmic_pulse package."""

from __future__ import annotations

if __name__ == "__main__":
    from cosmic_pulse.server import run

    run()
