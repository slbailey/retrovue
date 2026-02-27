# INV-SCHEDULEDAY-IMMUTABLE-001 — ScheduleDay is immutable once materialized

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

## Purpose

Protects EPG truthfulness and the derivation chain from post-hoc corruption. A mutable ResolvedScheduleDay means downstream artifacts (ExecutionEntry, AsRun) derived from it may silently diverge from the current ResolvedScheduleDay state, creating a derivation chain where downstream artifacts cannot be traced back to a stable upstream truth — directly violating `LAW-DERIVATION`.

## Guarantee

A ResolvedScheduleDay's slot assignments, asset placements, and wall-clock times MUST NOT be mutated after materialization. The only permitted modifications are:

1. **Atomic force-regeneration**: the existing record is replaced atomically (delete + insert as a single transaction).
2. **Operator manual override**: a new ResolvedScheduleDay record is created with `is_manual_override=true`, referencing the superseded record's ID. The original record is preserved for audit.

In-place field updates to a materialized ResolvedScheduleDay are unconditionally prohibited.

## Preconditions

- ResolvedScheduleDay record exists in the store (has been persisted).

## Observability

Enforced at two levels:

1. **Type-level**: `ResolvedScheduleDay`, `ResolvedSlot`, `ResolvedAsset`, `ProgramEvent`, `SequenceState` are `frozen=True` dataclasses. Direct field assignment raises `AttributeError`.
2. **Store-level**: `InMemoryResolvedStore.update()` unconditionally raises `ValueError` with tag `INV-SCHEDULEDAY-IMMUTABLE-001-VIOLATED`. No in-place mutation path exists.

## Deterministic Testability

Materialize a ResolvedScheduleDay. Attempt direct field assignment (rejected by frozen dataclass). Attempt `store.update()` (rejected with invariant tag). Separately, perform `force_replace()` and assert new record replaced old atomically. Perform `operator_override()` and assert new record with override metadata, original preserved. No real-time waits required.

## Failure Semantics

**Runtime fault** if the system mutated a ResolvedScheduleDay without an authorized workflow. **Operator fault** if a manual database edit bypassed application-layer enforcement.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledayImmutable001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_types.py` — `ResolvedScheduleDay(frozen=True)`, `ResolvedSlot(frozen=True)`, `ResolvedAsset(frozen=True)`, `ProgramEvent(frozen=True)`, `SequenceState(frozen=True)`
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.update()` unconditionally rejects, `operator_override()` creates new record with override metadata
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.force_replace()` atomically swaps records
- Error tag: `INV-SCHEDULEDAY-IMMUTABLE-001-VIOLATED`
