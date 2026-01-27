# Enricher Contract

## Purpose

Define the observable guarantees for the Enricher domain in RetroVue. This contract specifies **what** enrichers guarantee, not how they are implemented.

---

## Scope

The Enricher domain is covered by the following operation contracts:

- **[Enricher List Types](EnricherListTypesContract.md)**: Listing available enricher types
- **[Enricher Add](EnricherAddContract.md)**: Creating new enricher instances
- **[Enricher List](EnricherListContract.md)**: Listing configured enricher instances
- **[Enricher Update](EnricherUpdateContract.md)**: Updating enricher configurations
- **[Enricher Remove](EnricherRemoveContract.md)**: Removing enricher instances

---

## Design Principles

- **Type-based operation**: Enrichers operate as either ingest or playout types
- **Stateless design**: Enrichers are pure functions that don't maintain state
- **Priority ordering**: Enrichers are applied in priority order to resolve conflicts
- **Graceful failure**: Enricher failures don't block ingestion or playout
- **Test mode support**: All operations support `--dry-run` and `--test-db` modes

---

## Core Guarantees

### EN-010: Type Validation

**Guarantee:** Enrichers are validated by type before use.

**Observable behavior:**
- Invalid enricher type → error
- Enricher type determines valid attachment targets
- Type mismatch prevents misconfiguration

---

### EN-011: Configuration Validation

**Guarantee:** Enricher configuration validated before persistence.

**Observable behavior:**
- Invalid configuration → error with descriptive message
- Configuration schema enforced per enricher type
- Database unchanged on validation failure

---

### EN-020: Graceful Failure

**Guarantee:** Individual enricher failures don't block operations.

**Observable behavior:**
- Enricher failure logged but operation continues
- Per-enricher failure isolation
- Partial success possible in batch operations

---

### EN-030: Metadata Domains

**Guarantee:** Enrichers write to designated metadata domains only.

| Enricher Type | Target Domain |
|---------------|---------------|
| Technical (ffprobe) | `probed` |
| Editorial (TMDB, IMDB) | `editorial` |
| Station/packaging | `station_ops` |

**Observable behavior:**
- Enricher does not overwrite domains it doesn't own
- Existing values in target domain are merged (not replaced)
- `sidecar` field preserved unless explicitly extended

---

### EN-031: Metadata Merge Behavior

**Guarantee:** Metadata updates use merge semantics.

**Observable behavior:**
- Deep merge for nested objects
- Last-writer-wins for scalar values
- No data loss from overwrites

---

## Common Safety Patterns

All Enricher operations follow these patterns:

| Pattern | Behavior |
|---------|----------|
| Type validation | Enricher type verified before operation |
| Config validation | Configuration validated before persistence |
| Error isolation | Single enricher failure doesn't block others |
| Dry-run support | All operations support `--dry-run` |
| Test-db support | All operations support `--test-db` |

---

## Test Coverage

Each Enricher operation has two test files:

| Test Type | File Pattern |
|-----------|--------------|
| CLI Contract | `tests/contracts/test_enricher_{verb}_contract.py` |
| Data Contract | `tests/contracts/test_enricher_{verb}_data_contract.py` |

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| EN-010 | Type validation before use |
| EN-011 | Configuration validation before persistence |
| EN-020 | Graceful failure isolation |
| EN-030 | Metadata written to designated domains |
| EN-031 | Merge semantics for metadata updates |

---

## See Also

- [Source Contract](SourceContract.md) — source-level operations using enrichers
- [CLI Contract](README.md) — general CLI command standards
- [Contract Hygiene Checklist](../../../standards/contract-hygiene.md) — authoring guidelines
