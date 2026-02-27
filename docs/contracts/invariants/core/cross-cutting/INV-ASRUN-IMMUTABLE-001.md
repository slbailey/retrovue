# INV-ASRUN-IMMUTABLE-001 — AsRun records MUST NOT be mutated after creation

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-IMMUTABILITY`

## Purpose

AsRun records are the historical broadcast record. If they can be mutated in place, the system loses the ability to audit what actually aired. `LAW-IMMUTABILITY` requires that committed broadcast artifacts are append-only. State transitions (e.g. recording an end time) MUST produce new instances, not modify existing ones.

## Guarantee

`AsRunEvent` is a frozen dataclass. Direct field mutation MUST raise `AttributeError`. State transitions via `AsRunLogger.log_playout_end()` MUST produce a new `AsRunEvent` instance via `dataclasses.replace()` without modifying the original.

## Preconditions

- An `AsRunEvent` has been created via `AsRunLogger.log_playout_start()`.

## Observability

Any attempt to assign a field on an `AsRunEvent` instance raises `AttributeError` at the point of mutation. `log_playout_end()` returns a new instance; the original is verifiably unchanged.

## Deterministic Testability

1. Create an `AsRunEvent`. Attempt direct field mutation. Assert `AttributeError`.
2. Call `log_playout_end()`. Assert the returned instance is not the original (`updated is not original`). Assert the original's fields are unchanged.
3. Create a valid `AsRunEvent`. Query it by broadcast day. Assert it persists correctly.

## Failure Semantics

**Runtime fault.** A mutable AsRun record means the broadcast history can be silently corrupted after the fact.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (TestInvAsrunImmutable001)

## Enforcement Evidence

**Enforcement location:**
- `AsRunEvent` in `pkg/core/src/retrovue/runtime/asrun_logger.py` (line 33) — `@dataclass(frozen=True)` prevents all field mutation after construction.
- `AsRunLogger.log_playout_end()` in `pkg/core/src/retrovue/runtime/asrun_logger.py` (line 144) — Uses `dataclasses.replace()` to produce a new instance with updated end time. Original instance is never modified.

**Tests:**
- `test_inv_asrun_immutable_001_reject_mutation`: Creates event, attempts field mutation. Asserts `AttributeError`. Verifies `log_playout_end()` returns new instance without modifying original.
- `test_inv_asrun_immutable_001_reject_deletion`: Verifies frozen dataclass prevents field reassignment. Event persists in logger.
- `test_inv_asrun_immutable_001_valid_creation`: Creates valid event, queries by broadcast day. Asserts all fields match and event is retrievable.
