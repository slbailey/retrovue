# INV-SCHEDULEDAY-IMMUTABLE-001 — ScheduleDay is immutable once materialized

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

## Purpose

Protects EPG truthfulness and the Playlist derivation chain from post-hoc corruption. A mutable ScheduleDay means Playlist entries derived from it may silently diverge from the current ScheduleDay state, creating a derivation chain where downstream artifacts cannot be traced back to a stable upstream truth — directly violating `LAW-DERIVATION`.

## Guarantee

A ScheduleDay's zone assignments, SchedulableAsset placements, and wall-clock times MUST NOT be mutated after materialization. The only permitted modifications are:

1. **Atomic force-regeneration**: the existing record is replaced atomically (delete + insert as a single transaction).
2. **Operator manual override**: a new ScheduleDay record is created with `is_manual_override=true`, referencing the superseded record's ID. The original record is preserved for audit.

In-place field updates to a materialized ScheduleDay are unconditionally prohibited.

## Preconditions

- ScheduleDay record exists in the database (has been persisted).

## Observability

Any SQL `UPDATE` targeting slot assignments or timing fields on an existing ScheduleDay record (outside of an atomic force-regeneration transaction) is a violation. Application-layer enforcement must reject such mutations before they reach the database.

## Deterministic Testability

Materialize a ScheduleDay. Attempt to update a slot's wall-clock time via the application layer. Assert the update is rejected. Separately, perform a force-regeneration and assert the old record is replaced atomically (old record absent, new record present, no intermediate state visible). No real-time waits required.

## Failure Semantics

**Runtime fault** if the system mutated a ScheduleDay without an authorized workflow. **Operator fault** if a manual database edit bypassed application-layer enforcement.

## Required Tests

- `pkg/core/tests/contracts/test_inv_scheduleday_immutable.py`

## Enforcement Evidence

TODO
