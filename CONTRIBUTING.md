# Contributing / git workflow

Pulse uses standard local git practices. Remote (GitHub/GitLab) can be added later; the habits are the same.

## Principles

1. **Commit source, not runtime** — only tracked project files; DB, caches, and logs stay in `.gitignore`.
2. **One logical change per commit** — a feature, fix, or doc update; not a mixed bag of unrelated edits.
3. **Conventional Commits** — message format:

   ```
   <type>: <short summary>

   Optional body explaining why, not just what.
   ```

   Types: `feat`, `fix`, `docs`, `refactor`, `chore`, `style` (UI-only), `perf`.

4. **Changelog stays in sync** — user-visible work gets a bullet under `CHANGELOG.md` → `[Unreleased]` before or with the commit.
5. **Clean working tree** — finish a task with `git status` clean (or WIP on a branch, not half-applied on `main`).
6. **`main` is always runnable** — each commit should leave Pulse in a working state.

## Typical flow

```bash
cd pulse   # your clone directory

# edit files …
# update CHANGELOG.md [Unreleased] …

git add <files>
git commit -m "feat: describe the change"

# if UI or server changed:
systemctl --user restart pulse
```

## Branches

- **`main`** — default; day-to-day work is fine here while the repo is solo/local.
- **`feat/…` / `fix/…`** — use for larger or risky changes that span multiple sessions.

## What not to commit

- `pulse.db`, `pulse.db-wal`, `pulse.db-shm`
- `.tuning_log.json`, `.memory_cache.json`
- `__pycache__/`, `.ruff_cache/`
- Machine-specific paths in `~/.config/systemd/user/pulse.service` (use `deploy/pulse.service` template in repo)

## Publishing later

```bash
git config user.email "you@example.com"
git remote add origin <repo-url>
git push -u origin main
```