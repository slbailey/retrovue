# CLI ↔ Data Cross-Domain Guarantees

## Overview

This document defines the guarantees and constraints that govern interactions between the CLI domain and the Data domain. These guarantees ensure that command-line operations maintain consistency with database operations, transaction management, and data integrity.

The CLI-Data relationship is fundamental because:

- CLI commands orchestrate complex operations across multiple data models
- Data operations must maintain transactional integrity
- CLI must provide consistent error handling and user feedback
- Data layer must support CLI requirements for validation and rollback

### Data Flow Summary

The lifecycle of a CLI request follows this pattern:

1. **User invokes CLI** → Command parsing and initial validation
2. **Command validated** → Parameter validation against CLI contract
3. **API call to Data domain** → Business logic execution with transaction boundaries
4. **Persistence / rollback** → Atomic database operations with error handling
5. **CLI outputs result or error** → User-friendly feedback with appropriate exit codes

This flow ensures that CLI operations maintain consistency with data state while providing clear user feedback and proper error handling.

---

## Participating Domains

### CLI Domain

- **Contract:** All CLI command contracts (`docs/contracts/resources/*Contract.md`)
- **Interface:** Command-line interface, user interaction, output formatting
- **Responsibilities:** Command validation, user feedback, error reporting, output formatting

### Data Domain

- **Contract:** `docs/contracts/_ops/UnitOfWorkContract.md`, database schema contracts
- **Interface:** Database operations, transaction management, data persistence
- **Responsibilities:** Data persistence, transaction integrity, rollback management

---

## Cross-Domain Guarantees

### G-1: Transaction Boundary Management

**CLI operations MUST respect data transaction boundaries.**

- CLI commands MUST operate within appropriate transaction boundaries
- CLI MUST not span multiple transactions unless explicitly designed for orchestration
- Transaction failures MUST be handled gracefully with appropriate error codes
- CLI MUST emit clear error messages for transaction failures

### G-2: Data Validation Coordination

**CLI validation MUST coordinate with data validation.**

- CLI parameter validation MUST occur before any database operations
- Data validation MUST occur before persistence operations
- Validation failures MUST cause appropriate CLI exit codes
- CLI MUST emit clear error messages for validation failures

### G-3: Error Handling Consistency

**All CLI-initiated errors and all Data-domain rejections surfaced through the CLI must conform to the shared error contract.**

- Database errors MUST be translated to appropriate CLI error codes
- CLI error messages MUST be user-friendly and actionable
- All CLI-initiated errors and all Data-domain rejections surfaced through the CLI must conform to the shared error contract (error_code, message, context), ensuring parity between internal logs and user-facing messages
- CLI MUST provide clear guidance for error resolution

### G-4: Output Format Coordination

**CLI output formats MUST coordinate with data structures.**

- JSON output MUST accurately represent data model structures
- Human-readable output MUST be consistent with data relationships
- Output formatting MUST handle data validation states appropriately
- CLI MUST provide consistent output across different data states

### G-5: Rollback Coordination

**CLI rollback operations MUST coordinate with data rollback.**

- CLI rollback commands MUST trigger appropriate data rollback operations
- Data rollback MUST be atomic and complete
- CLI MUST provide clear feedback on rollback success/failure
- CLI and Data schemas must maintain forward and backward compatibility across minor versions. Breaking schema changes require a coordinated major version bump of both domains, reflected in their contract headers

### G-6: State Consistency

**CLI state MUST remain consistent with data state.**

- CLI operations MUST reflect current data state
- Data state changes MUST be reflected in CLI operations
- State inconsistencies MUST be detected and reported
- CLI MUST provide mechanisms for state verification

### G-7: Consistent Read Snapshot (CROSS-DOMAIN GUARANTEE)

**Any read-only CLI command that summarizes persisted state across more than one table MUST operate over a consistent read snapshot.**

Requirements:

- The command MUST build its entire response from a single transactional / repeatable-read snapshot of the database session.
- The reported aggregate values (like per-source collection counts) MUST match the entities returned in that same response.
- The reported `total` count MUST equal the number of returned objects in that snapshot.
- The command MUST NOT mix partially committed pre-transaction data with post-transaction updates in a single response.
- The command MUST NOT "requery" mid-output to fill in extra data if doing so would cross a transaction boundary.

This guarantee applies directly to:

- `retrovue source list`
- Any future `retrovue collection list`, `retrovue source status`, or similar inspection commands.

This guarantee exists to support operator trust: output MUST be internally consistent and explainable as "a view of the system at one moment in time," even under concurrent changes.

---

## Failure & Rollback Policy

### Transaction Failure Handling

1. **Validation Failure**: CLI MUST fail immediately with exit code 1
2. **Database Failure**: CLI MUST fail immediately with exit code 1
3. **Transaction Failure**: CLI MUST fail immediately with exit code 1
4. **State Failure**: CLI MUST fail immediately with exit code 1
5. **System Failure**: CLI MUST fail immediately with exit code 1

### Partial Failure Prevention

- **Atomic Operations**: CLI operations MUST be atomic where possible
- **Orchestration Handling**: Multi-step operations MUST handle partial failures gracefully
- **Atomic Rollback**: Data rollback MUST be complete and immediate
- **State Consistency**: System state MUST remain consistent after any failure

### Error Message Standards

- **Validation Errors**: "Error: {validation_error_message}"
- **Database Errors**: "Error: Database operation failed: {specific_error}"
- **Transaction Errors**: "Error: Transaction failed: {specific_error}"
- **State Errors**: "Error: System state inconsistent: {specific_error}"
- **System Errors**: "Error: {operation} failed: {specific_error_message}"

---

## Enforcement

### Test Coverage

- **Test File**: `tests/contracts/cross-domain/test_cli_data_guarantees.py`
- **Coverage**: All guarantees G-1 through G-7
- **Test Types**: Unit tests, integration tests, failure scenario tests
- **Mocking**: Database operations, transaction management, error conditions

### CI Integration

- **CI Step**: CrossDomainContracts enforcement
- **Command**: `pytest tests/contracts/cross-domain/ --maxfail=1 --disable-warnings -q`
- **Failure Policy**: Any cross-domain test failure MUST block PR merge
- **Coverage**: All cross-domain guarantees MUST be tested

### Contract Dependencies

- **All CLI Contracts**: Reference this guarantee in "Dependencies" section
- **UnitOfWorkContract**: References this guarantee in "Dependencies" section
- **Database Schema Contracts**: Reference this guarantee in "Dependencies" section

---

## Versioning & Change Coordination

### Version Coordination

- **Minor Changes**: CLI and Data contracts may bump minor versions independently
- **Major Changes**: Cross-domain guarantee changes require coordination between domains
- **Breaking Changes**: Must be coordinated across all participating domains

### Change Process

1. **Impact Assessment**: Evaluate impact on cross-domain guarantees
2. **Contract Updates**: Update relevant domain contracts
3. **Guarantee Updates**: Update this cross-domain guarantee document
4. **Test Updates**: Update cross-domain test suite
5. **Migration**: Update `CONTRACT_MIGRATION.md` status

### Backward Compatibility

- **Interface Stability**: Cross-domain interfaces MUST maintain backward compatibility
- **Schema Evolution**: Data schemas MUST support backward-compatible evolution
- **Migration Path**: Breaking changes MUST provide clear migration paths

---

## Examples

### Valid CLI Operation with Data Coordination

```bash
# Valid: CLI operation with proper data coordination
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token"
# Success: CLI validates, data persists atomically, CLI reports success
```

### Invalid CLI Operation with Data Validation

```bash
# Invalid: CLI validation fails before data operations
retrovue source add --type unknown --name "My Source"
# Exit code: 1
# Error: Unknown source type 'unknown'. Available types: plex, filesystem
```

### Database Failure with CLI Error Handling

```bash
# Invalid: Database operation fails
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token"
# Exit code: 1
# Error: Database operation failed: Connection timeout
```

### Transaction Failure with CLI Rollback

```bash
# Invalid: Transaction fails, CLI handles rollback
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token" \
  --discover
# Exit code: 1
# Error: Transaction failed: Collection discovery error
# Database rollback completed successfully
```

### Partial Success with CLI Orchestration

```bash
# Partial: Some operations succeed, others fail
retrovue source ingest "My Plex"
# Exit code: 2 (partial success)
# Success: Collections 'Movies', 'TV Shows' ingested
# Failed: Collection 'Music' failed ingestion
# Database state: Partial changes committed per collection
```

---

## See Also

- [UnitOfWorkContract](../../_ops/UnitOfWorkContract.md) - Transaction management contract
- [SourceAddContract](../SourceAddContract.md) - Source creation contract
- [SourceDiscoverContract](../SourceDiscoverContract.md) - Source discovery contract
- [SourceIngestContract](../SourceIngestContract.md) - Source ingestion contract
- [CollectionContract](../CollectionContract.md) - Collection management contract
- [CLI_CHANGE_POLICY.md](../CLI_CHANGE_POLICY.md) - CLI governance policy

---

## Traceability

- **Linked Tests:** `tests/contracts/cross-domain/test_cli_data_guarantees.py`
- **Dependencies:** All CLI command contracts (`docs/contracts/resources/*Contract.md`), `docs/contracts/_ops/UnitOfWorkContract.md`, database schema contracts
- **Last Audit:** 2025-10-28
