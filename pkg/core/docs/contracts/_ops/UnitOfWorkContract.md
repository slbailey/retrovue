# Unit of Work Contract

## Purpose

Define the observable guarantees for all RetroVue operations that modify database state. This contract specifies **what** the system guarantees (atomicity, consistency, isolation), not how those guarantees are implemented.

---

## Core Guarantees

### UOW-001: Atomicity (All-or-Nothing)

**Guarantee:** Operations either complete successfully with all changes persisted, or fail completely with no changes persisted.

**Observable behavior:**
- On success: all expected database records exist and are consistent
- On failure: database state is identical to pre-operation state
- No partial state is ever observable between operation start and completion

**Verification:** Query database before and after a failed operation; state must be identical.

---

### UOW-002: Consistency (Valid State Transitions)

**Guarantee:** Operations only transition the database from one valid state to another valid state.

**Observable behavior:**
- All foreign key constraints are satisfied after operation
- All business invariants hold after operation
- No orphaned records exist after operation

**Verification:** After any operation, database constraint checks pass and invariant queries return expected results.

---

### UOW-003: Isolation (No Cross-Operation Interference)

**Guarantee:** Concurrent operations do not interfere with each other.

**Observable behavior:**
- Each operation sees a consistent snapshot of data
- Operations do not observe partial results from other in-flight operations
- No phantom reads or dirty reads occur

**Verification:** Run concurrent operations; each completes with consistent results.

---

## Pre-Operation Validation

### UOW-010: Prerequisites Checked Before Changes

**Guarantee:** All prerequisites are validated before any database modifications occur.

**Observable behavior:**
- If prerequisites fail, operation exits with validation error
- No database changes occur when prerequisites fail
- Error message clearly identifies which prerequisite failed

**Exit code:** `1` (validation error)

**Example prerequisites:**
- Resource exists (collection, source, channel)
- Resource is in valid state for operation
- Required relationships exist
- No conflicting operations in progress

---

## Post-Operation Validation

### UOW-020: Results Verified Before Commit

**Guarantee:** Operation results are validated before changes become permanent.

**Observable behavior:**
- If post-validation fails, all changes are rolled back
- Error message clearly identifies what validation failed
- Database state reverts to pre-operation state

**Exit code:** `1` (validation error)

**Example validations:**
- All created records have valid relationships
- No orphaned records exist
- Business invariants are satisfied

---

## Error Handling

### UOW-030: Error Types and Exit Codes

| Exit Code | Error Type | Meaning |
|-----------|------------|---------|
| `0` | Success | Operation completed, all changes persisted |
| `1` | Validation Error | Prerequisites or post-validation failed; no changes persisted |
| `2` | Partial Success | Some targets succeeded, others failed (batch operations only) |
| `3` | External Error | External system unavailable; no changes persisted |

### UOW-031: Error Messages

**Guarantee:** All errors produce clear, actionable messages.

**Observable behavior:**
- Error message identifies the specific failure
- Error message includes relevant context (IDs, names)
- JSON output includes structured error information

**JSON error format:**
```json
{
  "status": "error",
  "code": "<ERROR_CODE>",
  "message": "Human-readable description",
  "context": {
    "resource_id": "...",
    "operation": "..."
  }
}
```

### UOW-032: Rollback on Failure

**Guarantee:** Any failure during operation execution triggers complete rollback.

**Observable behavior:**
- Database state after failure matches database state before operation
- No partial records exist
- No orphaned relationships exist

---

## Batch Operation Guarantees

### UOW-040: Batch Atomicity Options

**Guarantee:** Batch operations clearly define their atomicity scope.

**Option A — All-or-nothing batch:**
- All targets succeed, or entire batch fails
- No partial results
- Exit code: `0` (all succeeded) or `1` (any failed)

**Option B — Best-effort batch:**
- Each target processed independently
- Successful targets committed; failed targets rolled back individually
- Exit code: `0` (all succeeded), `2` (partial success), or `1` (all failed)

**Observable behavior:**
- Contract for each operation specifies which option applies
- Partial success reports which targets succeeded and which failed

---

## Test Database Isolation

### UOW-050: Test Database Guarantees

**Guarantee:** Operations with `--test-db` are completely isolated from production.

**Observable behavior:**
- No production tables are read or written
- Test data does not persist between test sessions (unless explicitly configured)
- Behavior, output format, and exit codes match production mode

---

## Contract Test Requirements

Tests verifying Unit of Work compliance must check:

1. **Atomicity test:** Force failure mid-operation; verify no partial state
2. **Rollback test:** Trigger validation error; verify state unchanged
3. **Consistency test:** After operation, verify all constraints satisfied
4. **Error format test:** On failure, verify error message and exit code
5. **Batch test (if applicable):** Verify correct handling of mixed success/failure

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| UOW-001 | All-or-nothing execution |
| UOW-002 | Valid state transitions only |
| UOW-003 | No cross-operation interference |
| UOW-010 | Prerequisites checked before changes |
| UOW-020 | Results verified before commit |
| UOW-030 | Defined exit codes |
| UOW-031 | Clear error messages |
| UOW-032 | Complete rollback on failure |
| UOW-040 | Batch atomicity clearly defined |
| UOW-050 | Test database isolation |

---

## See Also

- [Collection Wipe Contract](../resources/CollectionWipeContract.md) — applies UOW guarantees
- [Source Ingest Contract](../resources/SourceIngestContract.md) — applies UOW guarantees
- [Collection Ingest Contract](../resources/CollectionIngestContract.md) — applies UOW guarantees
- [Contract Hygiene Checklist](../../../standards/contract-hygiene.md) — authoring guidelines
