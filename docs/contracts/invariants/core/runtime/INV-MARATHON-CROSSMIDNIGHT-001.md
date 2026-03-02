# INV-MARATHON-CROSSMIDNIGHT-001

## Behavioral Guarantee

A movie marathon block whose `start` hour is >= `BROADCAST_DAY_START_HOUR` and whose `end` hour is <= `BROADCAST_DAY_START_HOUR` MUST resolve `end` to the next calendar day. The marathon MUST produce at least one program block.

## Authority Model

`_compile_movie_marathon` in `schedule_compiler.py` owns time resolution for marathon boundaries. Cross-midnight detection occurs after `_parse_time` returns, by comparing `end_time <= start_time`.

## Boundary / Constraint

- When a marathon's `end` time string resolves to a datetime earlier than or equal to its `start` datetime, the compiler MUST advance `end` by one calendar day.
- A marathon with `start < end` (after resolution) and a non-empty asset pool MUST produce at least one program block.
- This applies to any DSL block type that uses `start`/`end` time strings spanning the broadcast-day boundary.

## Violation

A marathon block that produces zero program blocks despite having a valid time range and available assets. Observable as a gap in the compiled schedule at the marathon's time window.

## Derives From

`LAW-GRID`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_marathon_crossmidnight.py`

## Enforcement Evidence

`_compile_movie_marathon` in `schedule_compiler.py` checks `end_time <= current_time` after parsing both times and advances `end_time` by 24 hours. This mirrors the existing pattern in `_compile_episode_block` (lines 688–690).
