# INV-TIER3-COMPILE-RESOLUTION-001 — Tier 3 segments resolved at compilation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring Tier 3 optional presentation segments — channel idents, network branding, "coming up next" promos — are fully resolved during `compile_schedule()`. If Tier 3 inclusion or asset identity were deferred to expansion or traffic fill, those downstream stages would make editorial decisions they do not own, violating the planning/execution boundary. `LAW-DERIVATION` requires that Tier 3 segments trace to a single authoritative compilation pass.

## Guarantee

Tier 3 segments, when enabled by a template's `continuity.optional` configuration, MUST be resolved during `compile_schedule()`, including asset selection and duration, using deterministic selection rules. Tier 3 inclusion is decided BEFORE grid sizing — Tier 3 duration is part of the structural total that drives grid block allocation. Once included in `compiled_segments`, Tier 3 segments MUST be treated as structural and MUST NOT be added, removed, or modified during expansion.

## Preconditions

- The block references a template with `continuity.optional` entries.
- The referenced asset pools exist and contain at least one eligible asset.
- All blocks in the broadcast day are compiled and compacted (Tier 3 resolution occurs in the second pass).

## Observability

A `ProgramBlockOutput` exits `compile_schedule()` with a Tier 3 segment that has an empty `asset_id`, a zero `duration_ms`, or a segment type that has not been resolved. Alternatively, a Tier 3 segment is added, removed, or modified after `compile_schedule()` completes.

## Deterministic Testability

Compile a schedule with a template declaring `continuity.optional` entries. Inspect each `ProgramBlockOutput.compiled_segments` for Tier 3 entries. Assert each has a non-empty `asset_id` and `duration_ms > 0`. Expand the block and assert Tier 3 segments in the expanded `ScheduledBlock` match their `compiled_segments` source exactly.

## Failure Semantics

**Planning fault.** An unresolved Tier 3 segment forces the expansion layer to make editorial decisions it does not own.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
