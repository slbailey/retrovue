# INV-COMPILED-GRID-ALIGNMENT-001

**Domain:** scheduling  
**Status:** accepted  
**Added:** 2026-04-09 (Phase 2 — RETA-91)

## Statement

After `_expand_schedule_to_blocks()` in the production compile path,
every `ScheduledBlock.start_utc_ms` MUST be grid-aligned: the offset
from the first block's start must be a multiple of the grid block
duration in milliseconds.

## Enforcement

- **Compile time:** `validate_compiled_grid_alignment()` in
  `scheduling/compile_time_validation.py`, called from
  `DslScheduleService._compile_day()` after block expansion.
- **Contract tests:** `test_compile_time_validation.py::TestCompiledGridAlignment`

## Production-path equivalent of

`validate_transmission_log_grid_alignment()` (derivation-chain validator, test-only).
See ADR-015.
