# INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001

## Behavioral Guarantee

An override artifact MUST NOT be committed unless an override record has already been durably persisted. The record commit is the precondition; the artifact commit is the consequent. If override record persistence fails, the artifact MUST NOT be created.

## Authority Model

Override-capable write paths own this guarantee. Each path persists an `OverrideRecord` via `InMemoryOverrideStore.persist()` before mutating the artifact store. The two operations are treated as a logical atomic unit under the same lock scope.

## Boundary / Constraint

For every override-capable write path:

- `InMemoryResolvedStore.operator_override()`: MUST call `override_store.persist()` before creating the replacement `ResolvedScheduleDay`. If persist raises, the store MUST remain unchanged.
- `ExecutionWindowStore.publish_atomic_replace(operator_override=True)`: MUST call `override_store.persist()` under `self._lock` before any entry mutation. If persist raises, MUST return `PublishResult(ok=False, error_code="OVERRIDE_RECORD_PERSIST_FAILED")` with no generation change and no entry mutation.

At no point may an override artifact exist without a backing override record.

## Violation

Any of the following:

- Override artifact committed without a preceding override record.
- Override record persistence failure followed by artifact mutation.
- Override artifact visible to consumers before the override record is durable.

MUST be logged as runtime fault with tag `INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001-VIOLATED`.

## Derives From

`LAW-IMMUTABILITY` — override governance requires auditable record-before-artifact ordering.
`LAW-DERIVATION` — artifact traceability requires an anchoring record.

## Required Tests

- `pkg/core/tests/contracts/test_inv_override_record_precedes_artifact.py` (TOR-001: record created before artifact)
- `pkg/core/tests/contracts/test_inv_override_record_precedes_artifact.py` (TOR-002: persist failure prevents artifact)
- `pkg/core/tests/contracts/test_inv_override_record_precedes_artifact.py` (TOR-003: ExecutionWindow override atomicity)
- `pkg/core/tests/contracts/test_inv_override_record_precedes_artifact.py` (TOR-004: no silent artifact without record)
- `pkg/core/tests/contracts/test_scheduling_constitution.py` (reject_without_record, atomicity)

## Enforcement Evidence

- **ScheduleDay path:** `InMemoryResolvedStore.operator_override()` in `pkg/core/src/retrovue/runtime/schedule_manager_service.py`. Under `self._lock`, calls `self._override_store.persist()` before creating the replacement `ResolvedScheduleDay`. On persist failure (`RuntimeError`), exception propagates and no artifact mutation occurs.
- **ExecutionWindowStore path:** `ExecutionWindowStore.publish_atomic_replace()` in `pkg/core/src/retrovue/runtime/execution_window_store.py`. Under `self._lock`, when `operator_override=True` and `self._override_store is not None`, calls `self._override_store.persist()` before entry mutation. On persist failure, returns `PublishResult(ok=False, error_code="OVERRIDE_RECORD_PERSIST_FAILED")` with no generation change.
- **Override record model:** `OverrideRecord` (frozen dataclass) and `InMemoryOverrideStore` in `pkg/core/src/retrovue/runtime/override_record.py`. `fail_next_persist` flag enables failure injection in tests.
- **Test file:** `pkg/core/tests/contracts/test_inv_override_record_precedes_artifact.py` — TOR-001 (record before artifact), TOR-002 (persist failure blocks artifact), TOR-003 (EWS override atomicity), TOR-004 (no silent artifact without record).
