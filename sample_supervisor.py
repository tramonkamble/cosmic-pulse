# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Supervise a killable sample_worker subprocess.

Watchdog and apply are **separate threads**. Hung sysfs/sensors cannot freeze
HTTP because sampling lives in a child we can SIGKILL. Hung apply (disk, lock,
JSON) cannot freeze kill/respawn because that work is not on the watchdog
thread.

If ``.sample_live.json`` is not refreshed within CHILD_STALL_SEC, the worker is
SIGKILL'd, a parent-side psutil emergency sample is published (timeout-bounded),
and the worker is respawned.
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
APPLY_STALE_SEC = 8.0
APPLY_RESTART_COOLDOWN_SEC = 15.0
RESPAWN_PAUSE_SEC = 0.4
POLL_SEC = 0.5
APPLY_POLL_SEC = 0.25
# Wall advanced much more than monotonic → suspend/resume (or large NTP step).
WALL_JUMP_SEC = 2.5
EMERGENCY_JOIN_SEC = 1.5


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
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "_publish_sample") and hasattr(main, "collect_metrics"):
        return main
    import server as srv

    return srv


def _hb_watchdog(srv) -> None:
    srv._watchdog_last_mono = time.monotonic()


def _hb_apply_loop(srv) -> None:
    srv._apply_loop_mono = time.monotonic()


def _start_apply_thread(srv, live_path: Path, *, force: bool = False) -> None:
    t = getattr(srv, "_pulse_apply_thread", None)
    if t is not None and t.is_alive() and not force:
        return
    srv._apply_gen = int(getattr(srv, "_apply_gen", 0) or 0) + 1
    if force:
        print(
            f"Cosmic Pulse sampler: restarting apply thread (gen={srv._apply_gen})",
            flush=True,
        )
    my_gen = srv._apply_gen
    thread = threading.Thread(
        target=_apply_loop,
        args=(srv, live_path, my_gen),
        daemon=True,
        name=f"pulse-sample-apply-{my_gen}",
    )
    srv._pulse_apply_thread = thread
    thread.start()


def _apply_loop(srv, live_path: Path, my_gen: int) -> None:
    """Consume new live-file samples. Never kills the worker."""
    last_seen_file_ts = 0.0
    samples_applied = 0
    _hb_apply_loop(srv)
    while int(getattr(srv, "_apply_gen", 0)) == my_gen:
        try:
            _hb_apply_loop(srv)
            payload = _read_live(live_path)
            if payload:
                kind = payload.get("kind")
                file_ts = float(payload.get("ts") or 0)
                # Worker respawn / clock jump: timestamps can go backwards.
                if file_ts and last_seen_file_ts and file_ts + 1.0 < last_seen_file_ts:
                    last_seen_file_ts = 0.0
                is_new = file_ts > last_seen_file_ts
                if kind == "sample" and isinstance(payload.get("snap"), dict) and is_new:
                    last_seen_file_ts = file_ts
                    snap = payload["snap"]
                    try:
                        srv._publish_sample(snap, my_gen=None, into_history=True)
                        samples_applied += 1
                        srv._apply_last_mono = time.monotonic()
                        if getattr(srv, "_sampler_last_reason", "") in (
                            "stall",
                            "degraded",
                            "starting",
                            "stale",
                        ):
                            srv._sampler_last_reason = ""
                        if samples_applied <= 3 or samples_applied % 30 == 0:
                            cpu = (snap.get("cpu") or {}).get("overall_pct")
                            print(
                                f"Cosmic Pulse sampler: applied sample #{samples_applied} "
                                f"cpu={cpu}%",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"Cosmic Pulse sampler: publish failed: {exc}", flush=True)
                    try:
                        srv.record_sample_maybe_prune(snap)
                    except Exception as exc:
                        print(f"Cosmic Pulse DB: sample write failed: {exc}", flush=True)
                elif kind in ("ready", "error") and is_new:
                    last_seen_file_ts = file_ts
                    if kind == "error":
                        print(
                            f"Cosmic Pulse sampler: worker error: {payload.get('error')}",
                            flush=True,
                        )
        except Exception as exc:
            print(f"Cosmic Pulse sampler: apply loop error: {exc}", flush=True)
        # Slice sleep so a gen bump exits without waiting a full poll.
        deadline = time.monotonic() + APPLY_POLL_SEC
        while time.monotonic() < deadline:
            if int(getattr(srv, "_apply_gen", 0)) != my_gen:
                return
            time.sleep(0.05)


def _supervisor_loop(srv=None) -> None:
    from paths import app_root, data_dir

    if srv is None:
        srv = _resolve_server_module()

    root = app_root()
    ddir = data_dir()
    live_path = ddir / ".sample_live.json"
    pid_path = ddir / ".sample_worker.pid"
    override = os.environ.get("PULSE_SAMPLE_WORKER", "").strip()
    worker_script = Path(override) if override else root / "sample_worker.py"
    stalls = 0
    env = os.environ.copy()
    env["PULSE_DATA_DIR"] = str(ddir)
    py = sys.executable or "python3"

    if not hasattr(srv, "_apply_gen"):
        srv._apply_gen = 0
    if not hasattr(srv, "_apply_last_mono"):
        srv._apply_last_mono = 0.0
    if not hasattr(srv, "_apply_loop_mono"):
        srv._apply_loop_mono = 0.0
    if not hasattr(srv, "_watchdog_last_mono"):
        srv._watchdog_last_mono = 0.0

    srv._mark_sample_ok()
    srv._sampler_ready.set()
    if not hasattr(srv, "_sampler_resume_epoch"):
        srv._sampler_resume_epoch = 0

    # Drop a leftover live file before apply starts so we don't publish a
    # previous-run sample as "fresh".
    try:
        if live_path.exists():
            live_path.unlink()
    except Exception:
        pass
    _start_apply_thread(srv, live_path, force=False)

    prev_wall = time.time()
    prev_mono = time.monotonic()
    last_apply_restart_mono = 0.0

    while True:
        _hb_watchdog(srv)
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
        last_seen_file_ts = 0.0
        deadline_boot = time.monotonic() + max(CHILD_STALL_SEC, 25.0)
        prev_wall = time.time()
        prev_mono = time.monotonic()

        def _emergency_publish() -> None:
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
            # Never block the watchdog on sysfs/psutil: join with a deadline.
            t = threading.Thread(
                target=_emergency_publish,
                daemon=True,
                name="pulse-supervisor-emergency",
            )
            t.start()
            t.join(timeout=EMERGENCY_JOIN_SEC)
            if t.is_alive():
                print(
                    "Cosmic Pulse sampler: emergency still running after "
                    f"{EMERGENCY_JOIN_SEC}s — watchdog continuing",
                    flush=True,
                )

        try:
            while True:
                _hb_watchdog(srv)
                rc = proc.poll()
                if rc is not None:
                    print(
                        f"Cosmic Pulse sampler: worker pid={child_pid} exited rc={rc} — respawn",
                        flush=True,
                    )
                    break

                now_m = time.monotonic()
                now_wall = time.time()
                wall_dt = now_wall - prev_wall
                mono_dt = max(0.0, now_m - prev_mono)
                prev_wall = now_wall
                prev_mono = now_m

                if (wall_dt - mono_dt) > WALL_JUMP_SEC or (wall_dt > 5.0 and mono_dt < 2.0):
                    _kill_and_emergency("resume")
                    break

                # Freshness from the *file*, not from apply succeeding. That is
                # the whole point of the split: a wedged publish must not hide a
                # live worker, and a live worker must not hide a wedged apply.
                payload = _read_live(live_path)
                if payload:
                    file_ts = float(payload.get("ts") or 0)
                    if file_ts and last_seen_file_ts and file_ts + 1.0 < last_seen_file_ts:
                        last_seen_file_ts = 0.0
                    if file_ts > last_seen_file_ts:
                        last_seen_file_ts = file_ts
                        last_good_wall = file_ts or now_wall
                        last_good_mono = now_m
                        if payload.get("kind") == "ready":
                            print("Cosmic Pulse sampler: worker ready", flush=True)

                apply_loop_mono = float(getattr(srv, "_apply_loop_mono", 0.0) or 0.0)
                if apply_loop_mono and (now_m - apply_loop_mono) >= APPLY_STALE_SEC:
                    if now_m - last_apply_restart_mono >= APPLY_RESTART_COOLDOWN_SEC:
                        last_apply_restart_mono = now_m
                        srv._sampler_last_reason = "stale"
                        _start_apply_thread(srv, live_path, force=True)

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
        name="pulse-sample-watchdog",
    )
    t.start()
