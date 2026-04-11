# INV-TIMELINE-APPEND-ONLY-001 — Append-only timeline

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-IMMUTABILITY` by ensuring that once a time range has been defined in the timeline, it is never modified or replaced. Modifying previously defined time ranges creates inconsistencies between planned, displayed, and actual playback.

## Guarantee

The timeline MUST be append-only with respect to time. Once a time range has been defined, it MUST NOT be modified or replaced by subsequent operations.

## Observability

Given an existing timeline covering [T₀, T₁), any subsequent scheduling operation MUST only define content for times ≥ T₁.

## Deterministic Testability

Compile a timeline covering [T₀, T₁). Trigger a subsequent compilation (horizon extension, restart, or operator action). Assert that no content within [T₀, T₁) has changed. Assert that new content exists only for times ≥ T₁.

## Failure Semantics

**Planning fault.** Rewriting past or present time ranges creates a split between what actually played (as-run) and what the system now claims was scheduled (EPG).

## Required Tests

- `server/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

- `TestTimelineAppendOnly::test_save_compiled_schedule_uses_conflict_resolution` — _save_compiled_schedule delegates to write_active_revision with ON CONFLICT DO NOTHING
- `TestTimelineAppendOnly::test_contiguity_enforcement_does_not_reorder_blocks` — block order preserved
- `TestTimelineAppendOnly::test_push_forward_does_not_modify_earlier_blocks` — original blocks not mutated
