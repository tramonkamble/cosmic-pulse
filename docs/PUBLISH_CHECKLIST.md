# Publish checklist

Goal: **review-ready repo this week**, public GitHub/GitLab after brother's feedback.

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
- [ ] **Brother code review** — feedback captured (issues or doc)
- [ ] Address blocker / should-fix items from review

## Before public publish

- [x] Create GitHub repo — https://github.com/tramonkamble/cosmic-pulse
- [ ] Set git `user.email` to real address for attribution
- [x] `git remote add origin` && `git push -u origin main`
- [x] README: clone URL points at GitHub
- [ ] Optional: second screenshot (Fixes tab, league drill-down)
- [ ] Optional: `127.0.0.1` bind default + `--lan` flag (if review suggests)
- [ ] Optional: GitHub Issues templates

## After publish (System76 / community)

- [ ] Short demo video (60–90 s)
- [ ] Post to r/pop_os or r/System76 for feedback
- [ ] Pitch as Cosmic System Monitor **companion** (not replacement)

## Not blocking v0.1

- libcosmic / Rust rewrite
- MangoHud log ingestion
- NVIDIA GPU support
- True frametime hooks