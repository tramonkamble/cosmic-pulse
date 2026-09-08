# Builtin rule packs (0.1)

Cosmic Pulse ships **two** builtin packs. That is the whole default Guidance set — ten insights, not a coach encyclopedia.

| Pack | When it runs | Role |
|------|----------------|------|
| **pulse-core** | Always | Linux kernel, Steam/Proton, live gaming |
| **popos-core** | `platform.is_pop` | Pop!_OS / COSMIC / apt / System76-class AMD |

Disable a pack in Options or `disabled_packs` in `~/.config/pulse/pulse_config.json`. Extra packs go in `~/.config/pulse/rules/<id>/pack.yaml`.

## pulse-core (5)

1. **cpu-governor-powersave** — governor stuck on `powersave`
2. **vm-swappiness-high** — `vm.swappiness` too aggressive for gaming
3. **stutter-proxy** — Pulse hitch score / events while a game runs (instrumented)
4. **gpu-fps-cap** — GPU busy vs display refresh while a game runs (instrumented)
5. **proton-wayland-launch-fix** — Proton on Wayland without an X11 launch override

CS2 / Cities II `game_overrides` live on this pack for process detection only — they are not extra cards.

## popos-core (5)

1. **display-hdr-off** — HDR-capable display in SDR; COSMIC has no desktop HDR toggle (instrumented EDID/DRM)
2. **cpu-rapl-unreadable** — RAPL `energy_uj` is root-only; zenpower is not in Pop repos
3. **game-libs-missing** — 32-bit Proton libs via `apt` / i386
4. **mangohud-recommended** — optional overlay; Pulse can attach FPS to sessions
5. **gpu-thermal-ceiling** — junction at the Pulse thermal-profile hot band

## Not builtin

Audio walls, tools shopping lists, CS2 encyclopedias, deep Steam health, per-title pro tips. Those belong in community packs after 0.1.
