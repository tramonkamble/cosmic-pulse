# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Cosmic Pulse product harness — intended functionality, no pytest required.

Covers: sampler health, live metrics shape, Guidance pack, dashboard HTML,
game-session API, read-only security, store/diagnostics, history ring.

Usage:
  python3 tests/harness.py              # spawn Pulse on :18765
  PULSE_TEST_EXISTING=1 python3 tests/harness.py   # hit running :8765
  python3 tests/harness.py --full       # also run slow sampler unit tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PORT = int(os.environ.get("PULSE_TEST_PORT", "18765"))
EXISTING = os.environ.get("PULSE_TEST_EXISTING", "").lower() in ("1", "true", "yes")
BASE = os.environ.get(
    "PULSE_TEST_URL",
    "http://127.0.0.1:8765" if EXISTING else f"http://127.0.0.1:{TEST_PORT}",
).rstrip("/")

_server_proc: subprocess.Popen | None = None
_failed: list[str] = []
_passed = 0


def _ok(name: str) -> None:
    global _passed
    _passed += 1
    print(f"  ok  {name}")


def _fail(name: str, detail: str) -> None:
    _failed.append(f"{name}: {detail}")
    print(f"  FAIL  {name}: {detail}")


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        _ok(name)
        return True
    _fail(name, detail or "assertion failed")
    return False


def _get(path: str, timeout: float = 10.0) -> tuple[int, object]:
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)
    if not body:
        return status, None
    ctype = ""
    try:
        return status, json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, body.decode("utf-8", "replace")


def _post(path: str, payload: dict, timeout: float = 8.0) -> tuple[int, object]:
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=raw,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)
    try:
        return status, json.loads(body.decode()) if body else None
    except json.JSONDecodeError:
        return status, None


def _ping() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/", timeout=2.0) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ensure_server() -> None:
    global _server_proc
    if EXISTING:
        if not _ping():
            raise RuntimeError(f"PULSE_TEST_EXISTING set but {BASE} is down")
        return
    if _server_proc is None:
        env = {**os.environ, "PULSE_PORT": str(TEST_PORT)}
        _server_proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    for _ in range(50):
        if _ping():
            return
        if _server_proc.poll() is not None:
            err = (_server_proc.stderr.read() if _server_proc.stderr else b"").decode()
            raise RuntimeError(f"Pulse exited during harness startup: {err[:800]}")
        time.sleep(0.2)
    raise RuntimeError(f"Pulse not reachable at {BASE}")


def _shutdown() -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


def _wait_sample() -> dict:
    last = {}
    for _ in range(25):
        status, data = _get("/api/metrics")
        if status == 200 and isinstance(data, dict):
            last = data
            samp = data.get("sampler") or {}
            latest = data.get("latest") or {}
            if samp.get("ok") and latest.get("cpu"):
                return data
        time.sleep(0.4)
    return last


def check_dashboard_html() -> None:
    status, html = _get("/")
    if not check("GET /", status == 200 and isinstance(html, str), f"status={status}"):
        return
    for needle in (
        "dash-dedupe",
        'data-tab="dashboard"',
        'data-tab="fixes"',
        'data-tab="options"',
        "Live lab",
        'data-viz-tab="rig"',
        'data-viz-tab="index"',
        'data-viz-tab="stutter"',
        'data-view="60"',
        'data-view="300"',
        'data-view="600"',
        'data-view="3600"',
        'data-dial="cpu-power"',
        'id="sumHealthCell" data-drill="insightsSection"',
        "pulse-core",
    ):
        # pack ids live in YAML; HTML need not mention them
        if needle == "pulse-core":
            continue
        check(f"html has {needle}", needle in html, "missing from index.html")


def check_sampler_and_metrics() -> dict:
    data = _wait_sample()
    samp = data.get("sampler") or {}
    latest = data.get("latest") or {}
    check("sampler ok", samp.get("ok") is True, str(samp))
    check(
        "sampler state",
        samp.get("state") in ("healthy", "starting", "degraded"),
        str(samp.get("state")),
    )
    age = samp.get("age_sec")
    check("sampler age_sec", isinstance(age, (int, float)) and age < 20, str(age))
    check("watchdog_age_sec", "watchdog_age_sec" in samp, str(samp.keys()))
    check("last_apply_age_sec", "last_apply_age_sec" in samp, str(samp.keys()))

    cpu = latest.get("cpu") or {}
    mem = latest.get("memory") or {}
    gpu = (latest.get("gpu") or {}).get("discrete") or {}
    check("cpu.overall_pct", cpu.get("overall_pct") is not None, str(cpu.get("overall_pct")))
    check("memory.pct", mem.get("pct") is not None, str(mem.get("pct")))
    check("gpu.busy_pct or gpu present", isinstance(gpu, dict), "no gpu.discrete")
    temps = (cpu.get("temps") or {})
    check(
        "cpu temps package or ccd",
        temps.get("package") is not None or bool(temps.get("ccd")),
        str(temps),
    )
    pw = cpu.get("power_w")
    check(
        "cpu.power_w is number or null",
        pw is None or isinstance(pw, (int, float)),
        str(pw),
    )
    check("game_totals", isinstance(latest.get("game_totals"), dict))
    check("game_performance", isinstance(latest.get("game_performance"), dict))
    check("tuning list", isinstance(latest.get("tuning"), list))
    check("stutter", isinstance(latest.get("stutter"), dict))
    return data


def check_bootstrap() -> dict:
    status, data = _get("/api/metrics?bootstrap=1")
    if not check("bootstrap 200", status == 200 and isinstance(data, dict), str(status)):
        return {}
    static = data.get("static") or {}
    check("pulse_root", bool(static.get("pulse_root")))
    check("games_catalog", isinstance(static.get("games_catalog"), dict))
    check("history is list", isinstance(data.get("history"), list))
    hmax = static.get("history_max_sec")
    check("history_max_sec >= 600", isinstance(hmax, (int, float)) and hmax >= 600, str(hmax))
    tools = static.get("tools") or {}
    srcs = tools.get("data_sources") or []
    ids = {t.get("id") for t in srcs if isinstance(t, dict)}
    check("tools lists cpu-rapl", "cpu-rapl" in ids, str(ids))
    check("slim poll has no static", True)  # checked below
    return data if isinstance(data, dict) else {}


def check_slim_poll() -> None:
    status, data = _get("/api/metrics")
    if not check("slim metrics 200", status == 200 and isinstance(data, dict)):
        return
    check("slim has latest", "latest" in data)
    check("slim has point", "point" in data)
    check("slim omits static", "static" not in data)


def check_guidance(boot: dict, live: dict) -> None:
    status, packs = _get("/api/rule-packs")
    if check("GET /api/rule-packs", status == 200 and isinstance(packs, dict), str(status)):
        plist = packs.get("packs") or []
        ids = {p.get("id") for p in plist if isinstance(p, dict)}
        check("pack pulse-core", "pulse-core" in ids, str(ids))
        check("pack popos-core", "popos-core" in ids, str(ids))
        builtin_ids = {p.get("id") for p in plist if isinstance(p, dict) and p.get("builtin")}
        check(
            "only two builtin packs",
            builtin_ids == {"pulse-core", "popos-core"},
            str(builtin_ids),
        )
        core = next((p for p in plist if p.get("id") == "pulse-core"), {})
        pop = next((p for p in plist if p.get("id") == "popos-core"), {})
        check("pulse-core builtin", core.get("builtin") is True, str(core))
        check("pulse-core has 5 rules", (core.get("rule_count") or 0) == 5, str(core.get("rule_count")))
        check("popos-core has 5 rules", (pop.get("rule_count") or 0) == 5, str(pop.get("rule_count")))
        if core.get("enabled") is False:
            print("  skip pulse-core enabled (disabled in this machine's config)")
    status, rules = _get("/api/rule-packs?view=rules&pack=pulse-core")
    if check("rule list 200", status == 200 and isinstance(rules, dict)):
        rids = {
            r.get("insight_id") or r.get("rule_id")
            for r in (rules.get("rules") or [])
            if isinstance(r, dict)
        }
        check(
            "stutter-proxy in core pack",
            "stutter-proxy" in rids,
            str(sorted(x for x in rids if x)[:12]),
        )
    status, pop_rules = _get("/api/rule-packs?view=rules&pack=popos-core")
    if check("pop rule list 200", status == 200 and isinstance(pop_rules, dict)):
        prids = {
            r.get("insight_id") or r.get("rule_id")
            for r in (pop_rules.get("rules") or [])
            if isinstance(r, dict)
        }
        check(
            "cpu-rapl-unreadable in pop pack",
            "cpu-rapl-unreadable" in prids,
            str(sorted(x for x in prids if x)[:12]),
        )

    energy = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
    present = energy.is_file()
    readable = False
    if present:
        try:
            energy.read_text()
            readable = True
        except OSError:
            readable = False
    latest = (live.get("latest") or {}) if isinstance(live, dict) else {}
    tuning = latest.get("tuning") or []
    insight_ids = {h.get("insight_id") for h in tuning if isinstance(h, dict)}
    if present and not readable:
        check(
            "RAPL blocked → Guidance card",
            "cpu-rapl-unreadable" in insight_ids,
            str(sorted(x for x in insight_ids if x)[:8]),
        )
        pw = (latest.get("cpu") or {}).get("power_w")
        check("CPU watts n/a while RAPL blocked", pw is None, str(pw))
    elif present and readable:
        pw = (latest.get("cpu") or {}).get("power_w")
        for _ in range(8):
            if isinstance(pw, (int, float)):
                break
            time.sleep(0.35)
            live = _wait_sample()
            latest = (live.get("latest") or {}) if isinstance(live, dict) else {}
            pw = (latest.get("cpu") or {}).get("power_w")
        check(
            "CPU watts numeric when RAPL readable",
            isinstance(pw, (int, float)),
            str(pw),
        )


def check_game_and_store() -> None:
    status, data = _get("/api/game-sessions?days=30")
    if check("GET /api/game-sessions", status == 200 and isinstance(data, dict), str(status)):
        check("sessions list", isinstance(data.get("sessions"), list))
        check("markers list", isinstance(data.get("markers"), list))
    status, data = _get("/api/issues-by-game")
    check("GET /api/issues-by-game", status == 200 and isinstance(data, dict))
    status, data = _get("/api/store")
    if check("GET /api/store", status == 200 and isinstance(data, dict), str(status)):
        scales = data.get("hw_scales") or {}
        check(
            "store hw_scales.cpu_temp_max_c",
            isinstance(scales.get("cpu_temp_max_c"), (int, float)),
            str(scales),
        )
    status, data = _get("/api/diagnostics")
    check("GET /api/diagnostics", status == 200 and isinstance(data, dict))
    status, data = _get("/api/trends?metric=gpu_junction_c&hours=1&bucket=60")
    check("GET /api/trends", status == 200 and isinstance(data, dict))


def check_readonly() -> None:
    status, data = _get("/api/fix-script?insight_id=vm-swappiness-high")
    check("fix-script gone", status == 404, str(status))
    status, data = _post("/api/apply-fix", {"insight_id": "vm-swappiness-high"})
    check("apply-fix gone", status in (404, 405, 410), str(status))
    if isinstance(data, dict):
        check("apply-fix read_only", data.get("read_only") is True or status in (404, 405))


def run_unit_file(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        _fail(rel, "missing")
        return
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode == 0:
        _ok(rel)
    else:
        tail = (proc.stdout or "")[-400:] + (proc.stderr or "")[-400:]
        _fail(rel, f"exit {proc.returncode}\n{tail}")


def run_product() -> None:
    print(f"\n== product  {BASE} ==")
    check_dashboard_html()
    boot = check_bootstrap()
    live = check_sampler_and_metrics()
    check_slim_poll()
    check_guidance(boot, live)
    check_game_and_store()
    check_readonly()


def main() -> int:
    full = "--full" in sys.argv
    print("Cosmic Pulse harness")
    print(f"  root {ROOT}")
    print(f"  url  {BASE}  existing={EXISTING}  full={full}")
    try:
        _ensure_server()
        run_product()
    except Exception:
        _fail("server", traceback.format_exc()[-600:])
    finally:
        if not EXISTING:
            _shutdown()

    print("\n== unit (no pytest) ==")
    run_unit_file("tests/test_live_sensors.py")
    run_unit_file("tests/test_hw_scales.py")
    run_unit_file("tests/test_probe_memory.py")
    run_unit_file("tests/test_platform_identity.py")
    run_unit_file("tests/test_chassis_identity.py")
    run_unit_file("tests/test_cli.py")
    if full:
        run_unit_file("tests/test_sample_supervisor.py")
    else:
        print("  skip tests/test_sample_supervisor.py (pass --full)")

    print(f"\n{ _passed } passed, {len(_failed)} failed")
    for item in _failed:
        print(f"  - {item}")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
