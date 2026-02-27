# INV-DERIVATION-ANCHOR-PROTECTED-001 — ResolvedScheduleDay with downstream execution artifacts MUST NOT be deleted

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

A `ResolvedScheduleDay` that has downstream `ExecutionEntry` artifacts in the `ExecutionWindowStore` is a constitutional anchor in the derivation chain. Deleting it severs traceability from execution artifacts back to their editorial source, violating `LAW-DERIVATION` and rendering the broadcast record unauditable.

## Guarantee

`InMemoryResolvedStore.delete()` MUST refuse deletion of a `ResolvedScheduleDay` when `ExecutionWindowStore.has_entries_for(channel_id, programming_day_date)` returns `True`. The anchor MUST survive the rejected deletion attempt.

A `ResolvedScheduleDay` with no downstream execution artifacts MAY be deleted freely.

## Preconditions

- An `ExecutionWindowStore` is configured on the resolved store.
- The `ResolvedScheduleDay` exists for the given `(channel_id, programming_day_date)`.

## Observability

`InMemoryResolvedStore.delete()` queries `ExecutionWindowStore.has_entries_for()` before removal. If downstream entries exist, a `ValueError` with tag `INV-DERIVATION-ANCHOR-PROTECTED-001-VIOLATED` is raised and the schedule day is preserved.

## Deterministic Testability

1. Materialize a `ResolvedScheduleDay`. Populate `ExecutionWindowStore` with entries derived from it. Attempt deletion. Assert `ValueError` raised and anchor survives.
2. Materialize a `ResolvedScheduleDay` with no downstream entries. Delete. Assert deletion succeeds.

## Failure Semantics

**Planning fault.** The resolved store permitted deletion of a schedule anchor with live downstream artifacts, severing the derivation chain.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (TestInvDerivationAnchorProtected001)

## Enforcement Evidence

**Enforcement location:**
- `InMemoryResolvedStore.delete()` in `pkg/core/src/retrovue/runtime/schedule_manager_service.py` (line 467) — Checks `ExecutionWindowStore.has_entries_for(channel_id, programming_day_date)` before removal. Raises `ValueError` with tag `INV-DERIVATION-ANCHOR-PROTECTED-001-VIOLATED` if downstream entries exist.
- `ExecutionWindowStore.has_entries_for()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` (line 214) — Scans entries matching `(channel_id, programming_day_date)`.

**Tests:**
- `test_inv_derivation_anchor_protected_001_reject_delete_with_downstream`: Populates execution store with 4 entries. Asserts deletion raises `ValueError`. Asserts anchor survives.
- `test_inv_derivation_anchor_protected_001_allow_delete_without_downstream`: No downstream entries. Asserts deletion succeeds.
