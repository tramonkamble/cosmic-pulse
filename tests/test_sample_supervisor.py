# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Watchdog vs apply split: wedged publish must not freeze worker kill/respawn."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import paths  # noqa: E402
import sample_supervisor as ss  # noqa: E402


def _dummy_worker_script(tmp: Path) -> Path:
    script = tmp / "dummy_worker.py"
    script.write_text(
        """\
import json, os, time
from pathlib import Path
ddir = Path(os.environ["PULSE_DATA_DIR"])
live = ddir / ".sample_live.json"
pidp = ddir / ".sample_worker.pid"
pidp.write_text(str(os.getpid()))
n = 0
while True:
    n += 1
    payload = {
        "kind": "sample",
        "ts": time.time(),
        "snap": {"ts": time.time(), "cpu": {"overall_pct": n % 100}, "gpu": {}, "memory": {}},
    }
    tmp = live.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(live)
    time.sleep(0.2)
"""
    )
    return script


def _fake_srv(*, block_publish: bool = False) -> SimpleNamespace:
    lock = threading.Lock()
    published: list[dict] = []
    emergencies: list[dict] = []

    def _publish_sample(snap, my_gen=None, *, into_history=True):
        if into_history and block_publish:
            time.sleep(60)
        with lock:
            (published if into_history else emergencies).append(snap)
        srv._sampler_last_ok_mono = time.monotonic()
        if into_history:
            srv._apply_last_mono = time.monotonic()
        return True

    def _mark_sample_ok():
        srv._sampler_last_ok_mono = time.monotonic()

    def collect_live_core_psutil():
        return {"cpu": {"overall_pct": 1.0}, "gpu": {}, "memory": {}}

    def record_sample_maybe_prune(snap):
        return None

    def load_tuning_log():
        srv.tuning_loads += 1

    srv = SimpleNamespace(
        _publish_sample=_publish_sample,
        _mark_sample_ok=_mark_sample_ok,
        collect_live_core_psutil=collect_live_core_psutil,
        collect_metrics=lambda: None,
        record_sample_maybe_prune=record_sample_maybe_prune,
        load_tuning_log=load_tuning_log,
        _sampler_gen=0,
        _sampler_stalls=0,
        _sampler_last_reason="starting",
        _sampler_resume_epoch=0,
        _sampler_ready=threading.Event(),
        _sampler_last_ok_mono=0.0,
        _apply_gen=0,
        _apply_last_mono=0.0,
        _apply_loop_mono=0.0,
        _watchdog_last_mono=0.0,
        _pulse_apply_thread=None,
        published=published,
        emergencies=emergencies,
        tuning_loads=0,
    )
    return srv


def _start(tmp: Path, srv) -> None:
    os.environ["PULSE_DATA_DIR"] = str(tmp)
    os.environ["PULSE_SAMPLE_WORKER"] = str(_dummy_worker_script(tmp))
    paths.reset_data_dir_cache()
    threading.Thread(target=ss._supervisor_loop, kwargs={"srv": srv}, daemon=True).start()


def _cleanup_worker(tmp: Path) -> None:
    pid_path = tmp / ".sample_worker.pid"
    if not pid_path.exists():
        return
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        return
    try:
        os.killpg(pid, 9)
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def test_apply_does_not_reload_tuning_log():
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        srv = _fake_srv()
        try:
            _start(tmp, srv)
            deadline = time.time() + 8
            while time.time() < deadline and len(srv.published) < 2:
                time.sleep(0.1)
            assert len(srv.published) >= 2, f"expected applies, got {len(srv.published)}"
            assert srv.tuning_loads == 0
            assert srv._apply_last_mono > 0
            assert srv._watchdog_last_mono > 0
        finally:
            _cleanup_worker(tmp)


def test_wedged_apply_does_not_prevent_worker_respawn():
    """Watchdog heartbeat + stall-kill still work while apply is blocked in publish."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        srv = _fake_srv(block_publish=True)
        try:
            _start(tmp, srv)
            deadline = time.time() + 6
            while time.time() < deadline and srv._watchdog_last_mono == 0:
                time.sleep(0.05)
            wd1 = srv._watchdog_last_mono
            assert wd1 > 0
            time.sleep(1.2)
            assert srv._watchdog_last_mono > wd1
            stalls_before = srv._sampler_stalls
            time.sleep(2.0)
            assert srv._sampler_stalls == stalls_before, "live worker killed because apply was wedged"
            hang = tmp / "dummy_worker.py"
            hang.write_text("import time\nwhile True:\n    time.sleep(30)\n")
            pid_path = tmp / ".sample_worker.pid"
            deadline = time.time() + 8
            pid = None
            while time.time() < deadline:
                if pid_path.exists():
                    try:
                        pid = int(pid_path.read_text().strip())
                        break
                    except ValueError:
                        pass
                time.sleep(0.05)
            assert pid, "worker pid file missing"
            os.kill(pid, 9)
            # First sample on a new worker is allowed up to 25s (boot deadline).
            deadline = time.time() + 40
            while time.time() < deadline and srv._sampler_stalls <= stalls_before:
                time.sleep(0.2)
            assert srv._sampler_stalls > stalls_before, (
                "watchdog did not kill stalled worker while apply was wedged"
            )
        finally:
            _cleanup_worker(tmp)


def run_all() -> None:
    test_apply_does_not_reload_tuning_log()
    test_wedged_apply_does_not_prevent_worker_respawn()
    print("test_sample_supervisor: ok")


if __name__ == "__main__":
    run_all()
