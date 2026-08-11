# UI elements inventory (main / stable dashboard)

Source of truth: `index.html` (~12k lines: CSS + HTML + JS).  
Theme: dark Cosmic/Pop, Inter, CSS variables for metric colors (`--m-cpu`, `--m-gpu`, `--m-mem`, etc.).  
Default UI scale often **1.5×** (`--ui-scale`) for second-monitor / couch distance.

---

## Global chrome

| Element | DOM / notes |
|---------|-------------|
| Sticky **header** | Title “Cosmic Pulse”, host **brand badges** (Pop, System76, DE, kernel, Mesa), nav tabs |
| **Nav tabs** | Dashboard · Guidance · Options |
| **Online pill** + clock | Live connection status |
| **Main** | Max-width ~1920px, stacked pages |

---

## Dashboard page — top to bottom

### 1. Summary card (`#summaryBar`)

**Rig strip** (`#rigStrip`)
- Horizontal hardware tiles: Chassis, CPU, GPU, Memory, Storage
- Click = multi-select HW focus filter (filters live overview / drills)
- Compact brand art + names

**Metric cells** (CSS grid)
| Cell | ID | Shows |
|------|-----|--------|
| CPU | `#sumCpuCell` | Ring % + package temp |
| Memory | `#sumMemCell` | Ring % + used / swap |
| GPU | `#sumGpuCell` | Ring % + hotspot + power |
| Pulse Index | `#sumLeagueCell` | Build index score + class |
| Guidance | `#sumHealthCell` | Warning count + CRIT/WARN/INFO chips (issue list demoted) |
| Game | `#sumGameCell` | Session score, art, smoothness, 1% low, CPU/GPU session avgs |

When a last session exists, game cell goes **full-width prominent** strip under the rings.

**Hardware sensors** (`#sensorStrip`)
- Collapsed by default: temp chips (CPU, GPU, VRAM, NVMe…)
- “Show more” expands I/O + network rates
- “Details →” opens Sensors drill

---

### 2. Live overview (`#vizPanel`)

**Tabs:** Rig snapshot (default) · Pulse Index · Stutter  

#### Rig snapshot — 3 columns (`.rig-layout`)

| Column | Role | Contents |
|--------|------|----------|
| **Left — Load** | “Now” util | Vertical bars: CPU, RAM, GPU, VRAM + one-line context (load avg, GB, W·MHz) |
| **Center — Chart** | “Trend” | Chart.js line “Load · 5 min”; series CPU/GPU/RAM (disk if busy); top color swatches; append-only ring buffer |
| **Right — Vitals** | Thermal / activity | Flat sections: **Power** glance chips · **Temps** bars · **Bus** bars · **Storage** R/W/Busy **dials** (one line) |

**Storage dials** (`.io-compact`)
- Three pills: **R** (read MB/s), **W** (write), **Busy** (%)
- Conic-gradient mini rings + value text
- Replaces older 3 stacked metric bars

**Intentionally demoted / hidden on main**
- Core map / GPU engine strips (`.dash-secondary`)
- Network vitals section
- Chart KPI chips (duplicate of left %)
- Load column status echo `cpu/gpu/ram`
- Chart dual-axis temps (temps only if HW-focus single CPU/GPU)

---

### 3. Drill stack (collapsed `<details>`)

Warnings, Game performance, Sensors, Charts, Bandwidth, Compute, Pulse Index, Drives, System checks, Profiling tools…  
Same data, deeper views — **not** the main clutter problem; Live overview + summary are.

---

### 4. Other pages

- **Guidance:** split index + detail fix scripts  
- **Options:** UI scale, theme mode, data paths, rule packs  

---

## Metric color system (keep consistent)

| Family | Token-ish | Use |
|--------|-----------|-----|
| CPU | sky blue `--m-cpu` | bars, rings, chart |
| GPU | violet `--m-gpu` | bars, rings, chart |
| Memory | emerald `--m-mem` | bars, rings, chart |
| Storage | amber `--m-disk` | I/O, dials |
| Thermal | rose `--m-thermal` | temp values when hot |
| Stutter / game | fuchsia / pink | session scores |

---

## Visual problems still visible (honest)

1. **Live overview** still feels sparse + busy: large empty region under short left/center when right rail is tall; chart often flat at idle.  
2. **Summary** still dense: rig tiles + rings + game strip + sensors before Live overview.  
3. **Nested “dashboard in a dashboard”** risk on the right rail (power + temps + bus + storage).  
4. **Type/spacing** still inconsistent in places (many rem one-offs remain).  
5. **Chart at idle** can look empty (tip dots only) — not always a bug.  

---

## Industry reference (user intent)

Compare to **AMD Adrenaline** performance metrics / overlay:  
**Keep front-and-center:** GPU %, GPU temp, VRAM, CPU %, RAM, power, FPS/session when gaming.  
**Demote or compact:** network rates, specialist bus % as walls of bars, duplicate readouts, OS/chrome badges noise.  
**Fun to keep:** bus throughput, storage activity — but **compact** (dials / one-liners), not three full bars.
