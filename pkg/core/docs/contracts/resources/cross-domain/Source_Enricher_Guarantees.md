# Source ↔ Enricher Cross-Domain Guarantees

## Overview

This document defines the guarantees and constraints that govern interactions between the Source domain and the Enricher domain. These guarantees ensure that source creation, validation, and lifecycle management maintain consistency when enrichers are attached to sources.

The Source-Enricher relationship is critical because:

- Sources define content ingestion pipelines
- Enrichers provide metadata enhancement capabilities
- Both domains must coordinate for successful content processing
- Failure in either domain must maintain transactional integrity

---

## Participating Domains

### Source Domain

- **Contract:** `docs/contracts/resources/SourceAddContract.md`
- **Interface:** Source creation, validation, and lifecycle management
- **Responsibilities:** Source persistence, configuration validation, external ID generation

### Enricher Domain

- **Contract:** `docs/contracts/resources/EnricherAddContract.md`, `docs/contracts/resources/EnricherListTypesContract.md`
- **Interface:** Enricher discovery, validation, and lifecycle management
- **Responsibilities:** Enricher registry, capability validation, metadata processing

---

## Cross-Domain Guarantees

### G-1: Enricher Registry Validation

**Any enricher attached to a Source MUST exist in the enricher registry before source creation.**

- The enricher registry is an in-memory enumeration of available enricher implementations and their stable identifiers. It is not persisted state.
- Source creation MUST validate all specified enrichers against the enricher registry
- Unknown enrichers MUST cause source creation to fail with exit code 1
- Enricher validation MUST occur before any database operations
- CLI MUST emit clear error message: "Error: Unknown enricher '{name}'. Available: {list}"
- **Multiple unknown enrichers MUST all be reported before failing** - the command MUST NOT fail fast on the first unknown enricher, but MUST validate all enrichers and report all unknown ones

### G-2: Enricher-Source Compatibility

**Only enrichers compatible with the source's importer type MAY be linked.**

- Enricher compatibility MUST be validated against the source's importer type
- Incompatible enrichers MUST cause source creation to fail with exit code 1
- Compatibility validation MUST occur after enricher registry validation
- CLI MUST emit clear error message: "Error: Enricher '{name}' is not compatible with '{type}' sources"

### G-3: Transactional Integrity

**If enrichment initialization fails, the Source transaction MUST roll back completely.**

- Source creation and enricher attachment MUST occur within a single transaction boundary
- This transaction boundary MUST follow the UnitOfWork contract (per-command, no partial persistence, rollback on failure)
- Any failure in enricher validation or initialization MUST roll back all pending database changes
- Partial source creation MUST NOT be permitted
- Transaction rollback MUST be atomic and complete

### G-4: Enricher Configuration Validation

**Enricher configuration MUST be validated before source persistence.**

- Enricher configuration parameters MUST be validated against enricher schema
- Invalid enricher configuration MUST cause source creation to fail with exit code 1
- Configuration validation MUST occur before database persistence
- CLI MUST emit clear error message: "Error: Invalid configuration for enricher '{name}'"

---

## Planned Guarantees / Future Governance Scope

The following guarantees are intended but are not yet enforced in CI. They become enforceable once SourceRemoveContract and SourceUpdateContract exist.

### G-5: Enricher Lifecycle Coordination (Non-Enforced Guidance)

**Enricher lifecycle MUST be coordinated with source lifecycle.**

- Source deletion MUST handle enricher cleanup appropriately
- Enricher updates MUST not break existing source configurations
- Source updates MUST validate enricher compatibility changes
- Lifecycle coordination MUST maintain referential integrity

---

## Failure & Rollback Policy

### Exit Code Guarantees

- **Validation failures** (unknown enricher, incompatible enricher, invalid configuration) MUST exit with code 1
- **System/transaction failures** MUST exit with code 1 unless a different exit code is explicitly documented in SourceAddContract

### Transaction Failure Handling

1. **Enricher Registry Failure**: Source creation MUST fail immediately with exit code 1
2. **Compatibility Failure**: Source creation MUST fail immediately with exit code 1
3. **Configuration Failure**: Source creation MUST fail immediately with exit code 1
4. **Database Failure**: All pending changes MUST be rolled back atomically

### Partial Failure Prevention

- **No Partial Creation**: Source creation is all-or-nothing
- **Atomic Rollback**: Database rollback MUST be complete and immediate
- **State Consistency**: System state MUST remain consistent after any failure
- **Error Isolation**: Enricher failures MUST not affect other system components

### Error Message Standards

- **Registry Errors**: "Error: Unknown enricher '{name}'. Available: {list}"
- **Compatibility Errors**: "Error: Enricher '{name}' is not compatible with '{type}' sources"
- **Configuration Errors**: "Error: Invalid configuration for enricher '{name}'"
- **System Errors**: "Error adding source: {specific_error_message}"

---

## Enforcement

### Test Coverage

- **Test File**: `tests/contracts/cross-domain/test_source_enricher_guarantees.py`
- **Coverage**: Enforced guarantees G-1 through G-4 (G-5 is planned but not yet enforced)
- **Test Types**: Unit tests, integration tests, failure scenario tests
- **Mocking**: Enricher registry, database transactions, error conditions

### CI Integration

- **CI Step**: CrossDomainContracts enforcement
- **Command**: `pytest tests/contracts/cross-domain/ --maxfail=1 --disable-warnings -q`
- **Failure Policy**: Any cross-domain test failure MUST block PR merge
- **Coverage**: All cross-domain guarantees MUST be tested

### Contract Dependencies

- **SourceAddContract**: References this guarantee in "Dependencies" section
- **EnricherAddContract**: References this guarantee in "Dependencies" section
- **EnricherListTypesContract**: References this guarantee in "Dependencies" section

---

## Versioning & Change Coordination

### Version Coordination

- **Minor Changes**: Both Source and Enricher contracts may bump minor versions independently
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
- **Schema Evolution**: Enricher schemas MUST support backward-compatible evolution
- **Migration Path**: Breaking changes MUST provide clear migration paths

---

## Examples

### Valid Source Creation with Enrichers

```bash
# Valid: All enrichers exist and are compatible
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token" \
  --enrichers "ffprobe,metadata"
```

### Invalid Enricher Registry

```bash
# Invalid: Unknown enricher
retrovue source add --type plex --name "My Plex" \
  --base-url "http://plex:32400" --token "token" \
  --enrichers "unknown-enricher"
# Exit code: 1
# Error: Unknown enricher 'unknown-enricher'. Available: ffprobe, metadata
```

### Invalid Enricher Compatibility

```bash
# Invalid: Incompatible enricher
retrovue source add --type filesystem --name "My Files" \
  --base-path "/media" \
  --enrichers "plex-metadata"  # Only works with Plex sources
# Exit code: 1
# Error: Enricher 'plex-metadata' is not compatible with 'filesystem' sources
```

---

## See Also

- [SourceAddContract](../SourceAddContract.md) - Source creation contract
- [EnricherAddContract](../EnricherAddContract.md) - Enricher creation contract
- [EnricherListTypesContract](../EnricherListTypesContract.md) - Enricher discovery contract
- [UnitOfWorkContract](../../_ops/UnitOfWorkContract.md) - Transaction management contract
