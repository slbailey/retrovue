# INV-EPG-PLAYOUT-ANCHOR-MATCH-001

**Domain:** scheduling  
**Status:** proposed  
**Added:** 2026-04-09 (Phase 2 — RETA-91)

## Statement

The active `ScheduleRevision.broadcast_day` for a given channel MUST match
the broadcast day anchor of the in-memory compiled schedule that produced
the `ScheduledBlock` objects consumed by playout.

## Rationale

EPG and playout both originate from the same DSL compilation but diverge
at the persistence boundary:

- **EPG** reads from `ScheduleRevision` / `ScheduleItem` rows in the database
  (via `get_canonical_epg()` and `ChannelActiveRevision` pointers).
- **Playout** reads from in-memory `ScheduledBlock` objects held by
  `DslScheduleService._blocks`.

This asymmetry is acceptable because the write path in `_compile_day()`
ensures both representations are produced from the same compilation in the
same call:

1. `compile_schedule()` produces the program schedule dict
2. `_expand_schedule_to_blocks()` produces the in-memory `ScheduledBlock` list
3. `_save_compiled_schedule()` writes `ScheduleRevision` + `ScheduleItem` to DB

As long as the write succeeds, both paths reflect the same compilation output.
If the write is refused (INV-TIMELINE-APPEND-ONLY-001), the in-memory blocks
are discarded — preventing divergence.

## Enforcement

This invariant is enforced structurally by the `_compile_day()` flow:
- If DB write fails, in-memory blocks are discarded (line ~2067-2074)
- `INV-TIMELINE-SINGLE-AUTHORITY-001` prevents in-memory forks

No runtime reconciliation mechanism is needed at this time.

## Violation Symptoms

If violated (e.g., by a code change that allows in-memory blocks to persist
after a failed DB write), EPG would show one schedule while playout executes
another — a silent correctness failure.
