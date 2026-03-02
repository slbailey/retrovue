# INV-SCHEDULE-SEQUENTIAL-ADVANCE-001

## Behavioral Guarantee

For channels using `mode: sequential`, consecutive broadcast days MUST advance the sequential counter so that episodes progress through the pool across days rather than repeating from the start.

## Authority Model

`DslScheduleService._compile_day()` owns sequential counter initialization. The counter starting position is derived from the broadcast day offset and the estimated slots per day.

## Boundary / Constraint

1. `_count_slots_in_dsl()` MUST return a value greater than zero for any DSL that produces program blocks. Block-style schedules (with `block:` containing `start`/`duration`/`end`/`pool`) and movie_marathon blocks MUST be counted by computing total scheduled minutes divided by grid slot size.
2. Compiling two consecutive broadcast days with the same DSL and pool MUST produce different first episodes when the pool contains more episodes than one day's worth of slots.

## Violation

`_count_slots_in_dsl()` returns 0 for block-style DSL (no `slots:` key), causing `starting_counter = day_offset * 0 = 0` for every broadcast day. All days compile identical episode sequences from the pool start.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_schedule_sequential_advance.py`

## Enforcement Evidence

TODO
