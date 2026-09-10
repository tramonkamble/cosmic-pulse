# Known issues

Open technical findings worth a look. Not a complete bug tracker — prefer GitHub Issues.

## Sampler / concurrency

- `games.py` lazy loaders (`_LazyDict`, legacy AppID maps) mutate globals without a lock. `ThreadingHTTPServer` can race on first request.
- Steam health / shader size caches TTL but do not evict expired keys.
- `guidance_auto.tick_auto_resolve` can call `fresh_active_ids()` once per expiring insight (diagnostic scan) instead of once per tick.

## Rules

- `rule_packs._get_path` only walks dicts, so templates like `{gpu.0.temp}` cannot index lists.
- Unresolved-template regex `\{[^}]+\}` also matches bracey shell/JSON strings.

## Tests

- `tests/test_steam_health.py` covers log parse, not `steam_update_needs_attention` thresholds.
- Harness (`tests/harness.py`) is the product smoke; many UI paths are visual-only.

## Product (intentional, v0.1)

- Hitch score is a kernel-signal **proxy**, not frametime.
- `--lan` has no authentication.
- Builtin Guidance is ten scaffold rules. Game-specific coaching is community packs.
