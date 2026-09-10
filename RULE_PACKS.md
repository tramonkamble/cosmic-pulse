# Rule packs

Pulse Guidance is YAML. Builtin packs stay small; community packs do the rest.

| Read | What |
|------|------|
| **[docs/RULES.md](docs/RULES.md)** | How to write a pack: schema, metric catalog, **rules for rules** |
| [rules/examples/hello-swappiness/](rules/examples/hello-swappiness/) | One rule, comments on every field (not loaded automatically) |
| [rules/builtin/pulse-core/rules.yaml](rules/builtin/pulse-core/rules.yaml) | Production examples (`cpu-governor-powersave`, then `stutter-proxy`) |

Drop a folder in `~/.config/pulse/rules/<id>/` (`pack.yaml` + `rules.yaml`) and restart Pulse.

## Builtin (0.1)

| Pack | When | Rules |
|------|------|--------|
| **pulse-core** | Always | governor, swappiness, stutter-proxy, gpu-fps-cap, proton-wayland |
| **popos-core** | `platform.is_pop` | HDR off, RAPL udev, Proton libs, MangoHud, GPU hot |

Disable in Options or `disabled_packs` in config. Builtin packs do not name game titles.

## Not builtin

Audio walls, tools shopping lists, CS2 encyclopedias, deep Steam health, per-title pro tips.
