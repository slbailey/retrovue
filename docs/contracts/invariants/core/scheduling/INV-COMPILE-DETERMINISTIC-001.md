# INV-COMPILE-DETERMINISTIC-001 — Compilation determinism

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-IMMUTABILITY` by ensuring that schedule compilation is a pure function of its inputs. Given the same compilation snapshot (DSL, catalog, ProgressionRun, parameters, prior-day boundary), the output MUST be identical. Non-deterministic compilation would mean restarts or recompilations silently alter the schedule.

## Guarantee

Schedule compilation under an unchanged compilation snapshot (DSL, catalog, ProgressionRun, parameters, prior-day boundary) MUST produce identical output. Determinism is relative to the snapshot; catalog mutation breaks equivalence.

## Observability

Compile the same snapshot twice and diff the outputs. Any difference is a determinism violation.

## Deterministic Testability

Record the output of a compilation run. Reset state. Compile the same snapshot again. Every field of every block, segment, and timing boundary MUST be identical between the two runs.

## Failure Semantics

**Planning fault.** Non-deterministic compilation means the schedule changes on restart without operator intent, silently replacing what was previously scheduled.

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

- `TestTimelineRestartIdentical::test_enforce_contiguity_is_deterministic` — contiguity enforcement is idempotent (stable across restarts)
- `TestTimelineRestartIdentical::test_push_forward_is_deterministic` — push-forward is idempotent
- `TestTimelineRestartIdentical::test_contiguity_preserves_block_identity` — block IDs and segments survive enforcement
