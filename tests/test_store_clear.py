# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Clear samples drains the writer queue then DELETE."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_clear_history_drops_queued_inserts() -> None:
    with tempfile.TemporaryDirectory() as raw:
        os.environ["PULSE_DATA_DIR"] = raw
        import importlib

        import paths
        import store

        paths.reset_data_dir_cache()
        importlib.reload(store)
        store.init_db()
        store.start_writer_worker()
        snap = {
            "ts": time.time(),
            "cpu": {"overall_pct": 10, "load": [1, 1, 1]},
            "memory": {"pct": 20, "swap_pct": 0},
            "gpu": {"discrete": {}},
            "bandwidth": {},
            "game_totals": {},
            "comparison": {},
            "stutter": {},
        }
        for _ in range(5):
            snap = dict(snap)
            snap["ts"] = time.time()
            store.record_sample(snap)
        store._sample_queue.join()
        before = store.stats()["samples"]
        assert before >= 5
        out = store.clear_history()
        assert out.get("cleared_samples", 0) >= 5
        assert store.stats()["samples"] == 0


if __name__ == "__main__":
    test_clear_history_drops_queued_inserts()
    print("test_store_clear: ok")
