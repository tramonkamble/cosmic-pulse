# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Supervise a killable sample_worker subprocess.

If ``.sample_live.json`` is not refreshed within CHILD_STALL_SEC, the worker is
SIGKILL'd, a parent-side psutil emergency sample is published, and the worker
is respawned. This is the durable fix: hung sysfs/sensors cannot freeze the
HTTP process because sampling does not share that address space.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

CHILD_STALL_SEC = 8.0
RESPAWN_PAUSE_SEC = 0.4
POLL_SEC = 0.5
# Wall advanced much more than monotonic → suspend/resume (or large NTP step).
WALL_JUMP_SEC = 2.5


def _read_live(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    # Reap zombie if we are parent
    try:
        os.waitpid(pid, os.WNOHANG)
    except Exception:
        pass


def _resolve_server_module():
    """Return the live server module.

    When Pulse is started as ``python server.py``, the app lives in
    ``sys.modules['__main__']``. A plain ``import server`` would load a *second*
    copy — samples would publish into a shadow module HTTP never reads.
    """
    import sys

    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_publish_sample") and hasattr(main, "collect_metrics"):
        return main
    import server as srv

    return srv


def _supervisor_loop(srv=None) -> None:
    from paths import app_root, data_dir

    if srv is None:
        srv = _resolve_server_module()

    root = app_root()
    ddir = data_dir()
    live_path = ddir / ".sample_live.json"
    pid_path = ddir / ".sample_worker.pid"
    worker_script = root / "sample_worker.py"
    stalls = 0
    env = os.environ.copy()
    env["PULSE_DATA_DIR"] = str(ddir)
    # Prefer same interpreter
    py = sys.executable or "python3"

    srv._mark_sample_ok()
    srv._sampler_ready.set()
    if not hasattr(srv, "_sampler_resume_epoch"):
        srv._sampler_resume_epoch = 0

    prev_wall = time.time()
    prev_mono = time.monotonic()

    while True:
        # Clear stale live file so we don't treat an old sample as fresh
        try:
            if live_path.exists():
                live_path.unlink()
        except Exception:
            pass
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass

        worker_log = ddir / "sample-worker.log"
        log_f = open(worker_log, "a", buffering=1)
        proc = subprocess.Popen(
            [py, "-u", str(worker_script)],
            cwd=str(root),
            env=env,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,  # own process group — kill group on stall
        )
        child_pid = proc.pid
        srv._sampler_gen += 1
        print(
            f"Cosmic Pulse sampler: worker pid={child_pid} started (killable subprocess) "
            f"watching {live_path}",
            flush=True,
        )
        last_good_wall = 0.0
        last_good_mono = 0.0
        saw_ready = False
        last_seen_file_ts = 0.0
        deadline_boot = time.monotonic() + max(CHILD_STALL_SEC, 25.0)
        samples_applied = 0
        # Fresh loop — sync clocks so we don't false-trigger resume on spawn
        prev_wall = time.time()
        prev_mono = time.monotonic()

        def _kill_and_emergency(reason: str) -> None:
            nonlocal stalls
            stalls += 1
            srv._sampler_stalls = stalls
            srv._sampler_last_reason = "stall"
            if reason == "resume":
                srv._sampler_resume_epoch = int(getattr(srv, "_sampler_resume_epoch", 0)) + 1
            print(
                f"Cosmic Pulse sampler: worker pid={child_pid} {reason} — SIGKILL "
                f"(stalls={stalls} resume_epoch={getattr(srv, '_sampler_resume_epoch', 0)})",
                flush=True,
            )
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except Exception:
                _kill_pid(child_pid)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            try:
                snap = srv.collect_live_core_psutil()
                srv._publish_sample(snap, my_gen=None, into_history=False)
                srv._sampler_last_reason = "degraded"
                print(
                    "Cosmic Pulse sampler: parent emergency (psutil) "
                    f"cpu={snap['cpu'].get('overall_pct')}%",
                    flush=True,
                )
            except Exception as exc:
                print(f"Cosmic Pulse sampler: parent emergency failed: {exc}", flush=True)
                srv._mark_sample_ok()

        try:
            while True:
                # Worker exited unexpectedly
                rc = proc.poll()
                if rc is not None:
                    print(
                        f"Cosmic Pulse sampler: worker pid={child_pid} exited rc={rc} — respawn",
                        flush=True,
                    )
                    break

                payload = _read_live(live_path)
                now_m = time.monotonic()
                now_wall = time.time()
                wall_dt = now_wall - prev_wall
                mono_dt = max(0.0, now_m - prev_mono)
                prev_wall = now_wall
                prev_mono = now_m

                # Suspend/resume: wall jumps while mono barely moves — kill worker
                # immediately (its sysfs/sensors state is often wedged after wake).
                if (wall_dt - mono_dt) > WALL_JUMP_SEC or (wall_dt > 5.0 and mono_dt < 2.0):
                    _kill_and_emergency("resume")
                    break

                if payload:
                    kind = payload.get("kind")
                    file_ts = float(payload.get("ts") or 0)
                    # Only act when the worker advances the timestamp (avoid re-applying).
                    is_new = file_ts > last_seen_file_ts
                    if kind == "ready" and is_new:
                        saw_ready = True
                        last_good_wall = file_ts or now_wall
                        last_good_mono = now_m
                        last_seen_file_ts = file_ts
                        print("Cosmic Pulse sampler: worker ready", flush=True)
                    elif kind == "error" and is_new:
                        print(
                            f"Cosmic Pulse sampler: worker error: {payload.get('error')}",
                            flush=True,
                        )
                        last_good_wall = file_ts or last_good_wall
                        last_good_mono = now_m
                        last_seen_file_ts = file_ts
                    elif kind == "sample" and isinstance(payload.get("snap"), dict) and is_new:
                        saw_ready = True
                        last_good_wall = file_ts or now_wall
                        last_good_mono = now_m
                        last_seen_file_ts = file_ts
                        snap = payload["snap"]
                        try:
                            srv._publish_sample(snap, my_gen=None, into_history=True)
                            samples_applied += 1
                            if samples_applied <= 3 or samples_applied % 30 == 0:
                                cpu = (snap.get("cpu") or {}).get("overall_pct")
                                print(
                                    f"Cosmic Pulse sampler: applied sample #{samples_applied} "
                                    f"cpu={cpu}%",
                                    flush=True,
                                )
                            if srv._sampler_last_reason in ("stall", "degraded", "starting"):
                                srv._sampler_last_reason = ""
                        except Exception as exc:
                            print(
                                f"Cosmic Pulse sampler: publish failed: {exc}",
                                flush=True,
                            )
                        try:
                            srv.load_tuning_log()
                        except Exception:
                            pass
                        try:
                            srv.record_sample_maybe_prune(snap)
                        except Exception as exc:
                            print(f"Cosmic Pulse DB: sample write failed: {exc}", flush=True)

                # Stall detection — prefer monotonic (stable across NTP); wall is
                # backup for "file timestamp never moved after resume".
                if last_good_mono:
                    age_mono = now_m - last_good_mono
                    age_wall = (now_wall - last_good_wall) if last_good_wall else 0.0
                    stalled = age_mono >= CHILD_STALL_SEC or age_wall >= CHILD_STALL_SEC
                else:
                    stalled = now_m >= deadline_boot

                if stalled:
                    _kill_and_emergency("stale")
                    break

                time.sleep(POLL_SEC)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    _kill_pid(proc.pid)
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
            try:
                log_f.close()
            except Exception:
                pass

        time.sleep(RESPAWN_PAUSE_SEC)


def start_sample_supervisor(srv=None) -> None:
    """Start supervisor. Pass ``srv=sys.modules[__name__]`` from server.main()."""
    t = threading.Thread(
        target=_supervisor_loop,
        kwargs={"srv": srv},
        daemon=True,
        name="pulse-sample-supervisor",
    )
    t.start()
