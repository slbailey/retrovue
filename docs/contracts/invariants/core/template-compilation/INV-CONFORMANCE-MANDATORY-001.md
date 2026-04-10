# INV-CONFORMANCE-MANDATORY-001 — Compiled plan must match scheduled duration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-GRID` by making segment conservation explicit at the compilation entry point. Strengthens `INV-BLOCK-SEGMENT-CONSERVATION-001` by requiring conformance verification at template compilation output, before downstream stages.

## Guarantee

The compiled playout plan MUST exactly match the scheduled block duration, within frame tolerance (40ms per `INV-BLOCK-SEGMENT-CONSERVATION-001`):

```
sum(all_segment_durations) == scheduled_block_duration ± 40ms
```

Conformance is verified at every pipeline stage.

## Preconditions

All structural segments (Tiers 0–3) and fill segments (Tier 4) are resolved.

## Observability

The compiler logs `sum(segments)` and `scheduled_duration` at conformance check. Any drift > 40ms is logged as an error and the block is rejected.

## Deterministic Testability

Construct a compiled block. Verify `sum(all_segment_durations)` equals `scheduled_block_duration` within 40ms. Inject a segment that causes > 40ms drift and verify the block is rejected.

## Failure Semantics

**Planning fault.** Duration drift causes timeline gaps or overlaps, violating `LAW-GRID` and `LAW-CONTENT-AUTHORITY`.

## Required Tests

- `pkg/core/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
