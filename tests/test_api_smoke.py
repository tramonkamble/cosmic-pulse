# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""HTTP smoke tests against a running Pulse server (port 8765)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PORT = int(os.environ.get("PULSE_TEST_PORT", "18765"))
BASE = os.environ.get("PULSE_TEST_URL", f"http://127.0.0.1:{TEST_PORT}").rstrip("/")
USE_EXISTING = os.environ.get("PULSE_TEST_EXISTING", "").lower() in ("1", "true", "yes")
_server_proc: subprocess.Popen | None = None


def _get(path: str, timeout: float = 8.0) -> tuple[int, dict]:
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    data = json.loads(body.decode()) if body else {}
    return status, data


def _ping() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/", timeout=2.0) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ensure_server() -> None:
    global _server_proc
    if USE_EXISTING and _ping():
        return
    if _server_proc is None and not USE_EXISTING:
        env = {**os.environ, "PULSE_PORT": str(TEST_PORT)}
        _server_proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    if _ping():
        return
    for _ in range(40):
        if _ping():
            return
        if _server_proc.poll() is not None:
            err = (_server_proc.stderr.read() if _server_proc.stderr else b"").decode()
            raise RuntimeError(f"Pulse server exited during startup: {err[:500]}")
        time.sleep(0.25)
    raise RuntimeError(f"Pulse not reachable at {BASE} after startup wait")


def _shutdown_server() -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


def test_root_ok():
    assert _ping()


def test_bootstrap_static_fields():
    status, data = _get("/api/metrics?bootstrap=1")
    assert status == 200
    static = data.get("static") or {}
    assert static.get("legacy_game_ids", {}).get("cities2") == "949230"
    assert isinstance(static.get("games_catalog"), dict)
    assert static.get("pulse_root")


def test_bootstrap_latest_shape():
    status, data = _get("/api/metrics?bootstrap=1")
    assert status == 200
    latest = data.get("latest") or {}
    assert "game_totals" in latest
    assert "tuning" in latest
    assert isinstance(latest.get("tuning"), list)
    assert isinstance(data.get("history"), list)
    samp = data.get("sampler") or {}
    assert "ok" in samp
    assert "age_sec" in samp
    assert "generation" in samp


def test_fix_script_requires_insight_id():
    status, data = _get("/api/fix-script")
    assert status == 400
    assert data.get("ok") is False


def test_fix_script_swappiness_non_empty():
    status, data = _get("/api/fix-script?insight_id=vm-swappiness-high")
    assert status == 200
    assert data.get("ok") is True
    script = data.get("script") or ""
    assert "swappiness" in script.lower()
    assert len(script) > 80


def test_fix_script_game_files_no_cs2_default():
    status, data = _get("/api/fix-script?insight_id=game-files-corrupt")
    assert status == 200
    script = data.get("script") or ""
    if script:
        assert "Counter-Strike" not in script
        assert "steam://validate/730" not in script


def test_fix_script_game_libs_non_empty():
    status, data = _get("/api/fix-script?insight_id=game-libs-missing")
    assert status == 200
    script = data.get("script") or ""
    assert "apt install" in script or "gaming libraries" in script.lower()


def test_diagnostics_force():
    status, data = _get("/api/diagnostics?force=1")
    assert status == 200
    assert isinstance(data.get("findings"), list)
    assert isinstance(data.get("scan_findings"), list)


def test_issues_by_game():
    status, data = _get("/api/issues-by-game")
    assert status == 200
    assert isinstance(data.get("issues_by_game"), dict)


def test_store_stats():
    status, data = _get("/api/store")
    assert status == 200
    assert "samples" in data or "games" in data


def test_poll_metrics_slim():
    status, data = _get("/api/metrics")
    assert status == 200
    assert "latest" in data
    assert "point" in data
    assert "static" not in data
    samp = data.get("sampler") or {}
    assert samp.get("ok") is True
    assert samp.get("age_sec") is not None
    assert samp["age_sec"] < 15


def run_all() -> None:
    _ensure_server()
    try:
        test_root_ok()
        test_bootstrap_static_fields()
        test_bootstrap_latest_shape()
        test_fix_script_requires_insight_id()
        test_fix_script_swappiness_non_empty()
        test_fix_script_game_files_no_cs2_default()
        test_fix_script_game_libs_non_empty()
        test_diagnostics_force()
        test_issues_by_game()
        test_store_stats()
        test_poll_metrics_slim()
    finally:
        if _server_proc is not None:
            _shutdown_server()


if __name__ == "__main__":
    run_all()
    print("all ok")
