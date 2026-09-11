# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""HTTP handler for Cosmic Pulse.

Imported from ``server.main()`` after the process module is fully loaded so
``from . import server as srv`` sees complete process state (no circular import
at module import time). Behavior matches the former ``server.Handler``.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import collectors as col
from . import server as srv
from .collectors import load_memory_spec
from .probe_memory import probe_script_path
from .cosmic_theme import get_cosmic_theme, get_cosmic_theme_pack
from .diagnostics import (
    diagnostics_job_status,
    get_diagnostics,
    invalidate_diagnostics_cache,
    primary_finding,
    request_diagnostics_scan,
)
from .pulse_config import THEME_MODES, get_resolved_insights, get_suppressed_insights
from .store import (
    correlate,
    list_game_sessions,
    list_session_markers,
    series,
    update_settings,
)
from .tuning_actions import system_context


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if self.command != "POST":
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            data = (srv.ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/assets/"):
            # Brand logos and other static assets (no path traversal)
            rel = path[len("/assets/") :].lstrip("/")
            asset_root = (srv.ROOT / "assets").resolve()
            try:
                fp = (asset_root / rel).resolve()
            except OSError:
                fp = None
            under_assets = fp and (
                fp == asset_root or str(fp).startswith(str(asset_root) + os.sep)
            )
            if not under_assets or not fp.is_file():
                self.send_response(404)
                self.end_headers()
                return
            data = fp.read_bytes()
            ctype = "application/octet-stream"
            cache = "public, max-age=86400"
            if fp.suffix == ".svg":
                ctype = "image/svg+xml"
            elif fp.suffix == ".png":
                ctype = "image/png"
            elif fp.suffix == ".jpg" or fp.suffix == ".jpeg":
                ctype = "image/jpeg"
            elif fp.suffix == ".webp":
                ctype = "image/webp"
            elif fp.suffix == ".css":
                ctype = "text/css; charset=utf-8"
                cache = "no-cache"
            elif fp.suffix == ".js":
                ctype = "text/javascript; charset=utf-8"
                cache = "no-cache"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/probe-memory":
            import subprocess as sp

            script = probe_script_path()
            payload = {
                "ok": False,
                "message": f"Run: sudo python3 {script}",
            }
            try:
                raw = sp.check_output(
                    ["sudo", "-n", sys.executable, str(script)],
                    text=True,
                    timeout=8,
                    stderr=sp.DEVNULL,
                )
                col._mem_spec = load_memory_spec()
                payload = {"ok": True, "memory": col._mem_spec, "output": raw[-500:]}
            except (sp.SubprocessError, OSError):
                pass
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/metrics":
            bootstrap = (qs.get("bootstrap") or ["0"])[0] in ("1", "true", "yes")
            # Copy under lock only — never hold the lock across json.dumps (or config I/O).
            # Holding the lock for the full encode used to delay the sampler after resume.
            with srv._lock:
                # Bootstrap keeps last_session.trend once for instant game chart;
                # steady 1 Hz polls omit the ~64 KB series (client uses history /
                # /api/game-sessions instead).
                latest = srv.latest_for_api(
                    srv._latest_full,
                    include_game_issues=bootstrap,
                    include_session_trend=bootstrap,
                )
                history_copy = list(srv._history) if bootstrap else None
                point = (
                    srv._history[-1]
                    if srv._history
                    else srv.slim_history_point(srv._latest_full)
                )
                static_snap = srv._static
            # Fresh COSMIC tokens every poll (mtime-cached — free when unchanged).
            try:
                pack = get_cosmic_theme_pack()
            except Exception:
                pack = {"auto": get_cosmic_theme(), "dark": None, "light": None}
            cosmic_theme = pack["auto"]
            if static_snap is not None:
                static_snap["cosmic_theme"] = cosmic_theme
                if pack.get("dark"):
                    static_snap["cosmic_theme_dark"] = pack["dark"]
                if pack.get("light"):
                    static_snap["cosmic_theme_light"] = pack["light"]
            samp = srv.sampler_status()
            if bootstrap:
                body = {
                    "static": static_snap,
                    "latest": latest,
                    "history": history_copy,
                    "sampler": samp,
                    "theme": cosmic_theme,
                    "cosmic_theme": cosmic_theme,
                }
            else:
                body = {
                    "latest": latest,
                    "point": point,
                    "theme": cosmic_theme,
                    "cosmic_theme": cosmic_theme,
                    "resolved_insights": get_resolved_insights(),
                    "suppressed_insights": get_suppressed_insights(),
                    "sampler": samp,
                }
            payload = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif path == "/api/issues-by-game":
            with srv._lock:
                latest = srv.latest_for_api(srv._latest_full)
                by_game = latest.get("issues_by_game") or {}
            self._json({"issues_by_game": by_game})
        elif path == "/api/diagnostics":
            from .rule_packs import evaluate_rule_packs, scan_findings_for_guidance

            force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
            # force starts background job — HTTP never waits on journalctl
            if force:
                request_diagnostics_scan()
            job = diagnostics_job_status()
            # Prefer last completed scan; never block the request thread.
            if job.get("has_result") and job.get("findings") is not None:
                diag = {
                    "scanned_at": job.get("scanned_at"),
                    "counts": job.get("counts") or {},
                    "findings": job.get("findings") or [],
                    "categories": [],
                    "pending": bool(job.get("running")),
                }
            else:
                diag = get_diagnostics(force=False)
            # Snapshot metrics under lock; evaluate outside so scans can't stall sampler.
            with srv._lock:
                full = srv._latest_full
                mem = col._mem_spec or {}
                gt = (full or {}).get("game_totals") or {}
                active = gt.get("game_id") or gt.get("appid")
                running = bool(gt.get("running"))
            ctx = system_context()
            try:
                _, emitted = evaluate_rule_packs(full or {}, mem, ctx)
            except Exception as exc:
                print(f"Cosmic Pulse diagnostics: rule pack eval failed: {exc}", flush=True)
                emitted = set()
            scan = scan_findings_for_guidance(
                diag.get("findings") or [],
                emitted,
                active_appid=str(active) if active else None,
                running=running,
            )
            primary = primary_finding(scan) or primary_finding(diag.get("findings") or [])
            diag = {
                **diag,
                "scan_findings": scan,
                "primary": primary,
                "job": {
                    "status": job.get("status"),
                    "running": bool(job.get("running")),
                    "ready": bool(job.get("has_result")),
                    "error": job.get("error"),
                },
            }
            self._json(diag)
        elif path == "/api/store":
            self._json(srv.enrich_store_stats())
        elif path == "/api/rule-packs":
            from .rule_packs import list_packs, list_rules

            qs = parse_qs(parsed.query)
            if (qs.get("view") or ["packs"])[0] == "rules":
                pack_id = (qs.get("pack") or [None])[0]
                q = (qs.get("q") or [None])[0]
                self._json(
                    {
                        "ok": True,
                        "rules": list_rules(pack_id=pack_id, q=q),
                        "packs": list_packs(include_disabled=True),
                    }
                )
            else:
                packs = list_packs(include_disabled=True)
                self._json(
                    {
                        "ok": True,
                        "packs": packs,
                        "enabled_count": sum(1 for p in packs if p.get("enabled")),
                        "rule_count": sum(p.get("rule_count") or 0 for p in packs if p.get("enabled")),
                    }
                )
        elif path == "/api/trends":
            metric = (qs.get("metric") or ["gpu_junction_c"])[0]
            try:
                hours = float((qs.get("hours") or ["24"])[0])
            except (TypeError, ValueError):
                hours = 24.0
            hours = max(0.1, min(hours, 24.0 * 90.0))  # cap at 90 days
            try:
                bucket = int((qs.get("bucket") or ["60"])[0])
            except (TypeError, ValueError):
                bucket = 60
            bucket = max(1, min(bucket, 3600))
            game_id = (qs.get("game") or [None])[0]
            self._json(
                {
                    "metric": metric,
                    "hours": hours,
                    "bucket_sec": bucket,
                    "game_id": game_id,
                    "points": series(metric, hours, bucket, game_id),
                }
            )
        elif path == "/api/correlation":
            a = (qs.get("a") or ["swap_pct"])[0]
            b = (qs.get("b") or ["pgfault_per_s"])[0]
            try:
                hours = float((qs.get("hours") or ["4"])[0])
            except (TypeError, ValueError):
                hours = 4.0
            hours = max(0.1, min(hours, 48.0))  # correlate is heavy — keep short
            game_id = (qs.get("game") or [None])[0]
            self._json(correlate(a, b, hours, game_id))
        elif path == "/api/game-sessions":
            game_id = (qs.get("game") or [None])[0]
            try:
                days = float((qs.get("days") or ["30"])[0])
            except (TypeError, ValueError):
                days = 30.0
            days = max(0.1, min(days, 90.0))
            self._json(
                {
                    "game_id": game_id,
                    "days": days,
                    "sessions": list_game_sessions(game_id, days),
                    "markers": list_session_markers(game_id, days),
                }
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        # Cap body to limit DoS / accidental huge payloads (JSON control plane)
        _max_post = 256 * 1024
        if length < 0 or length > _max_post:
            self._json({"ok": False, "error": "payload too large"}, status=413)
            return
        try:
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid JSON"}, status=400)
            return
        except UnicodeDecodeError:
            self._json({"ok": False, "error": "invalid encoding"}, status=400)
            return
        if path == "/api/rule-packs":
            from .rule_packs import reload_packs, set_pack_enabled

            action = body.get("action") if isinstance(body.get("action"), str) else ""
            if action == "reload":
                packs = reload_packs()
                self._json({"ok": True, "packs": packs})
                return
            if action in ("enable", "disable"):
                pack_id = body.get("pack_id")
                if not pack_id or not isinstance(pack_id, str):
                    self._json({"ok": False, "error": "pack_id required"}, status=400)
                    return
                result = set_pack_enabled(pack_id.strip(), enabled=(action == "enable"))
                self._json(result, status=200 if result.get("ok") else 400)
                return
            if action == "set_enabled":
                pack_id = body.get("pack_id")
                enabled = body.get("enabled")
                if not pack_id or not isinstance(pack_id, str):
                    self._json({"ok": False, "error": "pack_id required"}, status=400)
                    return
                if not isinstance(enabled, bool):
                    self._json({"ok": False, "error": "enabled must be boolean"}, status=400)
                    return
                result = set_pack_enabled(pack_id.strip(), enabled=enabled)
                self._json(result, status=200 if result.get("ok") else 400)
                return
            self._json(
                {"ok": False, "error": "action must be reload, enable, disable, or set_enabled"},
                status=400,
            )
            return
        if path == "/api/apply-fix":
            # Removed: Pulse never ran fixes; scripts are gone too.
            self._json(
                {
                    "ok": False,
                    "error": "apply-fix removed — use Guidance steps and copy commands",
                    "read_only": True,
                },
                status=410,
            )
            return
        if path == "/api/store":
            if "retention_days" in body:
                try:
                    int(body["retention_days"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "retention_days must be an integer"}, status=400
                    )
                    return
            if "ui_scale" in body:
                try:
                    float(body["ui_scale"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "ui_scale must be a number"}, status=400
                    )
                    return
            if "tuning_log_max" in body:
                try:
                    int(body["tuning_log_max"])
                except (TypeError, ValueError):
                    self._json(
                        {"ok": False, "error": "tuning_log_max must be an integer"}, status=400
                    )
                    return
            if "theme_mode" in body:
                mode = body["theme_mode"]
                if not isinstance(mode, str) or mode.strip().lower() not in THEME_MODES:
                    self._json(
                        {
                            "ok": False,
                            "error": "theme_mode must be " + ", ".join(THEME_MODES),
                        },
                        status=400,
                    )
                    return
            if "hw_scales" in body and not isinstance(body["hw_scales"], dict):
                self._json(
                    {"ok": False, "error": "hw_scales must be an object"},
                    status=400,
                )
                return

            action = body.get("action") if isinstance(body.get("action"), str) else None
            # Confirm gate for destructive actions (store also enforces).
            if action in (
                "clear_samples",
                "clear_tuning_log",
                "reset_guidance_prefs",
                "reset_all_pulse_data",
            ) and body.get("confirm") != "RESET":
                out = srv.enrich_store_stats()
                out["ok"] = False
                out["error"] = "Type RESET to confirm this action"
                self._json(out, status=400)
                return

            result = update_settings(body)
            if not result.get("ok"):
                self._json(srv.enrich_store_stats(result))
                return

            details = dict(result.get("details") or {})
            if action == "clear_tuning_log" or action == "reset_all_pulse_data":
                with srv._lock:
                    n = srv.clear_tuning_log_memory(save=True)
                details["cleared_tuning_entries"] = n
            if action == "trim_tuning_log" or "tuning_log_max" in body:
                with srv._lock:
                    details["trim_tuning_log"] = srv.trim_tuning_log_to_max()
            if action in ("clear_diag_cache", "reset_all_pulse_data"):
                invalidate_diagnostics_cache()
                details["cleared_diag_cache"] = True
            if action in ("clear_samples", "reset_all_pulse_data"):
                srv.clear_live_history_ring()
                details["client_clear_history"] = True

            out = srv.enrich_store_stats(result)
            out["ok"] = True
            if details:
                out["details"] = details
            self._json(out)
            return
        self.send_response(404)
        self.end_headers()
