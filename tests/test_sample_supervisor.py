# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Watchdog vs apply split: wedged publish must not freeze worker kill/respawn."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cosmic_pulse import paths  # noqa: E402
from cosmic_pulse import sample_supervisor as ss  # noqa: E402


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


def test_cmdline_is_sample_worker() -> None:
    assert ss._cmdline_is_sample_worker(["python3", "-u", "/opt/pulse/sample_worker.py"])
    assert ss._cmdline_is_sample_worker(["/usr/bin/python3", "sample_worker.py"])
    assert ss._cmdline_is_sample_worker(["python3.12", "-u", "sample_worker.py"])
    assert ss._cmdline_is_sample_worker(["/usr/bin/pypy3", "sample_worker.py"])
    assert ss._cmdline_is_sample_worker(["sample_worker.py"])
    assert ss._cmdline_is_sample_worker(["python3", "-u", "-m", "cosmic_pulse.sample_worker"])
    assert not ss._cmdline_is_sample_worker(["python3", "cosmic_pulse.server.py"])
    assert not ss._cmdline_is_sample_worker(["python3", "not_sample_worker.py"])
    assert not ss._cmdline_is_sample_worker(["vim", "sample_worker.py"])
    assert not ss._cmdline_is_sample_worker(["less", "/opt/pulse/sample_worker.py"])
    assert not ss._cmdline_is_sample_worker([])
    assert not ss._cmdline_is_sample_worker(None)


def test_data_dir_matches() -> None:
    assert ss._data_dir_matches("", None)
    assert ss._data_dir_matches("/tmp/a", "/tmp/a")
    assert ss._data_dir_matches("", "/tmp/a")
    assert ss._data_dir_matches(None, "/tmp/a")
    assert not ss._data_dir_matches("/tmp/b", "/tmp/a")


def test_atomic_write_uses_pid_tmp_and_cleans_up() -> None:
    import json

    from cosmic_pulse.sample_worker import _atomic_write_json

    with tempfile.TemporaryDirectory() as raw:
        dest = Path(raw) / ".sample_live.json"
        _atomic_write_json(dest, {"kind": "ready", "pid": os.getpid()})
        payload = json.loads(dest.read_text())
        assert payload["kind"] == "ready"
        assert list(Path(raw).glob("*.tmp")) == []
        _atomic_write_json(dest, {"kind": "sample", "pid": os.getpid()})
        payload = json.loads(dest.read_text())
        assert payload["kind"] == "sample"
        assert list(Path(raw).glob("*.tmp")) == []


def _spawn_named_worker(script: Path, data_dir: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PULSE_DATA_DIR"] = str(data_dir)
    return subprocess.Popen(
        [sys.executable, "-u", str(script)],
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_proc(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def test_reap_stray_workers_filters_data_dir() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        script = tmp / "sample_worker.py"
        script.write_text("import time\ntime.sleep(60)\n")
        dir_a = tmp / "a"
        dir_b = tmp / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        pa = pb = None
        try:
            pa = _spawn_named_worker(script, dir_a)
            pb = _spawn_named_worker(script, dir_b)
            deadline = time.time() + 2
            while time.time() < deadline and (pa.poll() is not None or pb.poll() is not None):
                time.sleep(0.05)
            assert pa.poll() is None and pb.poll() is None, "sleeper workers exited early"
            n = ss.reap_stray_workers(data_dir=dir_a)
            assert n >= 1
            deadline = time.time() + 2
            while time.time() < deadline and pa.poll() is None:
                time.sleep(0.05)
            assert pa.poll() is not None, "matching data_dir worker was not reaped"
            assert pb.poll() is None, "mismatched data_dir worker was killed"
            n_keep = ss.reap_stray_workers(keep_pid=pb.pid, data_dir=dir_b)
            assert n_keep == 0
            assert pb.poll() is None, "keep_pid worker was killed"
        finally:
            _stop_proc(pa)
            _stop_proc(pb)


def run_all() -> None:
    test_cmdline_is_sample_worker()
    test_data_dir_matches()
    test_atomic_write_uses_pid_tmp_and_cleans_up()
    test_reap_stray_workers_filters_data_dir()
    test_apply_does_not_reload_tuning_log()
    test_wedged_apply_does_not_prevent_worker_respawn()
    print("test_sample_supervisor: ok")


if __name__ == "__main__":
    run_all()
