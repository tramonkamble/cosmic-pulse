# Design context for next UI pass

## Product

**Cosmic Pulse** — local web UI for gaming performance on **Pop!_OS** (COSMIC DE first-class; dual-DE OK).  
Not a general multi-distro control panel. Not a full NOC (that experiment lives on `beta/ui-noc`).

**Primary user job:** Glance while gaming / after a session — is the rig healthy, what bottlenecked, what should I fix?

---

## Design principles (owner feedback)

1. **Like the original UI direction** — don’t replace with a radical NOC/wallboard on `main`.  
2. **Busy & inconsistent** today — text, borders, spacing, and information density.  
3. **Prefer graceful cleanup** over rewrites: minor but comprehensive passes; preserve metrics the user likes.  
4. **Cull noise from main screen** — if mostly useless, hide or move to drill / Options “power user” later.  
5. **Bus / I/O is fun and useful** — don’t delete; **compact** (user liked bus; storage should be one-line dials, not three bars).  
6. **Middle load chart** was over-changed and became hard to read — dual-axis temps made it “weird”; prefer simple load trends.  
7. **Too many passes stack badly** — next prompt should be **focused**, not another kitchen-sink redesign.

---

## Recent work (so Gemini doesn’t re-propose it)

| Pass | What happened |
|------|----------------|
| Pass 1 consistency | Tokens for space/labels; demoted specialist noise |
| Density pass | Tighter padding; summary grid reflow (guidance strip) |
| Live overview declutter | Removed KPI chips, flattened vitals, chart as hero |
| Storage + chart fix | Storage → R/W/Busy dials; chart load-only by default |

Still **not good enough** per owner: Live overview “looks better but seems bad still”; chart weird after too many changes; storage bars were the wrong density (now dials — evaluate if dials work).

---

## Technical constraints for implementers (Grok)

- **One file for UI:** `index.html` (CSS in `<style>`, app JS inline). Prefer CSS + small HTML; avoid new frameworks.  
- **Keep metric IDs / poll loops** working: `#utilMeters`, `#sparkChart`, `#tempMeters`, `#bwMeters`, `#ioMeters`, `#glanceGrid`, etc.  
- **Chart.js** for sparklines.  
- **HW focus filters** (`data-hw`, `#rigStrip`) must keep working.  
- **No backend redesign** unless a UI need forces a tiny API field.  
- Branch: work on **`main`** for stable UI; experimental UIs go on `beta/ui-*`.  
- Run tests if Python touched: `python3 -m pytest tests/ -q --tb=line`.

---

## Success criteria (for Gemini’s Grok prompt)

A good next pass would make the owner say:

- Live overview is **scannable in 2 seconds**  
- Clear hierarchy: **now (left) · trend (center) · thermals/activity (right)**  
- **No triple-redundant** CPU/GPU/RAM presentations  
- Storage / bus visible but **not tall stacks**  
- Chart **readable when idle and under load**  
- Summary still useful but doesn’t push Live overview off a 1080p second monitor  
- Changes feel **intentional and small**, not a new product  

---

## Anti-goals

- Another full NOC redesign on `main`  
- Random new accent gradients / rainbow frames “for flair”  
- Removing metrics the user called fun (bus, storage activity)  
- Parallel `index-beta.html` forks (use git branches)  
- Touching Guidance/Options unless necessary for density  
