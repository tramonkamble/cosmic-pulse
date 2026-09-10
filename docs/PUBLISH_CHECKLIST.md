# Publish checklist

Goal: **public GitHub** so people and other coding agents can hunt bugs and send PRs.

## Ship blockers (0.1)

- [x] **Builtin rules cleanup** — two packs of five: `pulse-core` + `popos-core`. Community owns richer packs.
- [x] **First public push** — maintainer asked to publish for community + AI review (UI still iterating).

## This week — review prep

- [x] `README.md` with screenshot and quick start
- [x] `LICENSE` (GPL-3.0-only, System76 / Pop!_OS app preference)
- [x] `requirements.txt`
- [x] `docs/REVIEW.md` for code reviewers
- [x] `docs/screenshots/dashboard.png`
- [x] Remove hardcoded `/home/tkep` paths
- [x] `.gitignore` for runtime artifacts (incl. `.pulse_config.json`, `backups/`)
- [x] `CONTRIBUTING.md` + `CHANGELOG.md`
- [x] `docs/ARCHITECTURE.md` — data flow, Guidance contracts, config
- [x] `.pulse_config.example.json` — template for local settings
- [x] Inline comments on Guidance render path (`index.html`) and `update_tuning_history`
- [x] `install.sh` + `docs/INSTALL.md` + `deploy/build-deb.sh` (.deb)
- [x] Agent map — `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`
- [x] Issue templates (bug + AI review)
- [x] Current dashboard screenshot
- [ ] `gh auth login` and `git push -u origin main` (needs GitHub credentials on this machine)
- [ ] Confirm the GitHub repo is **public**

## Before public publish

- [x] Create GitHub repo — https://github.com/tramonkamble/cosmic-pulse
- [ ] Set git `user.email` to a real or GitHub-noreply address
- [ ] `git push -u origin main` from a logged-in `gh` / SSH key
- [x] README: clone URL points at GitHub
- [x] Snapshot vitals screenshot
- [x] `127.0.0.1` bind default + `--lan` flag
- [x] GitHub Issues templates

## After publish (System76 / community)

- [ ] Short demo video (60–90 s)
- [ ] Post to r/pop_os or r/System76 for feedback
- [ ] Pitch as Cosmic System Monitor **companion** (not replacement)

## Not blocking v0.1

- libcosmic / Rust rewrite
- MangoHud log ingestion
- NVIDIA GPU support
- True frametime hooks