# INV-TIMELINE-RESTART-IDENTICAL-001 — Restart determinism

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-IMMUTABILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-IMMUTABILITY` by ensuring that a system restart — an operational event — does not alter what is scheduled or playing. Restart MUST NOT function as an implicit editorial action.

## Guarantee

A system restart MUST NOT change the timeline for any time range that was already defined prior to the restart.

## Observability

For any time T within the pre-restart timeline, the post-restart system MUST return identical program identity, timing, and structure.

## Deterministic Testability

Record the output of "what block covers time T" for every T in the compiled horizon. Restart the process. Query the same set of T values. Every answer MUST be identical — same block ID, same program, same start/end times.

## Failure Semantics

**Cross-layer fault.** A restart that produces a different timeline silently replaces in-flight or already-aired programs without operator intent.

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

- `TestTimelineRestartIdentical::test_enforce_contiguity_is_deterministic` — contiguity enforcement is idempotent (stable across restarts)
- `TestTimelineRestartIdentical::test_push_forward_is_deterministic` — push-forward is idempotent
- `TestTimelineRestartIdentical::test_contiguity_preserves_block_identity` — block IDs and segments survive enforcement
