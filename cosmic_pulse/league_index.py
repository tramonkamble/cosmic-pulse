# SPDX-FileCopyrightText: 2026 Pulse contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Published relative gaming scores for Pulse Index.

Snapshot of Tom's Hardware GPU/CPU hierarchies — not a live scrape.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data" / "league_index.json"

# DDR5-6000 dual-channel peak (Tom's 2026 GPU bench kit).
MEM_REF_GBPS = 96.0


@lru_cache(maxsize=1)
def load_league_index() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def league_meta() -> dict[str, Any]:
    return dict(load_league_index().get("meta") or {})


def cpu_published(name: str) -> dict[str, Any] | None:
    row = (load_league_index().get("cpu") or {}).get(name)
    return dict(row) if row else None


def gpu_published(name: str) -> dict[str, Any] | None:
    row = (load_league_index().get("gpu") or {}).get(name)
    return dict(row) if row else None


def memory_tier_score(peak_gbps: float) -> float:
    if not peak_gbps:
        return 0.0
    return round(min(100.0, float(peak_gbps) / MEM_REF_GBPS * 100.0), 1)


def apply_cpu_scores(tiers: list[dict]) -> list[dict]:
    out = []
    for t in tiers:
        pub = cpu_published(t["name"])
        row = dict(t)
        if pub:
            row["score"] = pub["score"]
            if pub.get("class"):
                row["class"] = pub["class"]
            row["score_estimated"] = bool(pub.get("estimated"))
        else:
            row["score_estimated"] = True
        out.append(row)
    return out


def apply_gpu_sku_scores(skus: list[dict[str, Any]]) -> None:
    """Mutate SKU table scores in place from the published snapshot."""
    for sku in skus:
        pub = gpu_published(sku["name"])
        if not pub:
            sku["score_estimated"] = True
            continue
        sku["score"] = pub["score"]
        if pub.get("class"):
            sku["class"] = pub["class"]
        sku["score_estimated"] = bool(pub.get("estimated"))
