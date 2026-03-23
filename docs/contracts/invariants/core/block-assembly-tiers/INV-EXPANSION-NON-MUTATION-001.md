# INV-EXPANSION-NON-MUTATION-001 — Expansion must not modify structural segments

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the expansion stage (`_expand_blocks_inner`) does not alter structural segments produced by `compile_schedule()`. If expansion re-resolves assets, changes durations, reorders, or drops structural segments, the compilation is no longer the single source of editorial truth. `LAW-DERIVATION` requires that the playlog plan traces faithfully to the compiled schedule.

Complements `INV-TIER2-EXPANSION-CANONICAL-001` (which governs the canonical expansion call path) by constraining what expansion may do to the segments it receives.

## Guarantee

Expansion MUST NOT modify, re-resolve, reorder, or remove structural segments (Tiers 0–3) produced by `compile_schedule()`. Expansion MUST treat `compiled_segments` entries as read-only editorial truth. Expansion MAY:

1. Hydrate `asset_id` to `asset_uri` (file path resolution).
2. Insert fill segments (Tier 4) — empty filler placeholders via `expand_program_block()`.
3. Sequence structural segments into their tier-ordered positions within the `ScheduledBlock`.

Expansion MUST NOT:

1. Change the `segment_type`, `asset_id`, or `duration_ms` of any structural segment.
2. Drop a structural segment.
3. Insert structural segments not present in `compiled_segments`.
4. Reorder structural segments relative to each other.

## Preconditions

- `compile_schedule()` has fully resolved all structural segments per `INV-STRUCTURAL-RESOLUTION-001`.
- `compiled_segments` is present on the block def dict passed to expansion.

## Observability

After expansion, the `ScheduledBlock` contains a structural segment whose `segment_type`, `asset_id`, or `segment_duration_ms` does not match the corresponding entry in the source `compiled_segments`. Or a structural segment present in `compiled_segments` is absent from the expanded block.

## Deterministic Testability

Compile a block with known `compiled_segments` (Tier 1 presentation + Tier 2 obligation + Tier 3 optional). Expand. Assert every structural segment in the expanded `ScheduledBlock` matches its source `compiled_segments` entry in type, asset identity, and duration. Assert no structural segments were added beyond those in `compiled_segments`.

## Failure Semantics

**Planning fault.** A mutated structural segment means the expanded block no longer reflects the compiled schedule. The playlog plan diverges from editorial intent.

## Required Tests

- `pkg/core/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
