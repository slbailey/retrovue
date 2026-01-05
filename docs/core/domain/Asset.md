_Related: [Collection](Collection.md) • [Source](Source.md) • [Scheduling](Scheduling.md) • [Ingest Pipeline](IngestPipeline.md)_

# Domain — Asset

## Purpose

Asset is the atomic unit of broadcastable content in RetroVue. It bridges ingestion, enrichment, and playout by defining a consistent, canonical representation of every piece of media. Assets are the foundation of RetroVue's content lifecycle and the single source of truth for anything that can air.

## Core model / scope

### Primary key / identity fields

- **uuid** (UUID, primary key): Primary identifier serving as the spine connecting all asset-related tables

### Canonical identity fields

- **canonical_key** (Text, required): Deterministic string identifying the asset within its collection (used for duplicate detection)
- **canonical_key_hash** (String(64), required): SHA256 hash of canonical_key, stored for efficient lookups
- **collection_uuid** (UUID, foreign key): Reference to the Collection this asset belongs to

**Uniqueness constraint**: `(collection_uuid, canonical_key_hash)` - Only one asset per canonical key per collection

### Required fields

- **source_uri** (Text, required): Source-native locator for the asset
  - Examples: `plex://12345`, `file:///mnt/media/movies/Airplane (1980).mkv`, `smb://MEDIA/share/show.mkv`
  - Persistence: Set by the importer at ingest time and never rewritten by core logic
- **canonical_uri** (Text, required): Canonical, locally-resolvable URI used by enrichers and playout
  - Derived at ingest time by resolving `source_uri` to a source path, then mapping via `PathMapping`
  - Examples: `file:///r:/media/tv/S01E01.mp4`, `file:///mnt/media/tv/S01E01.mp4`
- **size** (BigInteger, required): File size in bytes
- **state** (Enum, required): Lifecycle state (`new`, `enriching`, `ready`, `retired`)
- **discovered_at** (DateTime(timezone=True), required): When the asset was first discovered during ingest

### Approval / broadcast readiness fields

- **approved_for_broadcast** (Boolean, required, default=False): Runtime gating flag for schedulers and playout
  - Invariant: `true` requires `state='ready'` (enforced by database constraint)
  - Used by ScheduleService to determine available content
  - Set by operators via `asset resolve --approve`
- **operator_verified** (Boolean, required, default=False): Reserved for future multi-tier review processes distinct from broadcast approval

### Soft delete fields

- **is_deleted** (Boolean, required, default=False): Soft delete flag for content lifecycle management
- **deleted_at** (DateTime(timezone=True), nullable): When the asset was soft deleted

### Technical metadata fields

- **duration_ms** (Integer, nullable): Asset duration in milliseconds
- **video_codec** (String(50), nullable): Video codec information
- **audio_codec** (String(50), nullable): Audio codec information
- **container** (String(50), nullable): Container format


### Change tracking fields

- **last_enricher_checksum** (String(64), nullable): Reserved for future automatic enricher change detection
- **created_at** (DateTime(timezone=True), required, auto-generated): When asset record was created
- **updated_at** (DateTime(timezone=True), required, auto-generated): Last modification timestamp

### Relationships

Asset has relationships with:

- **Collection** (via `collection_uuid` foreign key): The collection this asset belongs to
- **Episode** (via `episode_assets` junction table): Many-to-many relationship with episodes (planned/WIP)
- **ProviderRef**: External system references (Plex rating keys, etc.)
- **Marker**: Chapters, availability windows, and other asset markers
- **ReviewQueue**: Items requiring human review for quality assurance

### Indexes

Asset table includes indexes on:

- `ix_assets_collection_uuid` on `collection_uuid`
- `ix_assets_state` on `state`
- `ix_assets_approved` on `approved_for_broadcast`
- `ix_assets_operator_verified` on `operator_verified`
- `ix_assets_discovered_at` on `discovered_at`
- `ix_assets_is_deleted` on `is_deleted`
- `ix_assets_collection_canonical_unique` **unique** on `(collection_uuid, canonical_key_hash)`
- `ix_assets_collection_source_uri_unique` **unique** on `(collection_uuid, source_uri)`
- `ix_assets_collection_canonical_uri` on `(collection_uuid, canonical_uri)`
- `ix_assets_schedulable` **partial** on `(collection_uuid, discovered_at)` where `state='ready' AND approved_for_broadcast=true AND is_deleted=false` (hot path for schedulers)

The table is named `assets` (plural). Schema migration is handled through Alembic. Postgres is the authoritative backing store.

## Contract / interface

### Lifecycle states

Assets progress through four distinct states:

1. **`new`**: Recently discovered, minimal metadata, awaiting processing
2. **`enriching`**: Undergoing enrichment by metadata services
3. **`ready`**: Fully processed, operator-approved, available for scheduling
4. **`retired`**: No longer available for broadcast

Procedural lifecycle control keeps the ingest and enrichment pipeline predictable and transparent. State transitions are enforced by ingest and enricher services.

### Asset Lifecycle

#### Asset State Transition Table


| **From State** | **Action**                   | **To State** | **Notes**                      |
|:-------------- |:---------------------------- |:------------ |:------------------------------ |
| `new`          | Enrichment begins            | `enriching`  | Automatic during ingest        |
| `enriching`    | Operator resolves and        | `ready`      | via `asset resolve --approve`  |
|                | approves                     |              | `--ready`                      |
| `ready`        | Operator retires asset       | `retired`    | via update/delete operations   |
| *any*          | Soft delete                  | —            | Marks `is_deleted=true`        |



### Critical invariants

- Check constraint: `chk_approved_implies_ready` enforces that `approved_for_broadcast=true` requires `state='ready'`
- Check constraint: `chk_deleted_at_sync` ensures `is_deleted` and `deleted_at` are synchronized
- Check constraint: `chk_canon_hash_len` enforces canonical key hash length of 64 characters
- Check constraint: `chk_canon_hash_hex` enforces canonical key hash is hexadecimal
- Unique constraint: `ix_assets_collection_canonical_unique` on `(collection_uuid, canonical_key_hash)` prevents duplicate assets
- Unique constraint: `ix_assets_collection_source_uri_unique` on `(collection_uuid, source_uri)` prevents duplicate source URIs per collection
- Newly ingested assets may be created as `ready` with `approved_for_broadcast=true` when
  confidence ≥ `auto_ready_threshold`; otherwise they enter as `new` or `enriching` per the
  Asset Confidence contract
- Every asset belongs to exactly one collection via `collection_uuid`

### Canonical key system

Assets are uniquely identified within a collection using canonical keys:

- **Canonical Key**: Deterministic string generated by `canonical_key_for()`
  - Normalizes `canonical_uri` (e.g., `file:/media/movie.mp4`)
  - Uses `provider_key` or `external_id` when available
  - Includes collection identifier
- **Canonical Hash**: SHA256 hash of canonical key, stored as `canonical_key_hash`
  - Enables efficient lookups and duplicate detection
  - Enforces uniqueness: `(collection_uuid, canonical_key_hash)`
- **Key Generation**: Handled by ingest service via `src/retrovue/infra/canonical.py`

**Normalization Rules**:
- Windows paths: `C:\path\to\file.mkv` → `/c/path/to/file.mkv`
- UNC paths: `\\SERVER\share\file.mkv` → `//SERVER/share/file.mkv` (server name preserved)
- URIs: `file:///path/to/file.mkv` → normalized scheme://host/path (host lowercased)
- Paths are lowercased and trailing slashes removed

### Duplicate detection

Assets are identified by canonical identity within a collection:

- **Canonical Identity**: Determined by importer via `canonical_key_for()`
- **Uniqueness**: One asset per canonical identity (enforced by unique constraint on `collection_uuid, canonical_key_hash`)
- **Duplicate Resolution**: Matching canonical key hash during collection ingest results in a SKIP (no mutation). Updates are performed by a separate `asset update` command (pending).

**Content Change Detection**:

- Full-file hashing MUST NOT be performed during ingest.
- Change detection uses lightweight fingerprints such as `(size_bytes, mtime_ns)` and
  optional media probe signatures (e.g., codec/container/duration tuples) or importer-provided
  version tokens/etags. Implementations SHOULD avoid any O(file_size) operations on ingest paths.

**Enricher Change Detection**:

- Reserved for future enrichment improvements
- Checksum-based reprocessing will automatically detect configuration changes

## Contract-driven behavior

All Asset operations are defined by behavioral contracts that specify exact CLI syntax, safety expectations, output formats, and data effects. The contracts ensure:

- **Safety first**: No destructive operations run against live data during automated tests
- **One contract per operation**: Each Asset operation has its own focused contract
- **Test isolation**: All operations support `--test-db` for isolated testing
- **Idempotent operations**: Asset operations are safely repeatable
- **Clear error handling**: Failed operations provide clear diagnostic information

Key contract patterns:

- `--test-db` flag directs operations to isolated test environment
- `--dry-run` flag shows what would be performed without executing
- Confirmation prompts for destructive operations (with `--force` override)
- JSON output format for automation and machine consumption
- Atomic transactions with rollback on failure

### CLI operations

**Implemented**:
- `retrovue asset attention` — List assets needing operator attention _(Contract: [Asset Attention](../contracts/resources/AssetAttentionContract.md))_
- `retrovue asset resolve <uuid>` — Approve and/or mark asset ready _(Contract: [Asset Resolve](../contracts/resources/AssetResolveContract.md))_

**Planned**:
- `retrovue asset show <uuid>` — Display detailed asset information _(Contract: [Asset Show](../contracts/resources/AssetShowContract.md))_
- `retrovue asset list` — List assets with filtering options _(Contract: [Asset List](../contracts/resources/AssetListContract.md))_
- `retrovue asset update <uuid>` — Update asset metadata and configuration _(Contract: [Asset Update](../contracts/resources/AssetUpdateContract.md))_
- `retrovue assets select` — Select assets by criteria _(Contract: [Assets Select](../contracts/resources/AssetsSelectContract.md))_
- `retrovue assets delete` — Delete assets _(Contract: [Assets Delete](../contracts/resources/AssetsDeleteContract.md))_

For complete behavioral specifications, see the [Asset Contracts](../contracts/resources/AssetContract.md).

---

## Execution model

IngestService creates and manages asset lifecycle during collection ingest. EnricherService processes assets through the enrichment pipeline. ScheduleService queries ready, approved assets for scheduling via ProgramEpisode creation.

**Key execution patterns:**

- Ingest creates Asset records in `new` or `enriching` state and does not update existing records
- Enrichers attach metadata, validate content, set state to `enriching`
- Operators review via `asset attention` and approve via `asset resolve --approve --ready`
- ScheduleService queries for `state='ready' AND approved_for_broadcast=true AND is_deleted=false`
- Scheduling creates ProgramEpisode entries referencing assets; PlaylogEvents generated from ProgramEpisodes for playback

**Note**: ScheduleService consumes ProgramEpisode entries, not Asset records directly. Playback follows PlaylogEvent → ProgramEpisode → Asset chain.

Pending: Asset modification flows (content/enricher state/approval changes) will be provided via a dedicated `asset update` command and associated contracts.

## Failure / fallback behavior

If assets fail discovery or processing, the system logs errors and continues with available assets. Invalid assets remain in `enriching` state or marked as `retired`. Missing or invalid ready assets trigger fallback to default programming or most recent valid content.

**Contract-driven failure handling:**

- **PRODUCTION SAFETY**: Hard deletes disabled in production; only soft deletes (`is_deleted=true`) permitted
- **PRODUCTION SAFETY**: Assets referenced by PlaylogEvent or AsRunLog cannot be deleted, even with `--force`
- Individual asset ingest failures do not abort collection ingest operation
- All operations support `--test-db` for isolated testing and `--dry-run` for preview operations
- Transaction rollback occurs on any fatal error, ensuring no partial state changes

## Operator workflows

**Discover and ingest assets**: Assets are automatically discovered during collection ingest operations. Use `retrovue collection ingest <collection_id>` for targeted collection ingest, or `retrovue source ingest <source_id>` for bulk ingest from all enabled collections in a source.

**Review assets needing attention**: Use `retrovue asset attention` to list assets needing operator attention. This shows assets in `enriching` state or not approved for broadcast.

**Approve assets for broadcast**: Use `retrovue asset resolve <uuid> --approve --ready` to approve and mark assets ready for scheduling. Only `ready` assets with `approved_for_broadcast=true` are eligible for scheduling. Enrichers do not automatically set `approved_for_broadcast=true`.

**Select assets** _(Contract: Planned)_: Use `retrovue assets select` with various criteria to select assets for operations. Supports filtering by UUID, title, series/season/episode hierarchy, and type.

**Delete assets** _(Contract: Planned)_: Use `retrovue assets delete <uuid>` to soft delete assets while preserving audit trail. Hard deletes disabled in production. Mark assets as `retired` to prevent scheduling without deleting.

## Future work

The current schema provides a solid foundation for upcoming enrichment and scheduling enhancements. Future iterations will add automatic enricher checksum validation using `last_enricher_checksum`.

## See also

- [Asset Contracts](../contracts/resources/AssetContract.md) - Complete behavioral contracts for all Asset operations
- [Collection](Collection.md) - Content groupings that contain assets
- [Source](Source.md) - Content sources that contain collections
- [Scheduling](Scheduling.md) - How ready assets become scheduled content
- [Ingest Pipeline](IngestPipeline.md) - Content discovery workflow
