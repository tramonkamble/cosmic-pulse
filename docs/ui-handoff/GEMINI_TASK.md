# Task for Gemini — write an implementation prompt for Grok

You are a **senior product designer + design systems critic**. You are **not** implementing code.

The human will attach screenshots of **Cosmic Pulse**, a dark Pop!_OS / COSMIC-first **game performance dashboard**, plus optional text files:

- `UI_ELEMENTS.md` — inventory of UI regions and metrics  
- `DESIGN_CONTEXT.md` — goals, constraints, recent failed/partial passes  

## Your job

1. **Look carefully** at the screenshots (full page, summary, live overview, vitals, chart).  
2. Diagnose **what still feels cluttered, sparse, inconsistent, or hard to read** — be specific (regions, not vibes only).  
3. Propose a **single focused next UI pass** (not a full redesign). Prefer hierarchy, density, and chart readability over new features.  
4. Output a **ready-to-paste prompt for Grok** (coding agent) that will implement that pass in `index.html`.

## Rules for your Grok prompt

The prompt you write **must**:

- Target **`main` stable UI** in `perf-dashboard/index.html` only (unless a tiny CSS/HTML change needs a note).  
- Say **graceful cleanup, no rewrite** of the app architecture.  
- List **concrete visual changes** (what to merge, hide, compact, re-space) tied to named regions: summary bar, live overview load column, chart, vitals rail, storage dials, sensor strip.  
- Preserve **metrics the owner likes**: CPU/GPU/RAM/VRAM load, bus throughput, storage activity (may be compact), temps, power, game session strip.  
- Avoid reintroducing: dual-axis temp overlay on the main load chart by default; triple duplicate CPU/GPU/RAM chips; three tall storage bars.  
- Include **acceptance checks** (what “done” looks like in a screenshot).  
- Include **don’t-touch** list (backend, Guidance page, Options, beta NOC branch).  
- Stay **one pass** — optional “later” bullets only as non-blocking backlog, not scope.

## Output format (strict)

Return **exactly two sections**:

### 1. Design critique (short)
Bullet list of the top 5–8 issues you see in the screenshots, ordered by severity.

### 2. Prompt for Grok (copy-paste block)
A fenced code block containing the full prompt the human will give Grok.  
Write it in second person (“You are…”, “Implement…”, “Do not…”).  
Be specific enough that an engineer who has **not** seen this chat can execute it.

Also fill in the skeleton ideas from `PROMPT_TEMPLATE_FOR_GROK.md` if helpful, but **your fenced prompt must be self-contained**.

## Design taste to apply

- **AMD Adrenaline / performance overlay** simplicity for “what matters while gaming.”  
- Dark desktop utility: elevation and gap > endless 1px boxes.  
- One primary focal region in Live overview (the trend chart), supporting columns for now + thermals.  
- Idle charts can be quiet; under load they must read clearly.  
- Second-monitor readability (UI scale ~1.5 is normal).

## Do not

- Do not invent metrics that don’t exist in the inventory.  
- Do not recommend React/Vue or splitting `index.html` in this pass.  
- Do not write the full CSS/JS implementation yourself — only the **prompt for Grok**.  
- Do not expand scope to the experimental NOC UI unless the human asks.
