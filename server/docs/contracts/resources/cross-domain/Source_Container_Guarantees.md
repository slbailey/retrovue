# Source ↔ Container Cross-Domain Guarantees (formerly Source–Collection)

## Overview

This document defines the guarantees and constraints that govern interactions between the Source domain and the **Container** domain (contract entity: Source → Container → Locator → Media/Asset). These guarantees ensure that source operations, container discovery, and lifecycle management maintain consistency when sources manage containers.

The Source–Container relationship is critical because:

- Sources define content ingestion pipelines that discover and manage containers
- Containers represent subdivisions of a source used for discovery (e.g. library section, folder)
- Both domains must coordinate for successful content discovery and ingestion
- Container lifecycle must be synchronized with source lifecycle

### Interaction Summary

The lifecycle of Source–Container operations follows this pattern:

1. **User runs `retrovue source add --discover`** → Command parsing and validation
2. **Source domain creates Source entity** → Source persistence with transaction boundary
3. **Source invokes container discovery service** → Container enumeration via importer
4. **Container domain persists discovered containers** → Containers created with `enabled=False` by default
5. **Source commits transaction** → Atomic completion of source and container creation

This flow ensures that source operations maintain consistency with container state while providing clear orchestration boundaries between domains.

---

## Participating Domains

### Source Domain

- **Contract:** `docs/contracts/resources/SourceAddContract.md`, `docs/contracts/resources/SourceDiscoverContract.md`, `docs/contracts/resources/SourceIngestContract.md`
- **Interface:** Source creation, discovery, and ingestion operations
- **Responsibilities:** Source persistence, container discovery, external ID generation

### Container Domain (contract term; code/DB may still use "Collection" until later phases)

- **Contract:** `docs/contracts/resources/ContainerContract.md`, Container Ingest (see ContainerIngestContract.md)
- **Interface:** Container management, ingestion, and lifecycle operations
- **Responsibilities:** Container persistence, ingestibility validation, sync management

---

## Cross-Domain Guarantees

### G-1: Container Discovery Coordination

**Container discovery MUST be coordinated between Source and Container domains.**

- Source discovery operations MUST create Container records with proper domain mapping
- Collection discovery MUST occur within the same transaction as source operations when using `--discover`
- Newly discovered collections MUST be persisted with `enabled=False` by default
- Collection external IDs MUST be unique within the source context

### G-2: Collection Lifecycle Synchronization

**Collection lifecycle MUST be synchronized with source lifecycle.**

- Source deletion MUST handle collection cleanup appropriately
- Source updates MUST validate collection compatibility changes
- Collection updates MUST not break existing source configurations
- Lifecycle coordination MUST maintain referential integrity

### G-3: Collection Ingestibility Validation

**Collection ingestibility MUST be validated before source ingestion operations.**

- Source ingestion MUST only operate on collections with `sync_enabled=true` AND `ingestible=true`
- Collection ingestibility MUST be re-validated before each ingestion operation
- Invalid collection states MUST cause source ingestion to fail with appropriate error codes
- CLI MUST emit clear error message: "Error: Collection '{name}' is not ingestible"

### G-4: Transactional Integrity

**Collection operations MUST maintain transactional integrity with source operations.**

- Collection discovery and source creation MUST occur within a single transaction boundary
- Collection ingestion and source ingestion MUST maintain atomicity per collection
- Any failure in collection operations MUST roll back appropriately
- Transaction rollback MUST be atomic and complete

### G-5: Collection State Consistency

**Collection state MUST remain consistent across source operations.**

- Collection state changes MUST be persisted atomically
- Collection state MUST be validated before source operations
- State inconsistencies MUST be detected and reported
- System state MUST remain consistent after any failure

### G-6: Collection Path Mapping Coordination

**Collection path mappings MUST be coordinated between domains.**

- Each newly discovered Collection MUST create a corresponding PathMapping record with local_path=NULL until explicitly resolved
- Path mappings MUST be created for all discovered collections
- Updates to PathMapping MUST remain synchronized with Collection state transitions (enabled, ingestible, sync_enabled)
- Path mapping consistency MUST be maintained across operations

---

## Failure & Rollback Policy

### Transaction Failure Handling

1. **Discovery Failure**: Source creation MUST fail immediately with exit code 1
2. **Collection Failure**: Collection operations MUST fail with appropriate error codes
3. **Ingestibility Failure**: Source ingestion MUST fail with exit code 1
4. **State Failure**: Operations MUST fail with exit code 1
5. **Database Failure**: All pending changes MUST be rolled back atomically

### Partial Failure Prevention

- **Per-Collection Atomicity**: Each collection operation MUST be atomic
- **Source-Level Orchestration**: Source operations MUST handle partial collection failures gracefully
- **Atomic Rollback**: Database rollback MUST be complete and immediate
- **State Consistency**: System state MUST remain consistent after any failure

### Error Message Standards

- **Discovery Errors**: "Error: Failed to discover collections from source '{name}'"
- **Ingestibility Errors**: "Error: Collection '{name}' is not ingestible"
- **State Errors**: "Error: Collection '{name}' is in invalid state"
- **System Errors**: "Error: {operation} failed: {specific_error_message}"

### Exit Code Semantics

| Exit Code | Meaning         | Example Scenario                                        |
| --------- | --------------- | ------------------------------------------------------- |
| 0         | Success         | All collections discovered/ingested successfully        |
| 1         | Failure         | Discovery error, ingestibility error, or system failure |
| 2         | Partial success | Some collections succeeded, others failed               |

---

## Enforcement

### Test Coverage

- **Test File**: `tests/contracts/cross-domain/test_source_collection_guarantees.py`
- **Coverage**: All guarantees G-1 through G-6
- **Test Types**: Unit tests, integration tests, failure scenario tests
- **Mocking**: Collection persistence, path mapping, error conditions

### CI Integration

- **CI Step**: CrossDomainContracts enforcement
- **Command**: `pytest tests/contracts/cross-domain/ --maxfail=1 --disable-warnings -q`
- **Failure Policy**: Any cross-domain test failure MUST block PR merge
- **Coverage**: All cross-domain guarantees MUST be tested
- **Enforcement**: CI MUST fail if any test in `tests/contracts/cross-domain/` fails validation for guarantees G-1 through G-6

### Contract Dependencies

- **SourceAddContract**: References this guarantee in "Dependencies" section
- **SourceDiscoverContract**: References this guarantee in "Dependencies" section
- **SourceIngestContract**: References this guarantee in "Dependencies" section
- **ContainerContract**: References this guarantee in "Dependencies" section
- **ContainerIngestContract**: References this guarantee in "Dependencies" section

---

## Versioning & Change Coordination

### Version Coordination

- **Minor Changes**: Source and Collection contracts may bump minor versions independently
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
- **Schema Evolution**: Collection schemas MUST support backward-compatible evolution
- **Migration Path**: Breaking changes MUST provide clear migration paths

---

## Examples

### Valid Source Creation with Collection Discovery

```bash
# Valid: Source creation with collection discovery
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token" \
  --discover
# Success: Source created, collections discovered and persisted with enabled=False
```

### Valid Source Ingestion with Enabled Collections

```bash
# Valid: Source ingestion with enabled collections
retrovue source ingest "My Plex"
# Success: Only collections with sync_enabled=true AND ingestible=true are processed
```

### Invalid Collection State

```bash
# Invalid: Collection not ingestible
retrovue source ingest "My Plex"
# Exit code: 1
# Error: Collection 'Movies' is not ingestible
```

### Collection Discovery Failure

```bash
# Invalid: Collection discovery fails
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token" \
  --discover
# Exit code: 1
# Error: Failed to discover collections from source 'My Plex'
```

### Partial Collection Ingestion Failure

```bash
# Partial: Some collections fail, others succeed
retrovue source ingest "My Plex"
# Exit code: 2 (partial success)
# Success: Collections 'Movies', 'TV Shows' ingested
# Failed: Collection 'Music' failed ingestion
```

---

## See Also

- [SourceAddContract](../SourceAddContract.md) - Source creation contract
- [SourceDiscoverContract](../SourceDiscoverContract.md) - Source discovery contract
- [SourceIngestContract](../SourceIngestContract.md) - Source ingestion contract
- [ContainerContract](../ContainerContract.md) - Container management contract
- [ContainerIngestContract](../ContainerIngestContract.md) - Container ingestion contract
- [UnitOfWorkContract](../../_ops/UnitOfWorkContract.md) - Transaction management contract

---

## Traceability

- **Tests:** `tests/contracts/cross-domain/test_source_collection_guarantees.py`
- **Dependencies:** SourceAddContract, SourceDiscoverContract, SourceIngestContract, ContainerContract, ContainerIngestContract
- **Last Audit:** 2025-10-28
