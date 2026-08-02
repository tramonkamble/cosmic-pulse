# Cosmic Pulse — terminal agent map

Entry: **server.py** (HTTP) + **index.html** (UI). No app.py.

## Product scope (until stated otherwise)

**Primary target:** **Pop!_OS** (minimum bar). **COSMIC DE** is first-class when present; dual-DE (e.g. KDE for gaming) is in-scope because many Pop gamers do that.

**Out of scope for core product until release+community:**
- Distro-specific paths (Fedora, Arch, etc.) beyond “generic Linux that happens to run”
- Non-Pop package managers as first-class install guidance
- Hardware ecosystems we don’t dogfood (e.g. deep NVIDIA driver matrix) — ship as **optional community rule packs**, not builtin defaults

**When adding features:** prefer Pop/System76/Steam/Proton/Mesa-AMD paths that work on this class of rig. Detect other stacks only when cheap; don’t block Pop UX on multi-distro perfection. Community packs (`~/.config/pulse/rules/`, rule-store later) own everything else.

## Review workflow (bash only)
```bash
ls *.py
rg -n "threading|while True|time.sleep|global " server.py store.py stutter.py | head -40
sed -n '1,100p' server.py
python3 -m pytest tests/ -q --tb=line
```

Hot files: server.py, store.py, stutter.py, games.py, diagnostics.py, index.html
