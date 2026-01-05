_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Contracts](../contracts/resources/README.md) • [Source](Source.md) • [Collection](Collection.md)_

# Domain — Importer

## Purpose

Importer defines the conceptual domain for content discovery and ingestion from external media systems. Importers bridge the gap between external content sources (Plex, filesystem, etc.) and RetroVue's internal content management system by implementing standardized discovery, validation, and ingestion operations.

Importers are **modular and extensible** - they can be developed by third parties without modifying core RetroVue code. Importers are discovered at runtime through a registry — a runtime collection of available importer implementations. The registry is responsible for mapping stable type identifiers (like plex, filesystem) to importer classes.

### Importer vs Source

An **Importer** is code. A **Source** is a configured instance of that Importer type (with credentials, base URLs, etc.) stored in the database and referenced by `source_id`. Operators interact with Sources through `retrovue source ....` Importers are never configured directly; they are discovered at runtime through the registry.

## Core model / scope

Importer is implemented as an abstract interface (`ImporterInterface`) that defines the contract for all content importers. Each importer type (Plex, filesystem, etc.) implements this interface with source-specific logic for:

- **Collection Discovery**: Enumerating content libraries from external sources
- **Prerequisites Validation**: Verifying that collections can be ingested
- **Content Ingestion**: Extracting metadata and producing normalized asset descriptions that become Asset records

The interface ensures consistent behavior across all importer types while allowing source-specific implementations.

### Registry vs CLI Architecture

**Registry Responsibility**: The registry is responsible for enumerating importer identifiers (simple names like "plex", "filesystem") and maintaining the mapping from identifiers to importer classes.

**CLI Responsibility**: The CLI is responsible for resolving those identifiers into structured output and validating interface compliance. Interface compliance is enforced at CLI time, not registry time.

This separation provides:

- **Clean boundaries**: Registry handles discovery, CLI handles presentation and validation
- **Flexibility**: Registry can be simple, CLI can add rich metadata and validation
- **Testability**: Easier to test individual components in isolation

## Contract / interface

### ImporterInterface and BaseImporter

At the domain level, an Importer is defined by its ability to:

- verify a collection can be ingested,
- enumerate available collections,
- drive ingestion of a collection (full or partial), and
- resolve a local URI to enrich/play content from the discovered source URI.

**ImporterInterface** is the required runtime contract that RetroVue orchestration calls.

**BaseImporter** is an abstract base class that implements most of that interface and enforces safety, and first-party importers MUST subclass it.

Third-party importers SHOULD subclass it, but if they don't, they MUST still satisfy ImporterInterface or they'll be rejected at runtime.

Orchestration may call these behaviors at different granularities. For the developer-facing method signatures and CLI wiring (including `get_config_schema()`, filtering by title/season/episode, etc.), see the [Importer Development Guide](../developer/Importer.md).

All importers MUST implement the `ImporterInterface` protocol, including URI resolution:

```python
class ImporterInterface(Protocol):
    name: str

    @classmethod
    def get_config_schema(cls) -> ImporterConfig: ...

    def discover(self) -> list[DiscoveredItem]: ...

    def get_help(self) -> dict[str, any]: ...

    def list_asset_groups(self) -> list[dict[str, any]]: ...

    def enable_asset_group(self, group_id: str) -> bool: ...

    def disable_asset_group(self, group_id: str) -> bool: ...

    def resolve_local_uri(
        self, item: DiscoveredItem | dict, *, collection: Any | None = None, path_mappings: list[tuple[str, str]] | None = None
    ) -> str: ...
```

**Dual-URI Responsibility:**

- Importer returns a stable, source-native `source_uri` for each discovered item (e.g., `plex://12345`, `file:///...`).
- Importer implements `resolve_local_uri(...)` to convert that discovered item into a local `file://` canonical URI using `PathMapping` and any upstream lookups required.
- Ingest persists both URIs: `source_uri` (unchanged) and `canonical_uri` (normalized local URI). Enrichers run against `canonical_uri`.

### Interface Responsibility Boundaries

The `ImporterInterface` defines three distinct responsibility areas with different operational characteristics:

**Discovery Operations** (Side-effect-free):

- `discover()`: Enumerate available collections from external sources
- `list_asset_groups()`: List asset groups within collections
- These operations MUST NOT modify external systems or database state

**Validation Operations** (Side-effect-free):

- `get_config_schema()`: Declare configuration requirements
- `get_help()`: Provide usage information
- These operations MUST NOT perform external system calls or database modifications

**Control/Resolution Operations**:

- `resolve_local_uri(...)`: Resolve a discovered item to a local `file://` URI for enrichment/playout
- `enable_asset_group()` / `disable_asset_group()`: Modify collection state
- These operations operate within Unit of Work boundaries and MUST NOT persist directly to authoritative tables

**Critical Invariant**: Importers MUST NOT directly persist to authoritative tables. They return normalized data; the ingest service handles persistence within controlled Unit of Work boundaries.

### Prerequisites Validation

The `validate_ingestible()` method determines whether a collection can be ingested based on importer-specific requirements:

- **Plex Importer**: Validates that path mappings exist and are resolvable
- **Filesystem Importer**: Validates that directory paths exist and are accessible
- **Future Importers**: Will implement their own prerequisite validation logic

### Collection Discovery

Importers must expose a **discovery capability** that enumerates available content libraries from external sources:

- **Plex Importer**: Queries Plex API for available libraries
- **Filesystem Importer**: Scans directory structure for content collections
- **Future Importers**: Will implement their own discovery mechanisms

### Content Ingestion

Importers must expose an **enumeration capability** that extracts content metadata and returns canonicalized asset descriptions to the ingest service. The ingest service is responsible for creating Asset records in the database inside a Unit of Work. Newly ingested assets MUST enter the system in a known lifecycle state (e.g. `new`, `enriching`). Importers MUST NOT persist directly to authoritative tables.

- **Scope Support**: Handles full collection, title, season, or episode-level ingestion
- **Metadata Extraction**: Extracts title, season, episode, duration, and file information
- **Asset Normalization**: Returns canonicalized asset descriptions in RetroVue's unified format
- **Duplicate Prevention**: Implements duplicate detection logic

**Important:** The importer DOES NOT directly persist to authoritative tables. The importer returns discovered/normalized assets. The ingest service, running under a Unit of Work, is what commits the data to the database.

## Contract-driven behavior

All importer operations are defined by behavioral contracts that specify exact CLI syntax, safety expectations, output formats, and data effects. The contracts ensure:

- **Safety first**: No destructive operations run against live data during automated tests
- **Atomicity**: Each ingest operation for a given collection MUST run inside a transaction (Unit of Work). If ingest for that collection fails, it MUST roll back cleanly without affecting other collections in the same source ingest run.
- **Idempotence**: Operations can be safely repeated without side effects
- **Audit trails**: All operations tracked for debugging and compliance

### Key Contract Requirements

- **Prerequisites Validation**: `ingestible` field MUST be validated before any ingest operation
- **Collection Discovery**: New collections MUST be created with `sync_enabled=false`
- **Asset Normalization**: Importers MUST return canonicalized asset descriptions, not persist directly
- **Error Handling**: Per-asset failures MUST NOT abort the entire ingest operation. Importers MUST raise typed errors for asset-level failures; orchestration is responsible for catching, logging, and continuing

## Implementation patterns

### Modular Architecture

Importers are developed as independent files in the `adapters/importers/` directory:

```
adapters/importers/
├── plex_importer.py        # Source type: "plex"
├── filesystem_importer.py  # Source type: "filesystem"
├── jellyfin_importer.py   # Source type: "jellyfin"
└── custom_importer.py     # Source type: "custom"
```

### Importer Naming Convention

Each importer file MUST follow the naming pattern `{source_type}_importer.py`:

- **`plex_importer.py`** → Source type: `"plex"`, Class: `PlexImporter`
- **`filesystem_importer.py`** → Source type: `"filesystem"`, Class: `FilesystemImporter`
- **`jellyfin_importer.py`** → Source type: `"jellyfin"`, Class: `JellyfinImporter`
- **`custom_importer.py`** → Source type: `"custom"`, Class: `CustomImporter`

### Registry Integration

Importers are exposed through a runtime registry with clear separation of responsibilities:

- **Runtime Discovery**: Registry scans `adapters/importers/` directory for `*_importer.py` files
- **Identifier Enumeration**: Registry returns simple importer identifiers (strings like "plex", "filesystem")
- **Class Mapping**: Registry maintains mapping from identifiers to importer classes
- **Dynamic Loading**: Importers loaded on-demand when needed
- **Interface Validation**: CLI validates `ImporterInterface` implementation at runtime, not registry time

**Registry does NOT:**

- Validate interface compliance
- Build rich metadata objects
- Perform complex validation logic

**CLI does:**

- Resolve identifiers to classes
- Validate interface compliance
- Build structured output with status and compliance information

### Configuration Management

Importer-specific configuration is stored in the Source `config` field:

```json
{
  "servers": [{ "base_url": "https://plex.example.com", "token": "***" }],
  "enrichers": ["ffprobe", "metadata"]
}
```

## Operator workflows

### Source Management

- **Add source**: `retrovue source add --type plex --name "My Plex Server" --discover`
- **Discover collections**: `retrovue source discover "My Plex Server"`
- **Validate prerequisites**: `retrovue collection show "TV Shows"` (shows `ingestible` status)

The list of valid `--type` values is provided at runtime by the Importer registry and surfaced to operators via `retrovue source list-types`.

### Collection Operations

- **Bulk ingest**: `retrovue source ingest "My Plex Server"` (processes all `sync_enabled=true` AND `ingestible=true` collections)
- **Targeted ingest**: `retrovue collection ingest "TV Shows" --title "The Simpsons" --season 1`

### Prerequisites Validation

- **Check ingestibility**: `retrovue collection show <collection_id>` shows `ingestible` field
- **Validate path mappings**: Plex importer validates that `plex_path` → `local_path` mappings are resolvable
- **Test connectivity**: Importers validate external system accessibility

## Key execution patterns

### Discovery Workflow

1. **Importer Discovery**: Registry scans `adapters/importers/` directory for `*_importer.py` files
2. **Identifier Enumeration**: Registry returns simple importer identifiers (e.g., ["plex", "filesystem"])
3. **Source Creation**: Source created with `type` field referencing an importer identifier
4. **CLI Processing**: CLI resolves identifiers to classes and validates interface compliance
5. **Collection Discovery**: Importer's discovery capability called to enumerate libraries
6. **Prerequisites Validation**: `validate_ingestible()` called for each collection
7. **Collection Persistence**: Collections created with `sync_enabled=false`, `ingestible=<validation_result>`

### Ingest Workflow

1. **Collection Selection**: Collections filtered by `sync_enabled=true` AND `ingestible=true`
2. **Prerequisites Revalidation**: `validate_ingestible()` called before ingest
3. **Content Extraction**: Importer's enumeration capability called with appropriate scope
4. **Asset Creation**: The ingest service writes Assets into the database in `new` or `enriching` state, using the normalized data returned by the importer
5. **Audit Logging**: Ingest results tracked for debugging and compliance

### Error Handling

- **Per-asset failures**: Individual asset failures do not abort collection ingest
- **Collection failures**: Individual collection failures do not abort source ingest; each collection operates in its own transaction boundary
- **Fatal errors**: Fatal errors (database constraints, external system unreachable) abort the specific collection operation
- **Transaction rollback**: Each collection ingest wrapped in its own Unit of Work for per-collection atomicity

## Business rules

### Importer Lifecycle

- **Discovery**: Importers discovered at runtime from filesystem
- **Identifier Enumeration**: Registry returns simple identifiers, CLI handles validation
- **Interface Validation**: CLI validates `ImporterInterface` implementation at runtime
- **Configuration**: Each importer declares its configuration requirements via `get_config_schema()`
- **Availability**: Importers immediately available when files exist

### Source Type Mapping

- **Automatic Derivation**: Source type derived from filename pattern
- **Unique Mapping**: Each source type maps to exactly one importer
- **Conflict Resolution**: Multiple importers claiming same source type cause registration failure

### Content Processing

- **Normalization**: All content normalized into RetroVue's unified model
- **Stable Identification**: External IDs preserved for incremental operations
- **Metadata Extraction**: Title, season, episode, duration extracted consistently
- **Duplicate Prevention**: Duplicate detection prevents redundant processing
- **No Direct Persistence**: Importers return normalized data; ingest service handles persistence

### Safety and Isolation

- **Test Mode Support**: All operations support `--dry-run` and `--test-db` modes
- **Non-Destructive Discovery**: Discovery operations never mutate external systems
- **Error Isolation**: Per-asset failures isolated from bulk operations
- **Transaction Boundaries**: Each collection ingest operates within its own Unit of Work for per-collection atomicity
- **Importer as Infrastructure**: Importers are infrastructure components; ingest service owns persistence authority

## Cross-references

- **Importer registry** – Runtime collection of available importer implementations and their identifiers
- **[Source Contracts](../contracts/resources/SourceContract.md)** - Source-level operations that use importers
- **[Collection Contracts](../contracts/resources/CollectionContract.md)** - Collection-level operations that use importers
- **[Unit of Work](../contracts/_ops/UnitOfWorkContract.md)** - Transaction management for importer operations
- **[CLI Contract](../contracts/resources/README.md)** - General CLI command standards
- **[Source Domain](Source.md)** - Source entity model and relationships
- **[Collection Domain](Collection.md)** - Collection entity model and relationships
- **[Developer Guide](../developer/Importer.md)** - Implementation details and development guide

## Contract Alignment

Importer contracts must maintain backward-compatible CLI behavior across migrations. Changes to interface signatures or discovery semantics require a corresponding update to the [CONTRACT_MIGRATION.md](../../tests/CONTRACT_MIGRATION.md) document.

**Migration Requirements:**

- **Interface Changes**: Any modification to `ImporterInterface` methods must be reflected in contract documentation
- **Discovery Semantics**: Changes to discovery behavior must update corresponding Source contracts
- **Validation Logic**: Modifications to validation requirements must align with Collection contracts
- **Test Coverage**: All interface changes must include corresponding contract test updates

This ensures importer evolution is formally tied to the global contract lifecycle and maintains backward compatibility for operators.

## Contract test requirements

All importer operations MUST have comprehensive test coverage following the contract test responsibilities in [README.md](../contracts/resources/README.md). Tests MUST:

- **Validate registry enumeration**: Test that registry returns simple identifiers correctly
- **Validate CLI processing**: Test that CLI correctly resolves identifiers and validates interface compliance
- **Test discovery**: Verify importer's discovery capability returns expected results
- **Test ingestion**: Verify importer's enumeration capability returns normalized asset data
- **Test error handling**: Verify graceful handling of external system failures
- **Test atomicity**: Verify per-collection Unit of Work behavior for all operations
- **Test idempotence**: Verify operations can be safely repeated

Each test MUST reference specific contract rule IDs to provide bidirectional traceability between contracts and implementation.

## Domain Integrity

The Importer domain operates within a larger system where each domain knows what it owns. The following table maps importer responsibilities to their enforcement and testing:

| Behavior             | Defined in      | Enforced by               | Tested by                                |
| -------------------- | --------------- | ------------------------- | ---------------------------------------- |
| Discovery            | Importer domain | Source contracts          | `test_source_discover_contract.py`       |
| Validation           | Importer domain | Collection contracts      | `test_collection_validation_contract.py` |
| Ingestion            | Importer domain | UnitOfWork contracts      | `test_source_ingest_contract.py`         |
| Registry Enumeration | Importer domain | SourceListTypes contracts | `test_source_list_types_contract.py`     |
| Interface Compliance | Importer domain | All Source contracts      | Contract validation tests                |

**Cross-Domain Dependencies:**

- **Importer registry**: Runtime list of importer implementations and their stable identifiers; no persistence; no validation; no operator-facing output
- **Source Domain**: Uses importers for collection discovery and ingestion
- **Collection Domain**: Validates importer prerequisites and manages collection state
- **UnitOfWork Domain**: Ensures atomicity for importer operations
- **CLI Contracts**: Enforce interface compliance and output formatting

This reinforces the "each domain knows what it owns" philosophy that underpins the architecture.
