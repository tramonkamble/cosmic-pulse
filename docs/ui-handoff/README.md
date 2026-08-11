# Cosmic Pulse UI handoff pack

**Purpose:** Give **Gemini** (or another designer/LLM) enough visual + structural context to write a **sharp implementation prompt for Grok** on the next UI pass.

**Repo / branch:** `perf-dashboard` · **`main`** @ `2a6f3a5` (update if you re-export)  
**App:** Cosmic Pulse — Pop!_OS / COSMIC-first game performance dashboard  
**UI file:** single mega-file `index.html` (CSS + DOM + JS). Backend is `server.py` (don’t redesign API in this pass).

**Live app (local):** `http://127.0.0.1:8765/`

---

## What’s in this folder

| Path | What |
|------|------|
| `shots/` | Screenshots of the **current** shipping UI |
| `UI_ELEMENTS.md` | Inventory of regions, metrics, components |
| `DESIGN_CONTEXT.md` | Product goals, constraints, recent pass history |
| `GEMINI_TASK.md` | **← Paste this to Gemini** (instructions + what to produce) |
| `PROMPT_TEMPLATE_FOR_GROK.md` | Empty shape Gemini should fill for Grok |

---

## Screenshots (`shots/`)

| File | Content |
|------|---------|
| `01-full-dashboard.png` | Full page (summary + live overview + drill stack top) |
| `02-summary-and-sensors.png` | Header, rig strip, summary cells, game strip, sensor strip |
| `03-live-overview.png` | Live overview 3-column band |
| `04-live-overview-vitals.png` | Right rail: power / temps / bus / storage dials |
| `05-live-overview-chart.png` | Center load chart crop |

Re-capture anytime:

```bash
cd ~/perf-dashboard
firefox --headless --window-size 1680,2200 \
  --screenshot "$(pwd)/docs/ui-handoff/shots/01-full-dashboard.png" \
  "http://127.0.0.1:8765/"
# then re-run crops from docs/ui-handoff if needed
```

---

## How to use with Gemini

1. Open **Gemini** (prefer a model that can see images).
2. Attach **all** `shots/*.png` (or at least `01`, `02`, `03`).
3. Paste the full contents of **`GEMINI_TASK.md`**.
4. Optionally attach `UI_ELEMENTS.md` + `DESIGN_CONTEXT.md` as text files (or paste them).
5. Copy Gemini’s output prompt → give that prompt to **Grok** in the Pulse coding session.

---

## Out of scope for this handoff

- Rewriting Python backend / metrics collection
- The experimental branch `beta/ui-noc` (NOC wallboard) — this pack is **`main` stable UI only**
- Brand-new product features (new metrics, new tabs) unless they reduce clutter
