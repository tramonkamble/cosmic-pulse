# Example rule packs

These folders are **not** builtin. Copy one into `~/.config/pulse/rules/` or point
`PULSE_RULE_PATH` at this directory. Schema and style: [docs/RULES.md](../../docs/RULES.md).

| Pack | What it shows |
|------|----------------|
| `hello-swappiness/` | One rule, comments on every field. Safe to load; it only fires if swappiness is actually high. |

Shipped production rules (load automatically):

- [../builtin/pulse-core/](../builtin/pulse-core/) — start with `cpu-governor-powersave`
- [../builtin/popos-core/](../builtin/popos-core/) — `match_when: platform.is_pop`
