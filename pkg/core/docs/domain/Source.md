_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Contracts](../contracts/resources/SourceContract.md)_

# Domain — Source

## Purpose

Source defines a persistent content discovery entity that connects to external media systems (Plex, filesystem) and manages collections of content libraries. Sources provide the foundation for content discovery and ingestion workflows.

## Core model / scope

Source is managed by SQLAlchemy with the following fields:

- **id** (UUID, primary key): Internal identifier for relational joins and foreign key references
- **external_id** (String(255), required, unique): External system identifier (e.g., "plex-abc123", "filesystem-def456")
- **name** (String(255), required): Human-facing source label used in UI and operator tooling
- **type** (String(50), required): Source type identifier ("plex", "filesystem", etc.)
- **config** (JSON, nullable): Source-specific configuration including connection details and enrichers
- **created_at** (DateTime(timezone=True), required): Record creation timestamp
- **updated_at** (DateTime(timezone=True), required): Record last modification timestamp

The table is named `sources` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

Source has relationships with SourceCollection through foreign key constraints with cascade deletion.

## Operational State and Readiness

Each `Source` owns zero or more `Collection` records.

Two boolean fields on each Collection define ingest readiness:

- `sync_enabled`:

  - Meaning: Operator intent.
  - `true` means "this Collection should be synchronized / ingested by the system."
  - `false` means "this Collection is known to the system but not currently scheduled for ingestion."

- `ingestible`:
  - Meaning: System safety/eligibility.
  - `true` means "this Collection is currently safe/eligible to ingest (prereqs satisfied, path mappings valid, credentials valid, etc.)."
  - `false` means "do not attempt ingest for this Collection."

A Source's ingest posture can be summarized by counting its Collections:

- `enabled_collections`: Number of Collections for that Source where `sync_enabled == true`.
- `ingestible_collections`: Number of Collections for that Source where `ingestible == true`.

These counts are reported by operator-facing commands such as `retrovue source list`. Those commands MAY read and summarize these values but MUST NOT silently change them. Only the appropriate lifecycle commands are allowed to mutate `sync_enabled` or `ingestible`.

These fields are authoritative system state. They are not derived heuristics at display time; they are persisted on each Collection.

## Contract / interface

SourceCollection represents individual content libraries within a source (e.g., Plex libraries, filesystem directories). Collections are automatically discovered when Plex sources are created and can be enabled/disabled individually.

SourceCollection fields:

- **id** (UUID, primary key): Internal identifier
- **source_id** (UUID, foreign key): Reference to parent Source
- **external_id** (String(255), required): External system identifier (e.g., Plex library key)
- **name** (String(255), required): Human-readable collection name
- **enabled** (Boolean, required, default=False): Whether collection is active for content discovery
- **config** (JSON, nullable): Collection-specific configuration
- **created_at** (DateTime(timezone=True), required): Record creation timestamp

PathMapping provides path translation between external systems and local storage:

- **id** (UUID, primary key): Internal identifier
- **collection_id** (UUID, foreign key): Reference to parent SourceCollection
- **plex_path** (String(500), required): External system path
- **local_path** (String(500), required): Local filesystem path

## Contract-driven behavior

All Source operations are defined by behavioral contracts that specify exact CLI syntax, safety expectations, output formats, and data effects. The contracts ensure:

- **Safety first**: No destructive operations run against live data during automated tests
- **One contract per operation**: Each Source operation has its own focused contract
- **Test isolation**: All operations support `--test-db` for isolated testing
- **Idempotent operations**: Source operations are safely repeatable
- **Clear error handling**: Failed operations provide clear diagnostic information

Key contract patterns:

- `--test-db` flag directs operations to isolated test environment
- `--dry-run` flag shows what would be performed without executing
- Confirmation prompts for destructive operations (with `--force` override)
- JSON output format for automation and machine consumption
- Atomic transactions with rollback on failure

For complete behavioral specifications, see the [Source Contracts](../contracts/resources/SourceContract.md).

---

## Execution model

SourceService manages source lifecycle and collection discovery. When a Plex source is created with `--discover`, collections are automatically discovered and persisted with `enabled=False` by default.

IngestOrchestrator consumes enabled collections to discover content for ingestion workflows. Source-level ingest operations orchestrate multiple collection ingests, with each collection ingest following atomic transaction boundaries.

**Key execution patterns:**

- Source creation triggers automatic collection discovery for Plex sources only when `--discover` is provided
- Collection discovery creates SourceCollection records with `enabled=False`
- PathMapping records are created with empty `local_path` for operator configuration
- Source ingest iterates over all collections that are both `sync_enabled=true` AND ingestible (reachable/valid path mappings)
- Each collection ingest operates within its own atomic transaction
- Individual collection failures do not abort the entire source ingest operation

## Failure / fallback behavior

If source connections fail, the system logs errors and continues with available sources. Collections with invalid paths are marked as not ingestable.

**Contract-driven failure handling:**

- Source deletion requires confirmation unless `--force` is provided
- **PRODUCTION SAFETY**: Sources with assets in PlaylogEvent or AsRunLog cannot be deleted in production, even with `--force`
- Collection discovery failures are logged but do not abort source creation
- Individual collection ingest failures do not abort the entire source ingest operation
- All operations support `--test-db` for isolated testing and `--dry-run` for preview operations
- Transaction rollback occurs on any fatal error, ensuring no partial state changes

## Operator workflows

**Create Plex source**: Use `retrovue source add --type plex` with required parameters. Collections are automatically discovered and persisted with `enabled=False` only when `--discover` is provided:

```bash
# Create source without collection discovery
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token"

# Create source with collection discovery
retrovue source add --type plex --name "My Plex Server" \
  --base-url "https://plex.example.com" --token "your-token" --discover
```

**Create filesystem source**: Use `retrovue source add --type filesystem` with required parameters:

```bash
retrovue source add --type filesystem --name "Media Library" \
  --base-path "/media/movies"
```

**List sources**: Use `retrovue source list` to see all sources, or `retrovue source list --json` for machine-readable output. _(Contract: Planned)_

**Show source details**: Use `retrovue source show "Source Name"` to see detailed source information including configuration and enrichers. _(Contract: Planned)_

**Update source**: Use `retrovue source update "Source Name"` with new parameters to modify source configuration. _(Contract: Planned)_

**Discover collections**: Use `retrovue source discover "Source Name"` to discover and add collections from external sources. New collections are created with `enabled=False` by default.

**Ingest source**: Use `retrovue source ingest "Source Name"` to process all enabled and ingestible collections within a source. This orchestrates individual collection ingests and provides aggregated results. **Note**: Source ingest is bulk-only and does not support collection-level narrowing flags like `--title`, `--season`, or `--episode`. For targeted ingest, use `retrovue collection ingest <collection_id> [--title ... --season ... --episode ...]`.

**Attach enrichers**: Use `retrovue source attach-enricher "Source Name" <enricher_id> --priority <n>` to attach enrichers to all collections in a source. _(Contract: Planned)_

**Detach enrichers**: Use `retrovue source detach-enricher "Source Name" <enricher_id>` to remove enrichers from all collections in a source. _(Contract: Planned)_

**Delete source**: Use `retrovue source delete "Source Name"` (with confirmation) or `retrovue source delete "Source Name" --force` to permanently remove source and all related collections and path mappings. **PRODUCTION SAFETY**: Sources with assets in PlaylogEvent or AsRunLog cannot be deleted in production, even with `--force`.

All operations support identification by name, UUID, or external ID. The CLI provides both human-readable and JSON output formats. All operations support `--test-db` for isolated testing and `--dry-run` for preview operations.

## Bulk / wildcard operations on Sources

Operators MAY issue bulk actions against multiple sources using wildcard-style identifiers.

The source_id argument in destructive commands (such as `retrovue source delete`) MAY be:

- a specific source identifier (UUID, external_id, or exact name)
- a wildcard pattern (e.g. "test-_" or "_\_temp")
- the special token "\*" meaning "all matching sources"

Wildcard matching is performed against name and external_id. It does not guess or fuzzy-match. Pattern rules MUST be documented in the contract for that command.

Wildcard deletion is primarily intended for cleanup of non-production / test data sets (for example, tearing down dozens of throwaway sources created during development or automated testing). It exists to prevent operator fatigue and manual loops.

**PRODUCTION SAFETY**: Production safety rules still apply. A source that cannot be deleted under production rules (for example, any source whose assets appear in PlaylogEvent or AsRunLog) MUST NOT be deleted even if it matches a wildcard. `--force` MUST NOT override this behavior.

A bulk delete that partially succeeds MUST still run inside a transaction per source (not one global transaction across all matches). Each source delete is atomic, consistent with the normal single-source delete contract.

**Operational intent:**

- Wildcards are allowed to accelerate cleanup of safe / disposable sources.
- Wildcards do not grant new powers to violate production safety guarantees.
- In production, protected sources MUST survive, even if other matched sources are removed.

## Ownership and Destructive Removal

A Source is the root of authority for its Collections.

Every Collection belongs to exactly one Source.

A Source MAY be deleted by an operator (including via wildcard).

When a Source is deleted, all Collections that belong to that Source MUST also be deleted as part of the same operation.

Collections are, in turn, the owner of ingested Assets. Long-term, deleting a Collection will also delete all of its Assets and any Asset-related metadata rows. That rule will be enforced at the Collection boundary.

Today, Source-level deletion is responsible for removing its Collections. Collection → Asset cascade will be enforced as the Asset schema and metadata tables stabilize.

## Naming rules

The canonical name for this concept in code and documentation is Source.

- **Operator-facing noun**: `source` (humans type `retrovue source ...`)
- **Internal canonical model**: `Source`
- **Database table**: `sources` (plural)
- **CLI commands**: Use names, UUIDs, or external IDs for source identification
- **Code and docs**: Always refer to the persisted model as `Source`

Source is always capitalized in internal docs. external_id uses format "type-hash" (e.g., "plex-abc123"). Collections are automatically discovered for Plex sources and start disabled by default.

## See also

- [Source Contracts](../contracts/resources/SourceContract.md) - Complete behavioral contracts for all Source operations
- [Collection](Collection.md) - Content library management
- [Ingest pipeline](IngestPipeline.md) - Content discovery workflow
- [Asset](Asset.md) - Media file management
- [Collection Ingest](../contracts/resources/CollectionIngestContract.md) - Collection-level ingest operations
