# ADR-015: Derivation Chain vs Production Compile Path

**Status:** Accepted  
**Date:** 2026-04-09  
**Context:** Phase 2 scheduling pipeline verification (RETA-91)

## Decision

The formal derivation chain (`derive_transmission_log` → `derive_execution_entries`)
remains **test-only**. The production path (DSL → compiler → ScheduleRevision →
PlaylistEvent → ScheduledBlock) is equivalent but distinct.

Compile-time validators are wired into the **production path** to enforce the same
scheduling invariants, using production types (`ScheduledBlock` list) rather than
derivation-chain types (`ResolvedScheduleDay`, `TransmissionLogEntry`).

## Context

The scheduling system has two parallel paths:

1. **Derivation chain** (test/contract path):
   - `SchedulePlan` → `ResolvedScheduleDay` → `TransmissionLog` → `ExecutionEntry`
   - Pure functions, no DB, no side effects
   - 8 validators defined for this chain
   - Only `validate_execution_entry_contiguity()` was wired in production (in `ExecutionWindowStore`)

2. **Production compile path**:
   - DSL YAML → `compile_schedule()` → `_expand_schedule_to_blocks()` → `ScheduledBlock` list
   - `_save_compiled_schedule()` → `ScheduleRevision` + `ScheduleItem` rows in DB
   - `PlaylistBuilderDaemon` → `PlaylistEvent` rows → `ScheduledBlock` consumption

These paths enforce the same intent (gap-free, grid-aligned broadcast days) but operate
on different type hierarchies. Forcing production code to construct derivation-chain types
would add coupling without safety benefit.

## Validators Wired at Compile Time

In `DslScheduleService._compile_day()`, after `_expand_schedule_to_blocks()`:

| Validator | Invariant | Production equivalent of |
|-----------|-----------|-------------------------|
| `validate_compiled_block_contiguity()` | INV-COMPILED-BLOCK-CONTIGUITY-001 | `validate_scheduleday_contiguity()` |
| `validate_compiled_grid_alignment()` | INV-COMPILED-GRID-ALIGNMENT-001 | `validate_transmission_log_grid_alignment()` |

These fail-fast at compile time, before bad data enters the playlog.

## What Remains Test-Only

The following validators continue to run only in contract tests:

- `validate_scheduleday_contiguity()` — validates `ResolvedScheduleDay`
- `validate_transmission_log_grid_alignment()` — validates `TransmissionLogEntry`
- `validate_no_mid_program_cut()` — validates `ProgramPlacement`
- `validate_asrun_traceability()` — validates as-run chain
- `validate_scheduleday_assets()` / `validate_transmission_log_assets()` / `validate_execution_entry_assets()` — foreign content validators

These remain valuable as contract tests proving the derivation chain's correctness,
but the production path uses its own equivalent checks.

## Consequences

- Compile-time validation catches contiguity gaps and grid misalignment before DB write
- No additional runtime cost on the playout hot path
- Derivation chain tests continue to validate the mathematical model independently
- New invariants added to production path: INV-COMPILED-BLOCK-CONTIGUITY-001, INV-COMPILED-GRID-ALIGNMENT-001
