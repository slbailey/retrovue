# INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001 — Every ExecutionEntry must be traceable to a TransmissionLogEntry

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Enforces `LAW-DERIVATION` at the runtime layer. An ExecutionEntry that cannot be traced to a TransmissionLogEntry represents content introduced into the execution stream outside the constitutional derivation chain. This would allow the runtime layer to play content that was never authorized by a SchedulePlan, violating `LAW-CONTENT-AUTHORITY`. It also severs the audit chain required by `INV-ASRUN-TRACEABILITY-001`.

## Guarantee

Every ExecutionEntry, except those created by an explicit recorded operator override, must be derived from a TransmissionLogEntry that is itself traceable to a ResolvedScheduleDay.

An ExecutionEntry with no TransmissionLogEntry reference and no operator override record MUST NOT be persisted.

## Preconditions

- ExecutionEntry is not an operator-initiated override (i.e., no override record exists for it).

## Observability

Application-layer enforcement at ExecutionEntry creation time. Audit query: any ExecutionEntry with no TransmissionLogEntry reference and no override record is a violation. HorizonManager MUST verify derivation before committing each entry.

## Deterministic Testability

Attempt to create an ExecutionEntry without a TransmissionLogEntry reference and without an override record via HorizonManager. Assert creation is rejected. Separately, create one with a valid TransmissionLogEntry reference and assert it is accepted. No real-time waits required.

## Failure Semantics

**Planning fault.** HorizonManager generated an entry outside the constitutional derivation chain. Indicates a logic error in the TransmissionLog-to-ExecutionEntry conversion.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvExecutionentryDerivedFromTransmissionlog001`

## Enforcement Evidence

`ExecutionWindowStore.add_entries()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` — when `enforce_derivation_from_playlist=True`, rejects any entry where `transmission_log_ref is None` and `is_operator_override is False` with tag `INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED`. Check runs before the schedule lineage check (fail fast).
