# INV-STRUCTURAL-TIER-UNIFICATION-001 — All structural tiers follow the same compilation model

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring a uniform compilation model across all structural tiers. If any structural tier (T0–T3) is resolved at a different pipeline stage — e.g., asset selection deferred to expansion or duration computed at fill time — the compilation ceases to be the single source of editorial truth. Uniform treatment eliminates category-specific code paths in the expansion layer, reducing the surface area for derivation faults.

## Guarantee

All structural tiers (T0–T3) MUST follow the same compilation model:

1. Asset selection occurs during `compile_schedule()`.
2. Durations are known at compile time.
3. Segments are immutable during expansion.

No structural tier receives special treatment. The distinction between tiers governs ordering and editorial intent, not the compilation/expansion boundary.

## Preconditions

- `compile_schedule()` has access to the asset resolver, all pool definitions, and obligation configuration.
- The second pass (T2/T3 resolution) completes before grid sizing.

## Observability

A structural segment (T0–T3) is resolved at a different pipeline stage than the others — e.g., a Tier 3 asset selected during expansion, or a Tier 2 duration computed at fill time.

## Deterministic Testability

Compile a schedule with all four structural tiers configured. Inspect `compiled_segments` on every `ProgramBlockOutput`. Assert all entries (regardless of tier) have resolved `asset_id` and `duration_ms > 0`. Then expand. Assert the expanded `ScheduledBlock` contains identical structural segments — no tier was re-resolved, dropped, or modified.

## Failure Semantics

**Planning fault.** A structural tier resolved outside compilation means the expansion layer is making editorial decisions, violating `INV-EXPANSION-NON-MUTATION-001`.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
