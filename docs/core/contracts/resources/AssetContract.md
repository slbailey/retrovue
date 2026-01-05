# Assets

## Purpose

This document provides an overview of all Asset domain testing contracts. Individual Asset operations are covered by specific behavioral contracts that define exact CLI syntax, safety expectations, and data effects.

---

## Scope

**Implemented Contracts:**

- **[Asset Attention](AssetAttentionContract.md)**: List assets needing operator attention (downgraded or not broadcastable)
- **[Asset Resolve](AssetResolveContract.md)**: Resolve a single asset by approving and/or marking ready

**Planned Contracts:**

- **[Asset Select](AssetsSelectContract.md)**: Selecting assets by various criteria (UUID, title, series, genre, etc.)
- **[Asset Delete](AssetsDeleteContract.md)**: Deleting assets (soft or hard delete) and restoring soft-deleted assets
- **[Asset Show](AssetShowContract.md)**: Displaying detailed asset information
- **[Asset List](AssetListContract.md)**: Listing assets with filtering options
- **[Asset Update](AssetUpdateContract.md)**: Updating asset metadata and configuration
- **[Asset Tagging](AssetTaggingContract.md)**: Replace-or-set tags on assets with normalized semantics
- **[Asset Confidence & Auto-State](AssetConfidenceContract.md)**: Confidence scoring during ingest to auto-approve or route for review

---

## Contract Structure

Each Asset operation follows the standard contract pattern:

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
- **One contract per noun/verb:** Each Asset operation has its own focused contract
- **Mock-first validation:** All operations must first be tested using mock/test databases
- **Idempotent operations:** Asset operations should be safely repeatable
- **Clear error handling:** Failed operations must provide clear diagnostic information
- **Unit of Work:** All database-modifying operations must be wrapped in atomic transactions

---

## Common Safety Patterns

All Asset contracts follow these safety patterns:

### Test Database Usage

- `--test-db` flag directs operations to isolated test environment
- Test database must be completely isolated from production
- No test data should persist between test sessions

### Dry-run Support

- `--dry-run` flag shows what would be performed without executing
- Essential for validating operations before execution
- Must show asset selection, validation, and operation preview

### Confirmation Models

- Destructive operations require confirmation prompts
- `--force` flag skips confirmations (use with caution)
- Clear indication of cascade effects and data impact
- **PRODUCTION SAFETY**: Assets referenced by PlaylogEvent or AsRunLog cannot be deleted in production

### Asset Selection

- Assets can be selected by UUID, title, series/season/episode hierarchy, or genre
- Selection supports bulk operations for multiple assets
- Selection is read-only and does not modify asset state

---

## Contract Test Requirements

Each Asset contract must have exactly two test files:

1. **CLI Contract Test**: `tests/contracts/test_asset_{verb}_contract.py` or `test_assets_{verb}_contract.py` (based on CLI noun)

   - CLI syntax validation
   - Flag behavior verification
   - Output format validation
   - Error message handling

2. **Data Contract Test**: `tests/contracts/test_asset_{verb}_data_contract.py` or `test_assets_{verb}_data_contract.py`
   - Database state changes
   - Transaction boundaries
   - Data integrity verification
   - Side effects validation

---

## Asset Lifecycle

Assets follow a specific lifecycle pattern:

1. **Discovery**: Assets are discovered during collection ingest operations
2. **Enrichment**: Assets progress through `new` → `enriching` → `ready` states
3. **Approval**: Assets become `approved_for_broadcast=true` when fully processed
4. **Scheduling**: Only `ready` assets with `approved_for_broadcast=true` are eligible for scheduling
5. **Playout**: Ready assets are played out through the broadcast pipeline
6. **Management**: Assets can be updated, deleted, or restored
7. **Retirement**: Assets can be marked as `retired` when no longer available

---

## Key Asset Operations

### Asset Select

- **Purpose**: Select assets by various criteria for bulk operations
- **Scope**: UUID, title, series/season/episode hierarchy, genre filtering
- **Unit of Work**: Read-only operation (no database writes)
- **Safety**: No state changes, safe for preview and bulk operations

### Asset Delete

- **Purpose**: Delete assets (soft or hard delete)
- **Scope**: Individual assets or bulk deletion by criteria
- **Unit of Work**: Single UoW for deletion operation
- **Safety**: Soft delete by default, hard delete requires confirmation and reference checks

### Asset Restore

- **Purpose**: Restore soft-deleted assets
- **Scope**: Individual assets or bulk restoration by criteria
- **Unit of Work**: Single UoW for restoration operation
- **Safety**: Only soft-deleted assets can be restored

### Asset Show (Planned)

- **Purpose**: Display detailed asset information
- **Scope**: Single asset by UUID or external identifier
- **Unit of Work**: Read-only operation
- **Safety**: No state changes, safe for inspection

### Asset List (Planned)

- **Purpose**: List assets with filtering options
- **Scope**: Multiple assets filtered by collection, state, or criteria
- **Unit of Work**: Read-only operation
- **Safety**: No state changes, safe for browsing

### Asset Update (Planned)

- **Purpose**: Update asset metadata and configuration
- **Scope**: Single asset by UUID
- **Unit of Work**: Single UoW for update operation
- **Safety**: Validation of metadata before changes

---

## Asset State Rules

The following rules apply to all Asset operations:

- **Only `ready` assets with `approved_for_broadcast=true` are eligible for scheduling**
- **Newly ingested assets MUST enter the system in `new` or `enriching` state**
- **Assets in `ready` state MUST have `approved_for_broadcast=true`**
- **Assets with `approved_for_broadcast=true` MUST be in `ready` state**
- **Soft-deleted assets (`is_deleted=true`) are excluded from normal operations**

Planned extension (see Asset Confidence & Auto-State): confidence scoring during ingest may
determine initial `state` and `approved_for_broadcast`, with importer-stable thresholds.

---

## See Also

- [Asset Domain Documentation](../../domain/Asset.md) - Core domain model and operations
- [Collection Contracts](CollectionContract.md) - Collection-level operations that manage assets
- [Source Contracts](SourceContract.md) - Source-level operations that manage collections
- [CLI Contract](README.md) - General CLI command standards
- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements
 - [Asset Tagging](AssetTaggingContract.md)
 - [Asset Confidence & Auto-State](AssetConfidenceContract.md)

