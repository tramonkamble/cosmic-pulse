# Cosmic Pulse — terminal agent map

Entry: **server.py** (HTTP) + **index.html** (UI). No app.py.

## UI branches (beta experiments)

**`main` ships the stable UI.** Alternate UIs live on branches only (not parallel `index-*.html` folders) so the API/server stay shared.

| Branch | Role |
|--------|------|
| `main` | Stable / shipping dashboard UI |
| `beta/ui-*` | Experimental frontends (same `index.html`, different design) |

Current beta: **`beta/ui-noc`** — Cosmic NOC wallboard (dials, Lab shell, session poster wall). Diff is **`index.html` only** vs `main`.

```bash
# daily / release work
git checkout main

# continue a beta UI
git checkout beta/ui-noc

# new experiment from stable
git checkout main && git checkout -b beta/ui-<name>
```

Do not merge beta UI into `main` until explicitly promoted. Backend/Python work should land on `main` first, then rebase beta branches.

## Product scope (until stated otherwise)

**Primary target:** **Pop!_OS** (minimum bar). **COSMIC DE** is first-class when present; dual-DE (e.g. KDE for gaming) is in-scope because many Pop gamers do that.

### 0.1 ship gates (both required)

**Do not tag or ship 0.1 until every ship-blocker in `backlog.json` is cleared.**

#### A — Rules: small scaffold, community owns the smarts

**Do not ship the first public build until builtin Guidance is cut to ~5–10 simple rules.**

- Cosmic Pulse **0.1 ships the engine**: live metrics, UI, rule-pack loader, Guidance steps, history.
- Builtin pack is a **scaffold** of obvious, high-confidence tips — not a full coach.
- **Community** (people smarter about specific games/distros/GPUs) owns richer rulesets that improve games.
- Today `rules/builtin/pulse-default/` is large (~30+ insights) — **dev dogfood**, not release shape.
- Backlog: `rules-minimal-for-0.1` (`priority: ship-blocker`).

**Scaffold shape (illustrative — finalize at cleanup time):**

| Kind | Examples (existing ids where we already have them) |
|------|-----------------------------------------------------|
| System / kernel | powersave governor, swappiness too high |
| Memory pressure | swap thrash (if kept simple) |
| GPU while gaming | GPU-bound → frame/FPS limit to display (e.g. `gpu-fps-cap`) |
| Thermal (optional) | critical GPU hot only — no essay cards |
| One free Valve demo | **CS2 (730)** preferred, or **TF2 (440)** — one game-scoped example as a community pack template, not a full title guide |

**Not in 0.1 builtin:** audio rule walls, tools shopping lists, deep Steam health encyclopedia, multi-title pro tips. **Later:** Heroic / Lutris / other launchers (`launcher-heroic-etc`, post-0.1) — Steam-first for ship.

#### B — Daddy must be happy with the UI

**Do not ship until the owner (daddy) explicitly signs off on the UI.**

- Metrics reliability and code review do **not** unlock 0.1 without that human yes.
- We are **much closer** after hierarchy / Live lab / family colors — closer is not shipped.
- Agents propose passes; **only daddy declares the UI good enough to release**.
- Backlog: `ui-daddy-signoff-for-0.1` (`priority: ship-blocker`).

**Out of scope for core product until release+community:**
- Distro-specific paths (Fedora, Arch, etc.) beyond “generic Linux that happens to run”
- Non-Pop package managers as first-class install guidance
- Hardware ecosystems we don’t dogfood (e.g. deep NVIDIA driver matrix) — ship as **optional community rule packs**, not builtin defaults
- Per-game “pro tips” encyclopedias in the builtin pack

**When adding features:** prefer Pop/System76/Steam/Proton/Mesa-AMD paths that work on this class of rig. Detect other stacks only when cheap; don’t block Pop UX on multi-distro perfection. Community packs (`~/.config/pulse/rules/`, rule-store later) own everything else.

**When adding rules:** default answer for 0.1 is **no** — put it in a community pack design, not `pulse-default`.

## Review workflow (bash only)
```bash
ls *.py
rg -n "threading|while True|time.sleep|global " server.py store.py stutter.py | head -40
sed -n '1,100p' server.py
python3 -m pytest tests/ -q --tb=line
```

Hot files: server.py, store.py, stutter.py, games.py, diagnostics.py, index.html
