# INV-STRUCTURAL-RESOLUTION-001 — Structural segments fully resolved at compilation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring all editorial decisions — asset selection, duration, and segment identity — are finalized during `compile_schedule()`. If structural segments remain unresolved when they leave the compiler, downstream stages must make editorial choices, violating the planning/execution boundary. `LAW-DERIVATION` requires that every scheduling artifact traces to a single authoritative compilation.

Supersedes `INV-TIER2-OBLIGATION-COMPILE-TIME-001` (which covered only Tier 2). This invariant generalizes the guarantee to all non-fill tiers.

## Guarantee

All non-fill segments (Tiers 0–3) MUST be fully resolved during `compile_schedule()`, including asset selection and final duration. The `compiled_segments` list on each `ProgramBlockOutput` MUST contain the complete, ordered set of structural segments with resolved `asset_id` and `duration_ms` values. No structural segment may have a placeholder asset reference or indeterminate duration.

## Preconditions

- `compile_schedule()` has access to the asset resolver and all pool definitions.
- Tier 2 and Tier 3 segments are injected in the second pass, after all blocks are compiled and compacted.

## Observability

A `ProgramBlockOutput` exits `compile_schedule()` with a `compiled_segments` entry that has an empty `asset_id`, a zero `duration_ms`, or a segment type requiring resolution that has not been resolved.

## Deterministic Testability

Compile a schedule with Tier 1 (presentation), Tier 2 (obligation), and Tier 3 (coming up next) configured. Inspect each `ProgramBlockOutput.compiled_segments` entry. Assert every entry has a non-empty `asset_id` and `duration_ms > 0`. Assert no entry has `segment_type` values requiring downstream resolution.

## Failure Semantics

**Planning fault.** An unresolved structural segment forces the expansion layer to make editorial decisions it does not own.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
