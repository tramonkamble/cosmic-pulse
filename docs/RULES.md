# Writing Guidance rules

Pulse Guidance is **data**, not Python. A rule pack is a folder of YAML. The engine
(`cosmic_pulse/rule_packs.py`) loads packs every sampler tick, evaluates `detect`,
and if it matches, emits a Guidance card with copy-paste steps.

Pulse **never runs** those commands. The user copies them.

**Start here**

| File | Why |
|------|-----|
| [rules/builtin/pulse-core/rules.yaml](../rules/builtin/pulse-core/rules.yaml) | Five real rules. Best first read: `cpu-governor-powersave` (one leaf), then `stutter-proxy` (`all` / `any` / `level_when`). |
| [rules/examples/hello-swappiness/](../rules/examples/hello-swappiness/) | Same shape, comments on every field. Copy this to write a community pack. |
| This doc | Schema, metric catalog, style (“rules for rules”). |
| [RULE_PACKS.md](../RULE_PACKS.md) | What ships vs what belongs in community packs. |

Builtin packs stay small on purpose. Game-specific and distro-specific advice belongs in
**community packs** under `~/.config/pulse/rules/<pack-id>/`.

---

## Pack layout

```
~/.config/pulse/rules/my-pack/
  pack.yaml      # id, name, when this pack is eligible
  rules.yaml     # list of rules (or split across files listed in pack.yaml)
```

Search order (first root that defines a given pack **id** wins):

1. `PULSE_RULE_PATH` (colon-separated, for development)
2. `rule_pack_paths` in `.pulse_config.json`
3. `rules/builtin/` (shipped)
4. `~/.config/pulse/rules/`
5. `~/.local/share/pulse/rule-packs/`

Each root is a directory of pack folders (`*/pack.yaml`). Disable a pack in Options
or `disabled_packs` in config.

The example pack is **not** loaded from `rules/builtin/`. Copy it, or point
`PULSE_RULE_PATH` at `rules/examples`.

### `pack.yaml`

```yaml
id: my-pack                 # directory name should match
name: My pack
version: "0.1.0"
requires_pulse: "0.1"       # documentation only today
priority: 50                # higher evaluates first; first matching insight_id wins
match_when:                 # optional; omit = always eligible
  metric: platform.is_pop
  eq: true
rules:
  - rules.yaml              # files relative to this folder
```

Shipped packs: `pulse-core` is `priority: 10` (always on), `popos-core` is `100`
(Pop only). Community packs that should override a builtin insight use a **higher**
number and the **same** `insight_id`.

`match_when` uses the same condition language as `detect` (below). Example: only
on NVIDIA (`platform.is_nvidia`), only on KDE (`platform.is_kde`).

Optional extras (community only — keep them out of builtin):

- `game_overrides:` per-AppID Steam detection (`name`, `short`, `main_exe`, `exclude_exe`)
- `legacy_game_ids:` old slug → Steam AppID
- `inline_rules:` a list of rule dicts in the manifest (same shape as `rules.yaml`)

---

## A rule

Every rule has `id`, `detect`, `emit`, and usually `actions`.

```yaml
rules:
  - id: cpu-governor-powersave          # stable id — do not rename after ship
    detect:
      metric: ctx.governor
      eq: powersave
    emit:
      insight_id: cpu-governor-powersave  # usually same as id
      level: warn                         # info | warn | hot
      title: CPU stuck in power-save mode
      text: >-
        Governor is '{ctx.governor}' — cores may not boost while gaming.
    actions:
      - label: Set performance governor (until reboot)
        kind: cmd
        cmd: echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

That rule ships in `pulse-core`. Walk it, then read `stutter-proxy` for `all` / `any`
and `level_when`.

### `detect`

A **leaf** is `{ metric: dotted.path, OP: value }`.

| Operator | Meaning |
|----------|---------|
| `eq` / `ne` | Equal / not equal (bools, numbers, strings) |
| `gt` / `gte` / `lt` / `lte` | Numeric compare |
| `in` / `not_in` | Value in a YAML list |
| `exists` / `not_exists` | Flattened value is not `None` / is `None` |

`exists: true` means “this path resolved to something.” A missing path **or** an
explicit `None` is `not_exists`. Do not use `eq: 0` to mean “unknown” — many
sensors default to `0` when the reading is missing.

Combine leaves:

```yaml
detect:
  all:                    # every child true
    - metric: game.running
      eq: true
    - any:                # at least one true
        - metric: stutter.event
          eq: true
        - metric: stutter.score
          gte: 42
    - not:
        metric: load_phase.in_grace
        eq: true
```

`detect: true` always matches (almost never what you want). Empty `all: []` is
true; empty `any: []` is false.

### `emit`

| Field | Meaning |
|-------|---------|
| `insight_id` | Stable key in history / ignore / mark-fixed. Keep it forever. |
| `level` | `info`, `warn`, or `hot` |
| `level_when` | Optional tree: if `detect` then this level else that level (can nest) |
| `title` / `text` | Card copy. `{dotted.path}` and `{path:.0f}` templates. |
| `games` | `all` (default), `active` (running Steam AppID), a string AppID, or a list |
| `bucket` | Optional UI group (`steam`, `tools`, `resolutions`, …) |
| `condition_live` | `true` if this card is “live this tick” (badge), not only outstanding |
| `requires_root` | Override; otherwise `apply_fix.py` looks up `insight_id` |

Templates in **actions** that do not resolve are **dropped** (so the UI never
shows `{gpu.junction_c}` as a command). Unresolved templates in `title` / `text`
are left as-is — put `exists` in `detect` when a template is required.

`games: all` as a YAML **string** is fine (the engine does not iterate it as
`a,l,l`). `games: active` with no running title becomes `all`.

### `actions`

Pulse copies; it does not execute.

| `kind` | UI hint |
|--------|---------|
| `cmd` | Terminal command (default) |
| `note` | Not a command — OSD / “do this in the game” |
| `steam` | Steam launch options |
| `game` | In-game settings |

Fields: `label`, `kind`, `cmd`, `note`. All four are templated.

---

## Metric catalog

`detect` and `{templates}` read **flattened** names from `flatten_metrics()` in
`cosmic_pulse/rule_packs.py`, not the raw `/api/metrics` JSON. Dot paths walk dicts
(and numeric list indexes). That function is the source of truth; YAML cannot
invent a sensor.

| Prefix | Examples |
|--------|----------|
| `ctx.` | `governor`, `swappiness`, `gpu_model` |
| `platform.` | `is_pop`, `is_cosmic`, `is_kde`, `is_gnome`, `is_xfce`, `is_cinnamon`, `is_hyprland`, `is_gamescope`, `is_nvidia`, `is_amd_gpu`, `is_intel_gpu`, `gpu_driver`, `gpu_stack`, `desktop` |
| `session.` | `wayland`, `desktop` |
| `game.` | `running`, `appid`, `name`, `proton`, `wayland_fix_missing` |
| `display.` | `refresh_hz`, `cap_hz`, `hdr_capable`, `hdr_active`, `hdr_connector`, `hdr_max_nits`, `hdr_colorspace` |
| `cpu.` | `overall_pct`, `ccd0_c`, `ccd1_c` |
| `gpu.` | `busy_pct`, `mem_busy_pct`, `vram_pct`, `vram_used_mb`, `junction_c`, `gtt_rate_mbps`, `gtt_pool_pct`, `vendor`, `driver`, `stack` |
| `memory.` | `swap_pct`, `swap_out_kbps`, `psi_avg10`, `pgmajfault_per_s` |
| `stutter.` | `score`, `event`, `severity`, `session_events` |
| `stutter_detail.` | `est_ms`, `cause_text`, `hitch_ms_1pct`, `severity` |
| `load_phase.` | `phase`, `in_grace`, `sustained_fault_playing` |
| `signals.` | `page_fault_warn`, `gtt_spill_risk`, `load_phase_loading` |
| `thermal.` | `is_hot`, `is_warm`, `hot_c`, `throttling`, `arch_label` |
| `tools.` | `mangohud`, `gamemoded`, `cpu_rapl`, `cpu_rapl_present` |
| `diag.` | diagnostics scan (libs, vulkan, steam disk, …) — not live 1 Hz |
| `steam.` | install health for the **active** AppID |
| `audio.` | PipeWire default sink / rate when probing works |
| `mem_spec.` | DIMM SPD vs configured MT/s |

Missing path → `exists: false` / `not_exists: true`.

---

## Rules for rules

1. **High confidence only.** If you cannot name a metric that is true when the advice applies and false otherwise, it is not a rule — it is a blog post.
2. **Stable `insight_id`.** History, ignore, and mark-fixed key off it. Never recycle an id for a different meaning.
3. **Builtin packs do not name titles.** Steam AppID + Proton/Wine is enough. Per-game tips go in community packs (`games: ["730"]` or `games: active` plus a title check you own).
4. **Prefer `all:` of a few leaves** over one loose `eq`. “GPU busy” without `game.running` nags at the desktop.
5. **Templates in `title` / `text` must be guaranteed** by `detect` (or `exists`). Action templates that miss are dropped silently.
6. **`kind: note` for things that are not shell.** HDR OSD, in-game menus. `kind: cmd` must be pasteable as-is.
7. **Do not ask for sudo unless the command needs it.** Set `requires_root` only then.
8. **Keep packs small.** Five rules is a good pack. Fifty is an encyclopedia — split or drop.
9. **`match_when` on the pack** for distro/GPU/DE. Do not copy `platform.is_pop` onto every rule.
10. **Pulse does not run your command.** Say so in `note` if the step is destructive (sysctl, udev, launch options).
11. **First `insight_id` wins.** Higher `priority` evaluates first. Reuse a builtin id only when you intend to replace that card.
12. **Do not ship encyclopedias in `rules/builtin/`.** Audio walls, shopping lists, and per-title pro tips are community packs.

---

## Try a pack locally

```bash
# from a clone
export PULSE_RULE_PATH="$PWD/rules/examples"
python3 server.py
# Options → rule packs should list "Example — swappiness"
```

Or copy:

```bash
mkdir -p ~/.config/pulse/rules
cp -a rules/examples/hello-swappiness ~/.config/pulse/rules/
# restart Pulse
```

Tests that cover the engine: `python3 tests/test_rule_packs.py`.

To add a metric that does not exist yet, that is Python (`flatten_metrics` in
`rule_packs.py`) — a new YAML field cannot invent a sensor.
