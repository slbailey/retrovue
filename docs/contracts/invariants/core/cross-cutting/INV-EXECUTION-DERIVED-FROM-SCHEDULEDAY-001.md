# INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 — Every execution artifact must be traceable to exactly one ResolvedScheduleDay

Status: Invariant
Authority Level: Execution
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Enforces `LAW-DERIVATION` at the execution layer. An ExecutionEntry that cannot be traced to a ResolvedScheduleDay represents content that entered the broadcast chain outside the constitutional derivation pipeline. Such content is editorially unauthorized: it was never vetted by a SchedulePlan, never materialized into a ScheduleDay, and never subjected to the eligibility, grid-alignment, or coverage invariants that govern the planning layers.

Without deterministic lineage from every execution artifact back to its source ResolvedScheduleDay, the system cannot:

- **Audit** what aired and why it aired (LAW-DERIVATION).
- **Reproduce** the exact same execution sequence from the same inputs (deterministic derivation).
- **Attribute** content authority to the SchedulePlan that authorized it (LAW-CONTENT-AUTHORITY).
- **Detect** unauthorized content injection at the execution boundary.

The execution layer is not an independent scheduling authority. It is a deterministic consumer of planning artifacts. This invariant makes that boundary enforceable.

## Guarantee

Every `ExecutionEntry` materialized into the `ExecutionWindowStore` must satisfy:

1. The entry carries an explicit `programming_day_date` field identifying the `ResolvedScheduleDay` it was derived from.
2. That `programming_day_date`, combined with the channel identifier, resolves to exactly one `ResolvedScheduleDay` in the resolved store at the time the entry was generated.
3. The derivation is deterministic: given the same `ResolvedScheduleDay`, the same `ExecutionEntry` sequence is produced regardless of when or how many times the pipeline runs.

Implicit traceability via `block_id` string parsing is not a constitutional traceability mechanism. It is fragile, unenforceable at the type level, and insufficient for audit.

ExecutionEntries created by an explicit recorded operator override are exempt from condition 2 but must still carry `programming_day_date` and an override record reference.

## Preconditions

- The planning pipeline has been invoked for a channel and broadcast date.
- A `ResolvedScheduleDay` exists in the resolved store for that `(channel_id, programming_day_date)`.

## Observability

At `ExecutionWindowStore.add_entries()` time, the store MUST verify that every entry carries a non-null `programming_day_date`. Any entry with `programming_day_date=None` and no override record MUST be rejected before it enters the store. Violations MUST be logged with: entry `block_id`, channel identifier, and fault class.

Audit query across the execution window: any `ExecutionEntry` where `programming_day_date` is null and no override record exists is a constitutional violation.

## Deterministic Testability

1. Construct an `ExecutionEntry` without a `programming_day_date` field. Assert that the model or the store rejects it. No real-time waits required.
2. Run the planning pipeline for a known `ResolvedScheduleDay`. Assert every resulting `ExecutionEntry` carries a `programming_day_date` matching the source day. Assert the entries are reproducible across repeated pipeline invocations.

## Failure Semantics

**Planning fault.** The pipeline generated an execution artifact outside the constitutional derivation chain. Indicates a logic error in the ScheduleDay-to-ExecutionEntry conversion, or a bypass of the pipeline entirely.

## Anchor Protection

A `ResolvedScheduleDay` that has downstream `ExecutionEntry` artifacts MUST NOT be deleted from the resolved store. Removing a schedule anchor while execution artifacts still reference it severs the derivation chain and renders the broadcast record unauditable. See `INV-DERIVATION-ANCHOR-PROTECTED-001`.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (TestInvExecutionDerivedFromScheduleday001)

## Enforcement Evidence

**Enforcement location:**
- `ExecutionWindowStore.add_entries()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` (line 121) — Rejects any `ExecutionEntry` where `channel_id` is empty or `programming_day_date` is `None`. Raises `ValueError` with tag `INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001-VIOLATED`.

**Tests:**
- `test_inv_execution_derived_from_scheduleday_001_reject_without_lineage`: Submits entries with `programming_day_date=None` and `channel_id=""`. Asserts both rejected. Store remains empty.
- `test_inv_execution_derived_from_scheduleday_001_valid_lineage`: Produces entries from a valid `ResolvedScheduleDay`. Asserts all carry correct `programming_day_date`.
