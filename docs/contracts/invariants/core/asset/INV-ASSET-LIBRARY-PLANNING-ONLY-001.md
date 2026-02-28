# INV-ASSET-LIBRARY-PLANNING-ONLY-001 — Asset Library is planning-only

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-RUNTIME-AUTHORITY`

## Purpose

The Asset Library is a planning-time resource. If runtime components (ChannelManager, AIR) queried the Asset Library during execution, they would introduce a planning-time dependency into the runtime path, violating the separation between editorial orchestration and runtime execution. Execution data MUST contain only pre-resolved references.

## Guarantee

The Asset Library MUST be queried ONLY by the planning pipeline (Schedule Manager, HorizonManager, BlockPlanProducer). ChannelManager and AIR MUST NOT import, instantiate, or reference the Asset Library at any time.

## Preconditions

None. This invariant holds unconditionally.

## Observability

Verified by static analysis: runtime/execution code paths (`channel_manager.py`, `playout_session.py`, AIR C++ code) MUST NOT contain imports of `db_asset_library`, `DatabaseAssetLibrary`, or `InMemoryAssetLibrary`.

## Deterministic Testability

Grep the runtime/execution codebase for Asset Library imports. Assert no matches. No real database required.

## Failure Semantics

**Architectural violation.** Runtime code imported or instantiated the Asset Library, creating a planning-time dependency in the execution path. The import MUST be removed and replaced with pre-resolved data passed through the execution contract.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetLibraryPlanningOnly001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/channel_manager.py` — no Asset Library imports
- `pkg/core/src/retrovue/runtime/playout_session.py` — no Asset Library imports
- `pkg/air/` — no Asset Library references
- Error tag: `INV-ASSET-LIBRARY-PLANNING-ONLY-001-VIOLATED`
