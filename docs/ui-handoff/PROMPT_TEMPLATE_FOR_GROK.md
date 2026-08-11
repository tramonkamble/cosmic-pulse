# Skeleton — Gemini should produce a filled, self-contained version

```text
You are implementing a focused UI pass on Cosmic Pulse (perf-dashboard).

## Context
- Branch: main
- File: index.html (CSS + DOM + JS)
- Product: Pop!_OS / COSMIC game performance dashboard
- Live: http://127.0.0.1:8765/
- Prior work: [Gemini fills: what not to redo]

## Goal of THIS pass only
[One sentence]

## Problems to fix (from screenshots)
1. ...
2. ...

## Concrete changes
### Live overview
- ...
### Summary (only if needed)
- ...
### Chart
- ...
### Storage / bus
- ...

## Constraints
- No framework; no backend rewrite
- Keep metric poll IDs working: utilMeters, sparkChart, tempMeters, bwMeters, ioMeters, glanceGrid
- Do not reintroduce dual-axis temps on default load chart
- Do not remove bus or storage activity (compact OK)
- Preserve HW focus filters on rig strip
- Prefer CSS + small HTML; minimal JS

## Acceptance
- [ ] Screenshot criteria 1
- [ ] Screenshot criteria 2
- [ ] Hard-refresh shows changes without server rewrite
- [ ] No broken live metrics

## Don’t touch
- beta/ui-noc branch
- Guidance/Options pages (unless required)
- Python metrics pipeline

## Deliver
Implement on main, commit with a clear message, summarize what changed.
```
