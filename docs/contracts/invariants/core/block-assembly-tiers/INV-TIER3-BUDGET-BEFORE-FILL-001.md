# INV-TIER3-BUDGET-BEFORE-FILL-001 — Tier 3 duration deducted before traffic fill

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-GRID` by ensuring optional presentation time is accounted for in the break budget derivation before traffic fill runs. If Tier 3 duration were not deducted, Tier 4 traffic fill would over-fill breaks, causing the block to exceed its grid slot duration. `LAW-CONTENT-AUTHORITY` requires that structural content (Tiers 0–3) takes priority over fill.

## Guarantee

Tier 3 optional presentation duration MUST be deducted from the break budget BEFORE Tier 4 traffic fill runs. The break budget formula is: `break_budget = scheduled_duration - content_duration - tier1_duration - tier2_duration - tier3_duration`. If adding Tier 3 elements causes the structural total to exceed the grid slot, the grid grows per `INV-GRID-SIZING-STRUCTURAL-001`; Tier 3 elements are NEVER dropped to preserve break budget.

## Preconditions

- Tier 3 segments are resolved and included in `compiled_segments`.
- Grid sizing has occurred after all structural tiers are resolved.

## Observability

Break budget calculation does not account for Tier 3 duration, resulting in `sum(all_segment_durations) > scheduled_block_duration`. Tier 3 elements are dropped to fit within break budget.

## Deterministic Testability

Compile a block with Tier 1 presentation (10s), Tier 3 channel ident (5s), and content (1200s) in a 1260s grid slot. Assert `break_budget == 1260000 - 1200000 - 10000 - 5000 == 45000ms`. Assert Tier 3 segments remain present; they are not dropped.

## Failure Semantics

**Planning fault.** Over-filled breaks violate `INV-BLOCK-SEGMENT-CONSERVATION-001`. Dropped Tier 3 elements violate `INV-TIER-DISPLACEMENT-001`.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
