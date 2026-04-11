# Source ↔ Importer Cross-Domain Guarantees

## Overview

This document defines the guarantees and constraints that govern interactions between the Source domain and the Importer domain. These guarantees ensure that source creation, validation, and lifecycle management maintain consistency when sources depend on importer implementations.

The Source-Importer relationship is fundamental because:

- Sources define content ingestion pipelines that depend on importer implementations
- Importers provide the actual content discovery and retrieval capabilities
- Both domains must coordinate for successful source operations
- Importer interface compliance is critical for source functionality

### Data Flow Summary

The lifecycle of Source-Importer operations follows this pattern:

1. **Source emits raw structured data** → Source domain provides content metadata and configuration
2. **Importer consumes and transforms the data** → Importer domain normalizes data into internal format
3. **Validation errors or missing fields trigger compensating events** → Error handling and rollback coordination
4. **Importer provides deterministic, one-to-one reference mapping** → Source ID correlation for lineage tracking

This flow ensures that source operations maintain consistency with importer capabilities while providing clear data transformation boundaries between domains.

---

## Participating Domains

### Source Domain

- **Contract:** `docs/contracts/resources/SourceAddContract.md`, `docs/contracts/resources/SourceDiscoverContract.md`, `docs/contracts/resources/SourceIngestContract.md`
- **Interface:** Source creation, discovery, and ingestion operations
- **Responsibilities:** Source persistence, configuration validation, external ID generation

### Importer Domain

- **Contract:** `docs/domain/Importer.md`
- **Interface:** Content discovery, validation, and retrieval capabilities
- **Responsibilities:** Importer registry, interface compliance, content enumeration

---

## Cross-Domain Guarantees

### G-1: Importer Registry Validation

**Any source type MUST correspond to a discovered importer in the importer registry.**

- Source creation MUST validate source type against available importers
- Unknown source types MUST cause source creation to fail with exit code 1
- Importer registry validation MUST occur before any database operations
- CLI MUST emit clear error message: "Error: Unknown source type '{type}'. Available types: {list}"

### G-2: Source Type Compliance

**All source types MUST be valid and supported by the system.**

- Source operations MUST verify source type is supported before proceeding
- Unsupported source types MUST cause operations to fail with exit code 1
- Source type validation MUST occur before any database operations
- CLI MUST emit clear error message: "Error: Source type '{type}' is not supported"
- Every imported entity must include a deterministic, one-to-one reference to its originating Source ID. The mapping must be immutable and verifiable through the import metadata model

### G-3: Configuration Schema Validation

**Source configuration MUST be validated against the source type's configuration schema.**

- Source configuration MUST be valid for the specified source type
- Invalid configuration MUST cause source creation to fail with exit code 1
- Configuration validation MUST occur before database persistence
- CLI MUST emit clear error message: "Error: Invalid configuration for source type '{type}'"

### G-4: Importer Capability Validation

**Source operations MUST respect importer capability declarations.**

- Discovery operations MUST only be attempted if importer declares discovery capability
- Ingestion operations MUST only be attempted if importer declares enumeration capability
- Capability validation MUST occur before attempting domain-specific operations
- CLI MUST emit clear error message: "Error: Importer '{type}' does not support {capability}"

### G-5: Transactional Integrity

**Importer failures MUST maintain transactional integrity across source operations.**

- Source creation and importer validation MUST occur within a single transaction boundary
- Any failure in importer validation or initialization MUST roll back all pending database changes
- Partial source creation MUST NOT be permitted
- Transaction rollback MUST be atomic and complete

### G-6: Importer Lifecycle Coordination

**Importer lifecycle MUST be coordinated with source lifecycle.**

- Source deletion MUST handle importer cleanup appropriately
- Importer updates MUST not break existing source configurations
- Source updates MUST validate importer compatibility changes
- Lifecycle coordination MUST maintain referential integrity

---

## Failure & Rollback Policy

### Transaction Failure Handling

1. **Registry Failure**: Source creation MUST fail immediately with exit code 1
2. **Interface Failure**: Source creation MUST fail immediately with exit code 1
3. **Configuration Failure**: Source creation MUST fail immediately with exit code 1
4. **Capability Failure**: Source operations MUST fail immediately with exit code 1
5. **Database Failure**: All pending changes MUST be rolled back atomically

### Partial Failure Prevention

- **No Partial Creation**: Source creation is all-or-nothing
- **Atomic Rollback**: Database rollback MUST be complete and immediate
- **State Consistency**: System state MUST remain consistent after any failure
- **Error Isolation**: Importer failures MUST not affect other system components
- **Intermediate State Observability**: Imports in progress must surface as an observable intermediate state (import_pending) that prevents downstream consumers from assuming completion

### Error Message Standards

- **Type Errors**: "Error: Unknown source type '{type}'. Available types: {list}"
- **Support Errors**: "Error: Source type '{type}' is not supported"
- **Configuration Errors**: "Error: Invalid configuration for source type '{type}'"
- **Capability Errors**: "Error: Source type '{type}' does not support {capability}"
- **System Errors**: "Error adding source: {specific_error_message}"

---

## Enforcement

### Test Coverage

- **Test File**: `tests/contracts/cross-domain/test_source_importer_guarantees.py`
- **Coverage**: All guarantees G-1 through G-6
- **Test Types**: Unit tests, integration tests, failure scenario tests
- **Mocking**: Importer registry, interface compliance, error conditions
- **Status**: Tests not yet created (CI enforcement pending)

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
- **Importer.md**: References this guarantee in "Cross-Domain Dependencies" section

---

## Versioning & Change Coordination

### Version Coordination

- **Minor Changes**: Source and Importer contracts may bump minor versions independently
- **Major Changes**: Cross-domain guarantee changes require coordination between domains
- **Breaking Changes**: Must be coordinated across all participating domains
- **Synchronized Updates**: Minor version updates to Importer contracts that alter accepted Source fields require synchronized minor updates to Source contract schema. Major changes require an approved cross-domain version bump

### Change Process

1. **Impact Assessment**: Evaluate impact on cross-domain guarantees
2. **Contract Updates**: Update relevant domain contracts
3. **Guarantee Updates**: Update this cross-domain guarantee document
4. **Test Updates**: Update cross-domain test suite
5. **Migration**: Update `CONTRACT_MIGRATION.md` status

### Backward Compatibility

- **Interface Stability**: Cross-domain interfaces MUST maintain backward compatibility
- **Schema Evolution**: Importer schemas MUST support backward-compatible evolution
- **Migration Path**: Breaking changes MUST provide clear migration paths

---

## Examples

### Valid Source Creation with Compliant Importer

```bash
# Valid: Importer exists and is interface compliant
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token"
# Success: Source created with compliant Plex importer
```

### Invalid Source Type

```bash
# Invalid: Unknown source type
retrovue source add --type unknown --name "My Source" \
  --base-url "http://test" --token "token"
# Exit code: 1
# Error: Unknown source type 'unknown'. Available types: plex, filesystem
```

### Unsupported Source Type

```bash
# Invalid: Unsupported source type
retrovue source add --type broken --name "My Source" \
  --base-url "http://test" --token "token"
# Exit code: 1
# Error: Source type 'broken' is not supported
```

### Invalid Configuration

```bash
# Invalid: Configuration doesn't match source type schema
retrovue source add --type plex --name "My Plex" \
  --invalid-param "value"
# Exit code: 1
# Error: Invalid configuration for source type 'plex'
```

### Unsupported Capability

```bash
# Invalid: Importer doesn't support discovery
retrovue source add --type filesystem --name "My Files" \
  --base-path "/media" --discover
# Exit code: 1
# Error: Importer 'filesystem' does not support discovery
```

---

## See Also

- [SourceAddContract](../SourceAddContract.md) - Source creation contract
- [SourceDiscoverContract](../SourceDiscoverContract.md) - Source discovery contract
- [SourceIngestContract](../SourceIngestContract.md) - Source ingestion contract
- [Importer.md](../../../domain/Importer.md) - Importer domain documentation
- [UnitOfWorkContract](../../_ops/UnitOfWorkContract.md) - Transaction management contract

---

## Traceability

- **Tests:** `tests/contracts/cross-domain/test_source_importer_guarantees.py`
- **Dependencies:** SourceAddContract, SourceDiscoverContract, SourceIngestContract, Importer.md
- **Last Audit:** 2025-10-28
