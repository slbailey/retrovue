# INV-ASSET-APPROVED-IMPLIES-READY-001 — Approval requires ready state

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

## Purpose

An asset marked `approved_for_broadcast=true` while in any state other than `ready` creates a false eligibility signal: downstream consumers (scheduling, horizon, playout plan) would select an asset whose technical metadata is incomplete or absent. This invariant prevents that by coupling approval to readiness.

## Guarantee

`approved_for_broadcast = TRUE` MUST imply `state = 'ready'`. Setting `approved_for_broadcast = TRUE` on an asset whose state is not `ready` MUST be rejected.

## Preconditions

None. This invariant holds unconditionally across all asset lifecycle operations.

## Observability

Enforced at the database layer via CHECK constraint `chk_approved_implies_ready`. Any INSERT or UPDATE violating this relationship MUST raise a constraint-violation error with tag `INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED`.

## Deterministic Testability

Construct an asset stub with `state='new'` and `approved_for_broadcast=True`. Assert validation rejects the combination. Repeat with `state='enriching'`. Then construct `state='ready'` with `approved_for_broadcast=True` and assert acceptance. No real database required.

## Failure Semantics

**Data integrity fault.** Code attempted to approve an asset that has not completed enrichment. This indicates a logic error in the approval workflow or a missing state-machine guard.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetApprovedImpliesReady001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — CHECK constraint `chk_approved_implies_ready`: `(NOT approved_for_broadcast) OR (state = 'ready')`
- Error tag: `INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED`
