# INV-GRID-SIZING-STRUCTURAL-001 — Grid allocation based on total structural runtime

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-GRID` by ensuring grid block allocation accounts for the total runtime of all structural segments (Tiers 0–3), not just primary content. If grid sizing considers only episode duration, blocks with substantial presentation, obligation, or optional segments may overflow their grid allocation, violating block boundary alignment.

Generalizes the budget deduction principle of `INV-PRESENTATION-GRID-BUDGET-001` (which covers Tier 1 only) to all structural tiers. `INV-PRESENTATION-GRID-BUDGET-001` remains authoritative for Tier 1 budget deduction within content selection; this invariant governs the grid block count decision.

## Guarantee

Grid block allocation for a program block MUST be based on the total runtime of all structural segments (Tiers 0–3). The grid slot duration MUST satisfy: `slot_duration_ms >= sum(segment.duration_ms for segment in compiled_segments)`. When dynamic grid sizing (`grid_blocks_max`) is used, the block count calculation MUST use the total structural runtime, not episode duration alone.

## Preconditions

- Tiers 0–1 are resolved during the first compilation pass.
- Tiers 2–3 are resolved during the second pass, after compaction.
- Grid block count is finalized after both passes complete.

## Observability

A `ProgramBlockOutput` has `slot_duration_sec * 1000 < sum(cs["duration_ms"] for cs in compiled_segments)`. The structural segments do not fit within the allocated grid slot.

## Deterministic Testability

Compile a block with: 85-minute movie (Tier 0), 10-second rating card (Tier 1), 5-second station ID obligation (Tier 2), 15-second "coming up next" (Tier 3). Total structural runtime: 85:30. Assert grid allocation is `ceil(5130 / 1800) = 3 blocks = 90 minutes`. Remove Tiers 1–3 and recompile. Assert grid allocation is `ceil(5100 / 1800) = 3 blocks`. Test boundary case where Tier 1–3 durations push total across a grid boundary.

## Failure Semantics

**Planning fault.** Grid underallocation causes `INV-BLOCK-SEGMENT-CONSERVATION-001` violations downstream when segments exceed the block envelope.

## Required Tests

- `pkg/core/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
