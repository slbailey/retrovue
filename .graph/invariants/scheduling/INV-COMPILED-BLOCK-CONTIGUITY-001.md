# INV-COMPILED-BLOCK-CONTIGUITY-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 2 — RETA-91)

## Statement

After `_expand_schedule_to_blocks()` in the production compile path, adjacent
`ScheduledBlock` objects MUST have no temporal gaps: each block's `end_utc_ms`
must equal the next block's `start_utc_ms`.

## Enforcement

- **Compile time:** `validate_compiled_block_contiguity()` in
  `scheduling/compile_time_validation.py`, called from
  `DslScheduleService._compile_day()` after block expansion.
- **Contract tests:** `test_compile_time_validation.py::TestCompiledBlockContiguity`

## Production-path equivalent of

`validate_scheduleday_contiguity()` (derivation-chain validator, test-only).
See ADR-015.
