# hello-swappiness — annotated example pack

Not loaded from `rules/builtin/`. Copy to `~/.config/pulse/rules/` or set
`PULSE_RULE_PATH` (see [docs/RULES.md](../../../docs/RULES.md)).

This pack has **one rule**. It is the commented twin of builtin
`vm-swappiness-high` (`rules/builtin/pulse-core/rules.yaml`). It uses a different
`insight_id` (`example-swappiness-high`) so you can load it next to the builtin
without replacing that card.

| File | Role |
|------|------|
| `pack.yaml` | Pack id, name, priority, which rule files to load |
| `rules.yaml` | The rule — comments on `id`, `detect`, `emit`, `actions` |

**What to copy:** the folder shape and the comments. Then change `id` /
`insight_id`, the metric, and the copy.

**Next read:** builtin `cpu-governor-powersave` (one leaf), then `stutter-proxy`
(`all` / `any` / nested `level_when`).
