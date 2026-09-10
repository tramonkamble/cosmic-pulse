# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Read COSMIC desktop theme tokens from ~/.config/cosmic."""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

COSMIC_ROOT = Path.home() / ".config/cosmic"
SHARE_ROOT = Path("/usr/share/cosmic")

# mtime-based cache: re-parse only when COSMIC theme files change (light/dark flip, accent, …)
_LAST_MTIME: float = 0.0
_THEME_CACHE: dict[str, dict] = {}
_THEME_LOCK = threading.RLock()

# Hardcoded fallback when not on Pop/COSMIC (or config missing).
_FALLBACK_THEME: dict = {
    "available": False,
    "is_dark": True,
    "is_frosted": False,
    "palette": "pulse-fallback",
    "accent": "#e95420",
    "accent_hover": "#f06a3a",
    "accent_soft": "rgba(233, 84, 32, 0.14)",
    "accent_on": "#000000",
    "bg": "#1b1b1b",
    "panel": "#2a2d34",
    "panel_solid": "#2a2d34",
    "panel_elevated": "#343840",
    "panel_hover": "#3a3e48",
    "text": "#d8e0ef",
    "text_secondary": "#b0b8c8",
    "muted": "#ababab",
    "line": "rgba(255,255,255,0.12)",
    "divider": "rgba(255,255,255,0.12)",
    "blue": "#63d0df",
    "purple": "#c084fc",
    "green": "#92cf9c",
    "orange": "#ffad00",
    "hot": "#fd9fa0",
    "amber": "#f7e062",
    "ok": "#92cf9c",
    "glass": "rgba(27, 27, 27, 0.94)",
    "radius": 8,
    "radius_lg": 16,
    "space_m": 24,
    "chart": {"accent": "#e95420", "hot": "#fd9fa0", "warn": "#f7e062"},
    "mtime": 0.0,
}

_FALLBACK_THEME_LIGHT: dict = {
    "available": False,
    "is_dark": False,
    "is_frosted": False,
    "palette": "pulse-fallback-light",
    "accent": "#7c3aed",
    "accent_hover": "#6d28d9",
    "accent_soft": "rgba(124, 58, 237, 0.12)",
    "accent_on": "#ffffff",
    "bg": "#e6ebf3",
    "panel": "#ffffff",
    "panel_solid": "#ffffff",
    "panel_elevated": "#f4f6fb",
    "panel_hover": "#eef1f7",
    "text": "#111827",
    "text_secondary": "#374151",
    "muted": "#4b5563",
    "line": "rgba(17, 24, 39, 0.14)",
    "divider": "rgba(17, 24, 39, 0.12)",
    "blue": "#0369a1",
    "purple": "#6d28d9",
    "green": "#047857",
    "orange": "#b45309",
    "hot": "#b91c1c",
    "amber": "#a16207",
    "ok": "#047857",
    "glass": "rgba(255, 255, 255, 0.92)",
    "radius": 8,
    "radius_lg": 16,
    "space_m": 24,
    "chart": {"accent": "#7c3aed", "hot": "#b91c1c", "warn": "#a16207"},
    "mtime": 0.0,
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _safe_mtime(path: Path) -> float:
    try:
        return float(os.path.getmtime(path))
    except OSError:
        return 0.0


def _theme_config_mtime() -> float:
    """Max mtime across Mode + Dark/Light theme token files (cheap, no parse)."""
    mt = 0.0
    mode = COSMIC_ROOT / "com.system76.CosmicTheme.Mode" / "v1"
    for name in ("is_dark", "is_high_contrast"):
        mt = max(mt, _safe_mtime(mode / name))
    for theme in ("Dark", "Light"):
        base = COSMIC_ROOT / f"com.system76.CosmicTheme.{theme}" / "v1"
        if not base.is_dir():
            continue
        mt = max(mt, _safe_mtime(base))
        for fname in (
            "accent",
            "background",
            "primary",
            "palette",
            "spacing",
            "corner_radii",
            "is_frosted",
            "destructive",
            "success",
            "warning",
        ):
            mt = max(mt, _safe_mtime(base / fname))
    return mt


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() == "true"


def _color_tuple(text: str, label: str) -> tuple[float, float, float, float] | None:
    pat = rf"{re.escape(label)}:\s*\(\s*red:\s*([-\d.]+)\s*,\s*green:\s*([-\d.]+)\s*,\s*blue:\s*([-\d.]+)\s*,\s*alpha:\s*([-\d.]+)\s*,?\s*\)"
    m = re.search(pat, text, re.DOTALL)
    if not m:
        return None
    return tuple(float(m.group(i)) for i in range(1, 5))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _to_hex(r: float, g: float, b: float, a: float = 1.0) -> str:
    r, g, b = (_clamp01(r), _clamp01(g), _clamp01(b))
    if a >= 0.999:
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {a:.3f})"


def _pick_color(text: str, *labels: str) -> str | None:
    for label in labels:
        tup = _color_tuple(text, label)
        if tup:
            return _to_hex(*tup)
    return None


def _section(text: str, name: str) -> str:
    needle = f"{name}:"
    idx = text.find(needle)
    if idx < 0:
        return ""
    rest = text[idx + len(needle) :].lstrip()
    if not rest.startswith("("):
        return ""
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return rest[1:i]
    return ""


def _nested_color(text: str, outer: str, inner: str) -> str | None:
    block = _section(text, outer)
    return _pick_color(block, inner) if block else None


def _spacing_value(text: str, key: str) -> int | None:
    m = re.search(rf"{re.escape(key)}:\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _radius_value(text: str, key: str) -> int | None:
    m = re.search(rf"{re.escape(key)}:\s*\(\s*([\d.]+)", text)
    return int(float(m.group(1))) if m else None


def _palette_color(text: str, key: str) -> str | None:
    return _pick_color(text, key)


def _theme_base(theme_name: str) -> Path | None:
    """Prefer ~/.config/cosmic, then /usr/share/cosmic, when token files exist."""
    for root in (COSMIC_ROOT, SHARE_ROOT):
        base = root / f"com.system76.CosmicTheme.{theme_name}" / "v1"
        if (base / "background").is_file() and (base / "palette").is_file():
            return base
    return None


def load_cosmic_theme(*, force: str | None = None) -> dict:
    """Return CSS-ready COSMIC theme tokens, or fallback when not available.

    ``force`` is ``dark``, ``light``, or None (follow the desktop Mode file).
    """
    want_light = force == "light"
    want_dark = force == "dark"
    fallback = dict(_FALLBACK_THEME_LIGHT if want_light else _FALLBACK_THEME)
    if not COSMIC_ROOT.is_dir():
        fallback["mtime"] = 0.0
        return fallback

    mode_dir = COSMIC_ROOT / "com.system76.CosmicTheme.Mode" / "v1"
    if want_light:
        is_dark = False
    elif want_dark:
        is_dark = True
    else:
        is_dark = (
            _parse_bool(_read_text(mode_dir / "is_dark")) if (mode_dir / "is_dark").exists() else True
        )
    theme_name = "Dark" if is_dark else "Light"
    base = _theme_base(theme_name)
    if base is None:
        fallback["mtime"] = _theme_config_mtime()
        return fallback

    accent_txt = _read_text(base / "accent")
    bg_txt = _read_text(base / "background")
    primary_txt = _read_text(base / "primary")
    palette_txt = _read_text(base / "palette")
    spacing_txt = _read_text(base / "spacing")
    radii_txt = _read_text(base / "corner_radii")
    frosted = (base / "is_frosted").exists() and _parse_bool(_read_text(base / "is_frosted"))

    accent = _pick_color(accent_txt, "base") or "#e95420"
    accent_hover = _pick_color(accent_txt, "hover") or accent
    bg = _pick_color(bg_txt, "base") or "#1b1b1b"
    panel = (
        _nested_color(bg_txt, "component", "base")
        or _nested_color(primary_txt, "component", "base")
        or "#40434a"
    )
    panel_hover = (
        _nested_color(bg_txt, "component", "hover")
        or _nested_color(primary_txt, "component", "hover")
        or panel
    )
    panel_elevated = _nested_color(primary_txt, "component", "hover") or panel_hover
    text = _pick_color(bg_txt, "on") or _pick_color(primary_txt, "on") or "#d8e0ef"
    divider = _pick_color(bg_txt, "divider") or "rgba(255,255,255,0.12)"
    comp_divider = _nested_color(bg_txt, "component", "divider") or divider

    destructive = _pick_color(_read_text(base / "destructive"), "base") or "#fd9fa0"
    success = _pick_color(_read_text(base / "success"), "base") or "#92cf9c"
    warning = _pick_color(_read_text(base / "warning"), "base") or "#f7e062"

    blue = _palette_color(palette_txt, "accent_blue") or "#63d0df"
    purple = _palette_color(palette_txt, "accent_purple") or accent
    green = _palette_color(palette_txt, "accent_green") or success
    orange = _palette_color(palette_txt, "accent_orange") or "#ffad00"

    radius_m = _radius_value(radii_txt, "radius_m") or 16
    radius_s = _radius_value(radii_txt, "radius_s") or 8
    space_m = _spacing_value(spacing_txt, "space_m") or 24

    accent_rgb = _color_tuple(accent_txt, "base")
    accent_soft = (
        _to_hex(accent_rgb[0], accent_rgb[1], accent_rgb[2], 0.14)
        if accent_rgb
        else "rgba(233, 84, 32, 0.14)"
    )

    palette_name = ""
    if m := re.search(r'name:\s*"([^"]+)"', palette_txt):
        palette_name = m.group(1)

    on_accent = _pick_color(accent_txt, "on") or "#000000"
    bg_tup = _color_tuple(bg_txt, "base")
    if frosted and bg_tup:
        glass = _to_hex(bg_tup[0], bg_tup[1], bg_tup[2], 0.72)
    else:
        glass = _to_hex(*(bg_tup or (0.105, 0.105, 0.105, 1.0))[:3], 0.94)

    mtime = _theme_config_mtime()
    return {
        "available": True,
        "is_dark": is_dark,
        "is_frosted": frosted,
        "palette": palette_name or f"cosmic-{theme_name.lower()}",
        "accent": accent,
        "accent_hover": accent_hover,
        "accent_soft": accent_soft,
        "accent_on": on_accent,
        "bg": bg,
        "panel": panel,
        "panel_solid": panel,
        "panel_elevated": panel_elevated,
        "panel_hover": panel_hover,
        "text": text,
        "text_secondary": _pick_color(primary_txt, "on") or text,
        "muted": (
            _palette_color(palette_txt, "neutral_5")
            if not is_dark
            else _palette_color(palette_txt, "neutral_7")
        )
        or ("#4b5563" if not is_dark else "#ababab"),
        "line": comp_divider,
        "divider": divider,
        "blue": blue,
        "purple": purple,
        "green": green,
        "orange": orange,
        "hot": destructive,
        "amber": warning,
        "ok": success,
        "glass": glass,
        "radius": radius_s,
        "radius_lg": radius_m,
        "space_m": space_m,
        # Series colors are owned by the UI metric palette (index.html METRIC/CHART).
        "chart": {
            "accent": accent,
            "hot": destructive,
            "warn": warning,
        },
        # For clients: detect Light↔Dark without deep token diffs
        "mtime": mtime,
        # Aliases requested by theme-sync API consumers
        "bg-color": bg,
        "text-color": text,
    }


def get_cosmic_theme(ttl_sec: float = 8.0, *, force: str | None = None) -> dict:
    """Return COSMIC tokens, reloading only when config files' mtime advances.

    ``force`` is ``dark``, ``light``, or None (desktop Mode). ``ttl_sec`` is
    retained for call-site compatibility but **mtime wins**.
    """
    global _LAST_MTIME, _THEME_CACHE
    _ = ttl_sec  # legacy arg
    key = (force or "auto").lower()
    if key not in ("auto", "dark", "light"):
        key = "auto"
    try:
        mtime = _theme_config_mtime()
    except OSError:
        mtime = 0.0

    with _THEME_LOCK:
        if mtime != _LAST_MTIME:
            _THEME_CACHE = {}
        cached = _THEME_CACHE.get(key)
        if cached and mtime == _LAST_MTIME and mtime > 0:
            return cached

        try:
            theme = load_cosmic_theme(force=None if key == "auto" else key)
        except OSError:
            theme = dict(_FALLBACK_THEME_LIGHT if key == "light" else _FALLBACK_THEME)
            theme["mtime"] = mtime

        if "mtime" not in theme or theme.get("mtime") is None:
            theme["mtime"] = mtime
        _LAST_MTIME = float(theme.get("mtime") or mtime or 0.0)
        _THEME_CACHE[key] = theme
        return theme


def get_cosmic_theme_pack() -> dict[str, dict]:
    """Desktop-follow plus explicit Dark/Light packs for Options."""
    return {
        "auto": get_cosmic_theme(),
        "dark": get_cosmic_theme(force="dark"),
        "light": get_cosmic_theme(force="light"),
    }
