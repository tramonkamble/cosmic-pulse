# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Killable metrics worker — runs as its own process (not a thread).

Parent (server.py) starts this via subprocess, reads ``.sample_live.json``,
and SIGKILLs this process if the file goes stale. Threads cannot be killed;
this process can.

Env:
  PULSE_DATA_DIR — writable state dir (required for shared DB/config paths)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, separators=(",", ":"), default=str).encode()
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main() -> int:
    # Ensure we import sibling modules from this app root
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)

    import server as srv
    from paths import data_dir

    out_path = data_dir() / ".sample_live.json"
    pid_path = data_dir() / ".sample_worker.pid"
    pid_path.write_text(str(os.getpid()))
    print(f"Cosmic Pulse sample-worker: pid={os.getpid()} out={out_path}", flush=True)

    srv.init_probe_state(for_child=True)
    _atomic_write_json(
        out_path,
        {"kind": "ready", "ts": time.time(), "pid": os.getpid()},
    )

    while True:
        t0 = time.monotonic()
        try:
            snap = srv.collect_metrics()
            _atomic_write_json(
                out_path,
                {"kind": "sample", "ts": time.time(), "pid": os.getpid(), "snap": snap},
            )
        except Exception as exc:
            _atomic_write_json(
                out_path,
                {
                    "kind": "error",
                    "ts": time.time(),
                    "pid": os.getpid(),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            traceback.print_exc()
        elapsed = time.monotonic() - t0
        time.sleep(max(0.05, 1.0 - elapsed))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
