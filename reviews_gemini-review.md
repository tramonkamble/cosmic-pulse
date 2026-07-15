# Code Review: Perf Dashboard (Gemini)

## Critical
**1. Repeated Expensive Callbacks in Auto-Resolution Loop**
* **File Path:** `guidance_auto.py`
* **Finding:** In `tick_auto_resolve`, the `fresh_active_ids()` callback is evaluated inside the `history` loop for every diagnostic-backed insight that reaches its clear timer. If multiple insights expire simultaneously, this triggers multiple expensive diagnostic scans (`tuning_hints(base)`) in a single tick.
* **Suggested Fix:** Cache the result of `fresh_active_ids()` lazily before or inside the loop so it is executed at most once per tick.

**2. Thread-Safety in Global Caches**
* **File Path:** `games.py`
* **Finding:** Global lazy-loading mechanisms (like `_load_legacy_game_ids` and the `_LazyDict` implementation) mutate global state without a thread lock. Since the server runs as a `ThreadingHTTPServer`, concurrent initial requests could trigger race conditions, double-imports, or malformed cache states.
* **Suggested Fix:** Add a `threading.Lock()` to `_LazyDict._data()` or around the global cache assignment in the loader functions.

## Medium
**1. Template Resolution Limits Array Access**
* **File Path:** `rule_packs.py`
* **Finding:** The `_get_path` function explicitly checks `isinstance(cur, dict)` to navigate nested paths. This breaks template variables that need to reference list items (e.g., `{gpu.0.temp}`).
* **Suggested Fix:** Allow list traversal in `_get_path` by checking if the next path segment is a digit (or catching `IndexError` after casting).

**2. Unbounded Memory Growth in Steam Health Caches**
* **File Path:** `games.py`
* **Finding:** `_STEAM_HEALTH_CACHE` and `_SHADER_SIZE_CACHE` store data with TTLs but never actively evict old keys. Memory usage will grow indefinitely over a long uptime if many different AppIDs are queried.
* **Suggested Fix:** Implement a periodic sweep to delete expired keys, or replace the raw dict with a bounded LRU cache mechanism.

## Low
**1. Overzealous Unresolved Template Regex**
* **File Path:** `rule_packs.py`
* **Finding:** `_UNRESOLVED_TEMPLATE_RE` uses `r"\{[^}]+\}"`, which will falsely match standard strings containing braces (like stringified JSON or bash variables) and flag them as unresolved templates.
* **Suggested Fix:** Tighten the regex to strictly match the expected template path format, e.g., `r"\{[a-zA-Z0-9_.:]+\}"`.

**2. Potential ValueError in Timer Seeding**
* **File Path:** `guidance_auto.py`
* **Finding:** In `seed_clear_timers`, `float(item.get("last_seen") or now)` is used. If `last_seen` exists in the history JSON but is an empty string `""` or invalid format, `float()` will crash.
* **Suggested Fix:** Wrap the conversion in a `try...except (ValueError, TypeError)` block and fallback to `now`.

## Test Gaps
**1. Steam Integration Thresholds and States**
* **File Path:** `tests/test_steam_health.py`
* **Finding:** The existing tests only validate log parsing (`content_log_health`). They do not cover `steam_update_needs_attention`, leaving its core logic (e.g., the 5 MB vs 20 MB size thresholds based on the `running` state) untested.
* **Suggested Fix:** Add parameterized tests specifically for `steam_update_needs_attention` validating the boolean return across different byte thresholds and `running` flags.

**2. Nested Template Resolution**
* **File Path:** `tests/test_rule_packs.py`
* **Finding:** High likelihood of missing test coverage for `render_template` edge cases, such as formatting fallbacks, invalid deeply nested paths, and literal curly braces.
* **Suggested Fix:** Ensure test suites invoke `render_template` with complex nested dictionaries, missing keys, and raw braces to ensure robust rendering without false unresolutions.
