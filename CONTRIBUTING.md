# Contributing

Clone: https://github.com/tramonkamble/cosmic-pulse

Coding agents should read [AGENTS.md](AGENTS.md) first (Claude: [CLAUDE.md](CLAUDE.md); Gemini: [GEMINI.md](GEMINI.md)).

## Principles

1. **Commit source, not runtime** — DB, caches, and logs stay in `.gitignore`.
2. **One logical change per commit.**
3. **Conventional Commits:** `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `style:`, `perf:`.
4. User-visible work gets a bullet under `CHANGELOG.md` → `[Unreleased]`.
5. **`main` stays runnable.**

## Lint & tests

```bash
cd cosmic-pulse
ruff check . --fix
ruff format .
python3 tests/harness.py          # product smoke (no pytest)
python3 tests/test_stutter.py     # or: pytest tests/ if installed
```

Ruff config is in `pyproject.toml`.

## Typical flow

```bash
# edit …
# ruff + harness …
# CHANGELOG.md [Unreleased] if users will notice

git add <files>
git commit -m "fix: describe the change"
```

Restart after Python edits: `systemctl --user restart cosmic-pulse` or re-run `python3 server.py`. Hard-refresh the browser after `index.html` / `assets/dashboard.css` / `assets/dashboard.js` changes. If you touched Live lab, check Snapshot, Pulse Index, and Stutter.

## Branches

- **`main`** — default shipping UI + server.
- **`feat/…` / `fix/…`** — larger or risky work.

## What not to commit

- `pulse.db`, `pulse.db-wal`, `pulse.db-shm`
- `.pulse_config.json`, `.tuning_log.json`, `.memory_cache.json`
- `backups/`, `__pycache__/`, `.ruff_cache/`
- Machine-specific systemd drop-ins (use `deploy/cosmic-pulse.service`)

Ship `.pulse_config.example.json` instead of a real config. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Guidance rule packs

YAML, not Python. Authoring guide: [docs/RULES.md](docs/RULES.md). Index: [RULE_PACKS.md](RULE_PACKS.md).

- Production examples: `rules/builtin/pulse-core/rules.yaml` (`cpu-governor-powersave`, then `stutter-proxy`).
- Annotated starter: `rules/examples/hello-swappiness/` — copy into `~/.config/pulse/rules/`; do not add example packs to `rules/builtin/`.
- New sensors need Python (`flatten_metrics` in `cosmic_pulse/rule_packs.py`). A YAML field cannot invent a metric.
- Keep builtin packs small (five rules each in 0.1). Per-title tips are community packs.

```bash
python3 tests/test_rule_packs.py
```

## AI reviews

Paste findings into a GitHub issue with the **AI review finding** template (`file:line`, severity, suggested fix). Do not open a PR that rewrites `index.html` unless the issue asks for that.
