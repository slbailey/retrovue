# INV-SCHEDULE-SEED-DAY-VARIANCE-001 — Day-varying compilation seed

## Status: ACTIVE

## Rule

1. The compilation seed passed to `compile_schedule()` MUST incorporate both
   `channel_id` and `broadcast_day`. Same `(channel_id, broadcast_day)` pair
   MUST always produce the same seed. Different `broadcast_day` values MUST
   produce different seeds.

2. Within a single compilation, each per-window block compiler (template entry,
   movie marathon, movie block, episode block) MUST derive a window-specific
   seed by mixing the window's start time into the compilation seed. Two windows
   at different start times on the same day MUST receive different seeds.

3. `channel_seed()` is unchanged. It remains the channel-identity seed used for
   non-date-dependent purposes. `compilation_seed(channel_id, broadcast_day)` is
   the day-varying seed for schedule compilation.

4. All seed derivation MUST use `hashlib.sha256` (deterministic, stable across
   process lifetimes). No `hash()`, no `random.random()`, no wall-clock input.

## Rationale

Without date incorporation, `Random(seed).choice(sorted_candidates)` produces
identical movie selections every day for the same channel — viewers see the same
schedule repeating. Incorporating `broadcast_day` ensures variety while preserving
deterministic rebuild: recompiling the same day produces the same output.

## Verification

- `compilation_seed("ch", "2026-03-01") != compilation_seed("ch", "2026-03-02")`
- `compilation_seed("ch", "2026-03-01") == compilation_seed("ch", "2026-03-01")`
- Two template windows compiled with different start times produce different
  movie selections on the same day.

## See Also

- `INV-SCHEDULE-SEED-DETERMINISTIC-001` — channel_seed() stability (unchanged)
- `pkg/core/src/retrovue/runtime/schedule_compiler.py` — `compilation_seed()`, `_window_seed()`
