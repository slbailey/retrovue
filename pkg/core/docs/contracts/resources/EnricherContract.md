# Enricher Contract

## Purpose

This document provides an overview of all Enricher domain testing contracts. Individual Enricher operations are covered by specific behavioral contracts that define exact CLI syntax, safety expectations, and data effects.

---

## Scope

The Enricher domain is covered by the following specific contracts:

- **[Enricher List Types](EnricherListTypesContract.md)**: Listing available enricher types
- **[Enricher Add](EnricherAddContract.md)**: Creating new enricher instances
- **[Enricher List](EnricherListContract.md)**: Listing configured enricher instances
- **[Enricher Update](EnricherUpdateContract.md)**: Updating enricher configurations
- **[Enricher Remove](EnricherRemoveContract.md)**: Removing enricher instances

---

## Contract Structure

Each Enricher operation follows the standard contract pattern:

1. **Command Shape**: Exact CLI syntax and required flags
2. **Safety Expectations**: Confirmation prompts, dry-run behavior, force flags
3. **Output Format**: Human-readable and JSON output structure
4. **Exit Codes**: Success and failure exit codes
5. **Data Effects**: What changes in the database and registry
6. **Behavior Contract Rules (B-#)**: Operator-facing behavior guarantees
7. **Data Contract Rules (D-#)**: Persistence, lifecycle, and integrity guarantees
8. **Test Coverage Mapping**: Explicit mapping from rule IDs to test files

---

## Design Principles

- **Type-based operation**: Enrichers operate as either ingest or playout types
- **Stateless design**: Enrichers are pure functions that don't maintain state
- **Priority ordering**: Enrichers are applied in priority order to resolve conflicts
- **Graceful failure**: Enricher failures don't block ingestion or playout
- **Test mode support**: All operations support `--dry-run` and `--test-db` modes

---

## Common Safety Patterns

All Enricher contracts follow these safety patterns:

### Type Validation

- Enrichers are identified by their type (ingest or playout)
- Type validation prevents misconfiguration
- Different types have different attachment targets

### Configuration Management

- Each enricher type defines its own configuration schema
- Configuration validation before persistence
- Type-specific parameter validation

### Error Handling

- Graceful failure handling with detailed error messages
- Per-enricher failure isolation
- Fallback behavior for failed enrichments

---

## EnricherInterface Specification

All enrichers MUST implement the `Enricher` protocol:

```python
class Enricher(Protocol):
    name: str

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with additional metadata."""
        ...
```

### Method Responsibilities

- **enrich()**: Transforms input objects by adding metadata
- **Type Declaration**: Enrichers are identified by their type (ingest or playout)
- **Configuration Schema**: Each enricher type defines its configuration requirements

### Configuration Schema

Enricher-specific configuration is stored in the Enricher `config` field:

```json
{
  "ffprobe_path": "/usr/bin/ffprobe",
  "timeout": 30,
  "sources": ["imdb", "tmdb"]
}
```

---

## Metadata domains

E-10. Enrichers MUST NOT overwrite domains they don’t own.

- If an enricher provides **technical** metadata (ffprobe), it MUST write to `probed`.
- If an enricher provides **editorial** metadata (e.g. TMDB), it MUST write to `editorial`.
- If an enricher provides station-level or packaging metadata, it MUST write to `station_ops`.

E-11. When an enricher attaches metadata to an item, and the item already has a value at that domain,
the enricher MUST perform a deep merge (object/object recursive merge, last-writer-wins on scalars)
instead of replacement.

E-12. Enrichers MUST leave `sidecar` intact unless they specifically extend it. (Sidecar is the canonical
merge surface for importer + enrichers.)

---

## Contract Test Requirements

Each Enricher contract must have exactly two test files:

1. **CLI Contract Test**: `tests/contracts/test_enricher_{verb}_contract.py`

   - CLI syntax validation
   - Flag behavior verification
   - Output format validation
   - Error message handling

2. **Data Contract Test**: `tests/contracts/test_enricher_{verb}_data_contract.py`
   - Database state changes
   - Registry state changes
   - Configuration validation
   - Error propagation validation

---

## See Also

- [Enricher Domain Documentation](../../domain/Enricher.md) - Core domain model and operations
- [Enricher Development Guide](../../developer/Enricher.md) - Implementation details and development guide
- [Source Contracts](SourceContract.md) - Source-level operations that use enrichers
- [CLI Contract](README.md) - General CLI command standards
