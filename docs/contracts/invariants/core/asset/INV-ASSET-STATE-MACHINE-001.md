# INV-ASSET-STATE-MACHINE-001 — Asset state transitions are strictly defined

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

## Purpose

The asset lifecycle is a finite state machine. Permitting arbitrary transitions (e.g., `new` directly to `ready`, or `ready` back to `new`) would bypass enrichment, invalidate technical metadata, or create assets in states that violate downstream invariants such as `INV-ASSET-APPROVED-IMPLIES-READY-001`.

## Guarantee

The only legal state transitions are:

- `new` -> `enriching`
- `enriching` -> `ready`
- `enriching` -> `new` (revert on enrichment failure)
- `any` -> `retired`

No other transitions are permitted. Attempting an illegal transition MUST raise `ValueError` with tag `INV-ASSET-STATE-MACHINE-001-VIOLATED`.

## Preconditions

None. This invariant holds unconditionally for all asset state mutations.

## Observability

Enforced by `validate_state_transition(current_state, new_state)` called on every state assignment. Violations raise `ValueError` with the invariant tag and a description of the illegal transition.

## Deterministic Testability

For each pair `(current, proposed)` in the state space `{new, enriching, ready, retired}`, assert that legal transitions succeed and illegal transitions raise `ValueError` with the invariant tag. No real database required.

## Failure Semantics

**Logic fault.** Code attempted a state transition that bypasses the enrichment pipeline or reverses a completed lifecycle step. This indicates a missing guard or incorrect use-case orchestration.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetStateMachine001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — `validate_state_transition()` function
- `pkg/core/src/retrovue/usecases/ingest_orchestrator.py` — uses validated transitions
- `pkg/core/src/retrovue/usecases/asset_reprobe.py` — uses validated transitions
- Error tag: `INV-ASSET-STATE-MACHINE-001-VIOLATED`
