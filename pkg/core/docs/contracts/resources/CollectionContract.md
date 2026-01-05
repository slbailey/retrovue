# Collections

## Purpose

This document provides an overview of all Collection domain testing contracts. Individual Collection operations are covered by specific behavioral contracts that define exact CLI syntax, safety expectations, and data effects.

---

## Scope

The Collection domain is covered by the following specific contracts:

- **[Collection Ingest](CollectionIngestContract.md)**: Processing assets from a single collection
- **[Collection Show](CollectionShowContract.md)**: Displaying detailed collection information
- **[Collection List](CollectionListContract.md)**: Listing collections (optionally filtered by source)
- **[Collection Update](CollectionUpdateContract.md)**: Updating collection configuration, sync state, and enricher attachments
- **[Collection Wipe](CollectionWipeContract.md)**: Complete removal of collection data
- **Collection Delete** (planned): Deleting collections with cascade cleanup

---

## Contract Structure

Each Collection operation follows the standard contract pattern:

1. **Command Shape**: Exact CLI syntax and required flags
2. **Safety Expectations**: Confirmation prompts, dry-run behavior, force flags
3. **Output Format**: Human-readable and JSON output structure
4. **Exit Codes**: Success and failure exit codes
5. **Data Effects**: What changes in the database
6. **Behavior Contract Rules (B-#)**: Operator-facing behavior guarantees
7. **Data Contract Rules (D-#)**: Persistence, lifecycle, and integrity guarantees
8. **Test Coverage Mapping**: Explicit mapping from rule IDs to test files

---

## Design Principles

- **Safety first:** No destructive operation runs against live data during automated tests
- **One contract per noun/verb:** Each Collection operation has its own focused contract
- **Mock-first validation:** All operations must first be tested using mock/test databases
- **Idempotent operations:** Collection operations should be safely repeatable
- **Clear error handling:** Failed operations must provide clear diagnostic information
- **Unit of Work:** All database-modifying operations must be wrapped in atomic transactions

---

## Common Safety Patterns

All Collection contracts follow these safety patterns:

### Test Database Usage

- `--test-db` flag directs operations to isolated test environment
- Test database must be completely isolated from production
- No test data should persist between test sessions

### Dry-run Support

- `--dry-run` flag shows what would be performed without executing
- Essential for validating operations before execution
- Must show asset discovery, path validation, and operation preview

### Confirmation Models

- Destructive operations require confirmation prompts
- `--force` flag skips confirmations (use with caution)
- Clear indication of cascade effects and data impact
- **PRODUCTION SAFETY**: Collections with assets in PlaylogEvent or AsRunLog cannot be deleted in production

### Path Mapping Validation

- All collection operations must validate path mappings
- Local paths must exist and be accessible
- Plex paths must be valid external references
- Path mapping changes must be atomic with collection updates

---

## Contract Test Requirements

Each Collection contract must have exactly two test files:

1. **CLI Contract Test**: `tests/contracts/test_collection_{verb}_contract.py`

   - CLI syntax validation
   - Flag behavior verification
   - Output format validation
   - Error message handling

2. **Data Contract Test**: `tests/contracts/test_collection_{verb}_data_contract.py`
   - Database state changes
   - Transaction boundaries
   - Data integrity verification
   - Side effects validation

---

## Collection Lifecycle

Collections follow a specific lifecycle pattern:

1. **Discovery**: Collections are discovered from sources (Plex libraries, filesystem directories)
2. **Configuration**: Path mappings are configured to map external paths to local storage
3. **Enablement**: Collections are enabled for sync/ingest operations
4. **Ingest**: Assets are discovered and ingested from the collection
5. **Management**: Collections can be updated, have enrichers attached, or be wiped
6. **Deletion**: Collections can be deleted with proper cascade cleanup

---

## Key Collection Operations

### Collection Ingest

- **Purpose**: Process assets from a single collection
- **Scope**: Individual collection asset discovery and ingestion
- **Unit of Work**: Single UoW for all assets in the collection
- **Safety**: Atomic transaction with rollback on fatal errors

### Collection Wipe

- **Purpose**: Complete removal of all collection data
- **Scope**: Assets, episodes, seasons, titles, and related data
- **Unit of Work**: Single UoW for entire wipe operation
- **Safety**: Confirmation required, preserves path mappings for re-ingest

### Collection Management

- **Purpose**: Update collection configuration and settings
- **Scope**: Path mappings, sync enablement, enricher attachment
- **Unit of Work**: Single UoW for all configuration changes
- **Safety**: Validation of paths and configuration before changes

---

## See Also

- [Collection Domain Documentation](../../domain/Collection.md) - Core domain model and operations
- [Source Contracts](SourceContract.md) - Source-level operations that manage collections
- [CLI Contract](README.md) - General CLI command standards
- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements
