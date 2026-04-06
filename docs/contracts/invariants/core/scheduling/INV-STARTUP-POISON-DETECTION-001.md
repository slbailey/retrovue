# INV-STARTUP-POISON-DETECTION-001 — Startup poison detection

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the system does not silently operate with an empty schedule revision on a programmed day. An empty active revision on a non-dark day is a poisoned state that MUST be detected and corrected before playout proceeds.

## Guarantee

On startup, an empty active revision on a programmed day MUST be detected as invalid. The system MUST automatically supersede it and attempt rebuild. If rebuild fails, the channel MUST fail fast — not silently degrade.

## Preconditions

- The channel has a non-dark programming assignment for the target day.
- An active ScheduleRevision exists for that day with zero ScheduleItems.

## Observability

Startup health checks report the poisoned revision. Log events include the channel, broadcast day, and revision ID of the empty revision, plus the outcome (superseded or fail-fast).

## Deterministic Testability

Create a channel with a programmed day. Persist an empty active revision for that day. Invoke the startup/reconciliation path. Verify the empty revision is detected, superseded, and either rebuilt or the channel enters a fail-fast state.

## Failure Semantics

**Cross-layer fault.** An undetected empty revision causes the channel to emit silence or error frames, violating liveness without any operator-visible signal.

## Required Tests

- `pkg/core/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestEmptyRevisionPoisoning::test_empty_revision_does_not_produce_working_channel` — empty revision on a programmed day is detected as invalid
- `TestEmptyRevisionPoisoning::test_empty_revision_is_superseded_after_recovery` — system supersedes the empty revision and rebuilds
