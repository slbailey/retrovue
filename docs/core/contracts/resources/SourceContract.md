# Source

## Purpose

This document provides an overview of all Source domain testing contracts. Individual Source operations are covered by specific behavioral contracts that define exact CLI syntax, safety expectations, and data effects.

---

## Scope

The Source domain is covered by the following specific contracts:

- **[Source Add](SourceAddContract.md)**: Creating new content sources
- **[Source Delete](SourceDeleteContract.md)**: Deleting sources with cascade cleanup
- **[Source Discover](SourceDiscoverContract.md)**: Discovering collections from sources
- **[Source Ingest](SourceIngestContract.md)**: Processing collections for asset discovery
- **[Source Update](SourceUpdateContract.md)**: Updating source configurations
- **Source Enrichers** (planned): Managing metadata enrichers

---

## Contract Structure

Each Source operation follows the standard contract pattern:

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
- **One contract per noun/verb:** Each Source operation has its own focused contract
- **Mock-first validation:** All operations must first be tested using mock/test databases
- **Idempotent operations:** Source operations should be safely repeatable
- **Clear error handling:** Failed operations must provide clear diagnostic information
- **Source type validity:** All source operations must use valid, supported source types
- **Configuration validation:** Source configurations must be valid for the specified source type

---

## Common Safety Patterns

All Source contracts follow these safety patterns:

### Test Database Usage

- `--test-db` flag directs operations to isolated test environment
- Test database must be completely isolated from production
- No test data should persist between test sessions

### Dry-run Support

- `--dry-run` flag shows what would be performed without executing
- Essential for validating operations before execution
- Must show configuration validation and external ID generation

### Confirmation Models

- Destructive operations require confirmation prompts
- `--force` flag skips confirmations (use with caution)
- Clear indication of cascade effects and data impact
- Importer interface compliance verification before operations

---

## Contract Test Requirements

Each Source contract must have exactly two test files:

1. **CLI Contract Test**: `tests/contracts/test_source_{verb}_contract.py`

   - CLI syntax validation
   - Flag behavior verification
   - Output format validation
   - Error message handling

2. **Data Contract Test**: `tests/contracts/test_source_{verb}_data_contract.py`
   - Database state changes
   - Transaction boundaries
   - Data integrity verification
   - Side effects validation

---

## See Also

- [Source Domain Documentation](../../domain/Source.md) - Core domain model and operations
- [Collection Wipe](CollectionWipeContract.md) - Reference implementation pattern
- [CLI Contract](README.md) - General CLI command standards
- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements
