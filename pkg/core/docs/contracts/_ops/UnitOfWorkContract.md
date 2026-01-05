# Unit of Work

## Purpose

Define the Unit of Work (UoW) paradigm for all RetroVue operations to ensure atomicity, consistency, and data integrity. All operations that modify database state MUST follow this contract.

## Core Principles

### 1. Atomicity

- **All-or-Nothing**: Operations either complete successfully or fail completely
- **No Partial State**: Database must never be left in an inconsistent state
- **Rollback on Failure**: Any failure must roll back all changes made during the operation

### 2. Consistency

- **Pre-flight Validation**: Validate all prerequisites before making any changes
- **Constraint Enforcement**: Ensure all database constraints are satisfied
- **Business Rule Compliance**: Enforce business rules throughout the operation

### 3. Isolation

- **Transaction Boundaries**: Each operation runs in its own transaction
- **No Cross-Operation State**: Operations cannot interfere with each other
- **Clean State**: Each operation starts with a clean, consistent database state

## Contract Requirements

### 1. Operation Structure

Every operation MUST follow this structure:

```python
def operation_name(params...) -> OperationResult:
    """
    Operation description.

    Pre-conditions:
    - List all prerequisites that must be met

    Post-conditions:
    - List all guarantees if operation succeeds

    Atomicity:
    - Describe what happens on failure
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            validate_prerequisites(db, params)

            # Phase 2: Execute operation
            result = execute_operation(db, params)

            # Phase 3: Post-operation validation
            validate_result(db, result)

            return result

        except Exception as e:
            # Transaction automatically rolls back
            logger.error("operation_failed", operation="operation_name", error=str(e))
            raise OperationError(f"Operation failed: {e}")
```

### 2. Pre-flight Validation

**MUST validate before any changes:**

- **Resource Availability**: Ensure all required resources exist
- **Constraint Satisfaction**: Verify all constraints can be satisfied
- **Business Rules**: Check all business rules are met
- **Dependency Integrity**: Ensure all dependencies are valid

**Examples:**

- Collection exists and is accessible
- Source is reachable and authenticated
- Path mappings are valid and accessible
- No conflicting operations in progress

### 3. Post-operation Validation

**MUST validate after changes:**

- **Data Integrity**: Verify all relationships are correct
- **Constraint Compliance**: Ensure all constraints are satisfied
- **Business Rule Compliance**: Verify business rules are met
- **State Consistency**: Confirm database state is consistent

**Examples:**

- All created entities have valid relationships
- No orphaned records exist
- All foreign key constraints are satisfied
- Business invariants are maintained

## Operation-Specific Contracts

### Ingest Operations

#### Collection Ingest Contract

```python
def ingest_collection(collection_id: str, filters: IngestFilters) -> IngestResult:
    """
    Ingest all assets from a collection.

    Pre-conditions:
    - Collection exists and is enabled
    - Collection has valid path mappings
    - Source is reachable and authenticated
    - No conflicting ingest operations in progress

    Post-conditions:
    - All discovered assets are processed
    - All created entities have valid relationships
    - No orphaned records exist
    - Collection state is consistent

    Atomicity:
    - If any asset fails to process, entire operation rolls back
    - If any enricher fails, entire operation rolls back
    - If any validation fails, entire operation rolls back
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            collection = validate_collection_exists(db, collection_id)
            validate_collection_enabled(collection)
            validate_path_mappings(db, collection)
            validate_source_connectivity(db, collection.source_id)
            validate_no_conflicting_operations(db, collection_id)

            # Phase 2: Execute ingest
            result = execute_collection_ingest(db, collection, filters)

            # Phase 3: Post-operation validation
            validate_no_orphaned_records(db)
            validate_all_relationships(db, result.created_entities)
            validate_business_rules(db, result)

            return result

        except Exception as e:
            logger.error("collection_ingest_failed", collection_id=collection_id, error=str(e))
            raise IngestError(f"Collection ingest failed: {e}")
```

#### Asset Processing Contract

```python
def process_discovered_item(discovered_item: DiscoveredItem, collection: Collection) -> AssetProcessingResult:
    """
    Process a single discovered item through the ingest pipeline.

    Pre-conditions:
    - DiscoveredItem is valid and complete
    - Collection exists and is accessible
    - All required enrichers are available

    Post-conditions:
    - Asset is created with proper relationships
    - All enrichers have been applied
    - No duplicate assets exist
    - Hierarchy is properly maintained

    Atomicity:
    - If any step fails, entire asset processing rolls back
    - If enricher fails, entire asset processing rolls back
    - If validation fails, entire asset processing rolls back
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            validate_discovered_item(discovered_item)
            validate_collection_accessible(db, collection)
            validate_enrichers_available(db, collection)

            # Phase 2: Execute processing
            result = execute_asset_processing(db, discovered_item, collection)

            # Phase 3: Post-operation validation
            validate_asset_relationships(db, result.asset)
            validate_hierarchy_integrity(db, result)
            validate_no_duplicates(db, result.asset)

            return result

        except Exception as e:
            logger.error("asset_processing_failed", asset_path=discovered_item.path_uri, error=str(e))
            raise AssetProcessingError(f"Asset processing failed: {e}")
```

### Wipe Operations

#### Collection Wipe Contract

```python
def wipe_collection(collection_id: str, options: WipeOptions) -> WipeResult:
    """
    Completely wipe a collection and all associated data.

    Pre-conditions:
    - Collection exists
    - No conflicting operations in progress
    - All dependencies are identified

    Post-conditions:
    - All collection data is deleted
    - No orphaned records exist
    - Collection and path mappings are preserved
    - Database state is consistent

    Atomicity:
    - If any deletion step fails, entire operation rolls back
    - If any validation fails, entire operation rolls back
    - If any constraint violation occurs, entire operation rolls back
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            collection = validate_collection_exists(db, collection_id)
            validate_no_conflicting_operations(db, collection_id)
            validate_wipe_prerequisites(db, collection)

            # Phase 2: Execute wipe
            result = execute_collection_wipe(db, collection, options)

            # Phase 3: Post-operation validation
            validate_no_orphaned_records(db)
            validate_collection_preserved(db, collection)
            validate_path_mappings_preserved(db, collection)
            validate_database_consistency(db)

            return result

        except Exception as e:
            logger.error("collection_wipe_failed", collection_id=collection_id, error=str(e))
            raise WipeError(f"Collection wipe failed: {e}")
```

## Error Handling

### Error Types

1. **ValidationError**: Pre-flight validation failed
2. **ConstraintError**: Database constraint violation
3. **BusinessRuleError**: Business rule violation
4. **ResourceError**: Resource not available
5. **OperationError**: General operation failure

### Error Response

All errors MUST:

- Log detailed error information
- Roll back the transaction
- Provide clear error messages
- Preserve database consistency

## Testing Requirements

### Unit Tests

- Test pre-flight validation
- Test post-operation validation
- Test error handling and rollback
- Test atomicity guarantees

### Integration Tests

- Test complete operation workflows
- Test failure scenarios and recovery
- Test concurrent operation handling
- Test database consistency

### Contract Tests

- Verify all operations follow the contract
- Verify all validation rules are enforced
- Verify all error conditions are handled
- Verify all atomicity guarantees are met

## Implementation Guidelines

### 1. Use Context Managers

Always use the `session()` context manager:

```python
with session() as db:
    # All database operations
    # Automatic commit/rollback
```

### 2. Validate Early and Often

- Validate inputs before starting
- Validate state before each major step
- Validate results before committing

### 3. Fail Fast

- Stop at the first validation failure
- Don't continue if prerequisites aren't met
- Provide clear error messages

### 4. Log Everything

- Log operation start and parameters
- Log each major step
- Log validation results
- Log errors with full context

## See Also

- [Collection Wipe](../resources/CollectionWipeContract.md)
- [Ingest pipeline](../../domain/IngestPipeline.md)
- [Data model](../../data-model/README.md)
- [Unit of Work implementation](../../../src/retrovue/infra/uow.py)






