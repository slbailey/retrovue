_Related: [CLI contract](../contracts/resources/README.md) • [Runtime: Channel manager](../runtime/ChannelManager.md) • [Domain: Source](../domain/Source.md)_

# Domain — Ingest pipeline

## Purpose

Define how external media becomes part of RetroVue's managed library. The ingest pipeline is responsible for enumerating sources, selecting which collections are eligible, creating asset records, enriching those records, and storing them in RetroVue.

**Critical Rule**: Assets created during ingest start in `state='new'` and progress through `enriching` → `ready` lifecycle states. Only assets in `ready` state are eligible for scheduling and playout.

## Core model / scope

Source is a configured external content provider (e.g. Plex, filesystem, Jellyfin).

A source is stored in the database after running `retrovue source add`.

Each source has:

- type (e.g. plex, filesystem, jellyfin)
- name (operator label)
- connection parameters (URL, API token, root path, etc.)

Sources are registered in the Source Registry. The registry supports:

- listing known source types (`retrovue source list-types`)
- creating instances (`retrovue source add`)
- listing configured instances (`retrovue source list`)
- updating and removing instances

A Collection (also called SourceCollection) is a logical library inside a Source.

Examples:

- Plex libraries such as "Movies", "TV Shows", "Kids Cartoons", "Adult"
- A filesystem subtree such as `/srv/media/cartoons`

Collections sit between Source and Asset. RetroVue ingests from Collections, not directly from the Source as a whole.

Each collection tracks:

- source_id (which Source it belongs to)
- display_name (e.g. "TV Shows")
- source_path (path or mount as reported by the Source, e.g. /media/TV)
- local_path (path RetroVue should actually read, e.g. R:\Media\TV or /mnt/plex/tv)
- sync_enabled (operator toggle; can only be enabled if collection is ingestible)
- ingestible (derived from path reachability; if false, sync cannot be enabled)

Operators can selectively ingest only certain collections. This prevents pulling e.g. adult content or personal footage.

Operators can map remote paths to local paths. Example: Plex reports /media/TV, but RetroVue must read R:\Media\TV. If no usable mapping is provided, the collection is marked not ingestible.

## Contract / interface

### Unit of Work Requirements

All ingest operations MUST follow the Unit of Work paradigm:

- **Atomicity**: All-or-nothing operation - either complete success or complete rollback
- **Pre-flight Validation**: Validate all prerequisites before making any changes
- **Post-operation Validation**: Verify database consistency after all changes
- **Transaction Isolation**: Run in a single database transaction
- **Error Handling**: Roll back on any failure and provide clear error messages

### Collection Ingest Contract

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

### Asset Processing Contract

```python
def process_asset(asset_data: AssetData, collection: Collection) -> AssetProcessingResult:
    """
    Process a single asset through the ingest pipeline.

    Pre-conditions:
    - AssetData is valid and complete
    - Collection exists and is accessible
    - All required enrichers are available

    Post-conditions:
    - Asset is created with state='new' and proper relationships
    - All enrichers have been applied
    - No duplicate assets exist
    - Hierarchy is properly maintained
    - Asset progresses through lifecycle states

    Atomicity:
    - If any step fails, entire asset processing rolls back
    - If enricher fails, entire asset processing rolls back
    - If validation fails, entire asset processing rolls back
    """
    with session() as db:
        try:
            # Phase 1: Pre-flight validation
            validate_asset_data(asset_data)
            validate_collection_accessible(db, collection)
            validate_enrichers_available(db, collection)

            # Phase 2: Execute processing
            result = execute_asset_processing(db, asset_data, collection)

            # Phase 3: Post-operation validation
            validate_asset_relationships(db, result.asset)
            validate_hierarchy_integrity(db, result)
            validate_no_duplicates(db, result.asset)
            validate_asset_lifecycle_state(db, result.asset)

            return result

        except Exception as e:
            logger.error("asset_processing_failed", asset_path=asset_data.file_path, error=str(e))
            raise AssetProcessingError(f"Asset processing failed: {e}")
```

AssetData is the raw data produced during ingest for a single media item.

The importer for a collection returns AssetData objects with basic fields:

- file path (as reported by the source)
- runtime/duration if known
- guessed title / series / season / episode
- any chapter/ad-break markers discovered

AssetData is then processed to create Asset records with `state='new'`, which are then enriched by ingest-scope enrichers and progress through the lifecycle states.

**AssetProcessingResult.asset** returns the newly created or updated Asset row (UUID, state, metadata) - this is the actual database entity, not a draft structure.

## Execution model

### Unit of Work Execution

The ingest orchestration MUST follow the Unit of Work pattern:

1. **Pre-flight Validation Phase**

   - Validate collection exists and is enabled
   - Validate path mappings are accessible
   - Validate source connectivity
   - Validate no conflicting operations
   - Validate all prerequisites are met

2. **Execution Phase**

   - Enumerate collections for a source
   - Process each collection atomically
   - Apply enrichers in priority order
   - Store results in database

3. **Post-operation Validation Phase**
   - Validate no orphaned records exist
   - Validate all relationships are correct
   - Validate business rules are satisfied
   - Validate database consistency

### Collection Processing

The ingest orchestration runs in this order:

1. Enumerate collections for a source.

   - `ImporterRegistry.list_collections(source_id)` calls the importer plugin and discovers libraries / folders / sections.
   - RetroVue persists those as Collection rows.

2. For each collection:

   - If sync_enabled is false, skip.
   - If collection is not ingestible (no valid local paths), skip.

3. Ingest that collection:
   - `ImporterRegistry.fetch_assets_for_collection(source_id, collection_id, local_path)` retrieves AssetData for that collection.
   - Each AssetData is processed to create Asset records with `state='new'`.
   - Assets are enriched by ingest enrichers attached to that collection (in priority order).
   - Enrichers can be attached at the source level (applies to all collections) or collection level (applies to specific collection).
   - Assets progress through lifecycle states (`new` → `enriching` → `ready`) as enrichers complete.
   - Only assets in `ready` state are eligible for scheduling and playout.

### TV Show Hierarchy Processing

For TV show collections, the system implements a complete hierarchy:

1. **Hierarchy Traversal**: The importer traverses the nested structure through shows → seasons → episodes to enumerate individual media files
2. **Database Creation**: Creates proper database relationships:
   - `Title` (TV show/series) with `kind="show"`
   - `Season` linked to the title
   - `Episode` linked to both title and season
   - `EpisodeAsset` junction table linking episodes to assets (in case multiple encodings of a single asset exists)
   - `Asset` representing the media file
3. **Metadata Population**: Populates series title, season number, episode number, and episode title from the source system's metadata
4. **Duplicate Detection**: Automatically detects duplicate assets by URI and skips both database insertion and review queuing for existing assets

This ensures that TV shows are properly structured in the database with full hierarchical relationships, enabling proper search and organization of content.

### Error Handling and Validation

#### Pre-flight Validation

Before any ingest operation begins, the system MUST validate:

- **Collection Validation**

  - Collection exists and is accessible
  - Collection is enabled for sync
  - Collection has valid path mappings
  - Collection is not locked by another operation

- **Source Validation**

  - Source is reachable and authenticated
  - Source has no connectivity issues
  - Source is not in maintenance mode

- **Resource Validation**
  - All required enrichers are available
  - Database has sufficient space
  - All dependencies are satisfied

#### Post-operation Validation

After ingest completion, the system MUST validate:

- **Data Integrity**

  - No orphaned records exist
  - All foreign key relationships are valid
  - All business rules are satisfied

- **Consistency Checks**
  - Asset counts match expected values
  - Hierarchy relationships are correct
  - No duplicate assets were created

#### Error Recovery

When errors occur:

- **Immediate Rollback**: All changes are rolled back automatically
- **Error Logging**: Detailed error information is logged
- **State Preservation**: Database is left in a consistent state
- **Clear Messaging**: User receives clear error messages

### Duplicate Asset Handling

The ingest pipeline includes robust duplicate detection to prevent redundant processing:

1. **Detection**: Assets are considered duplicates if they have the same URI (file path)
2. **Database Skip**: Duplicate assets are not inserted into the database again
3. **Review Skip**: Duplicate assets are not queued for review again, preventing unnecessary review queue entries
4. **Junction Creation**: If a duplicate asset is found, the system ensures the EpisodeAsset junction table is properly linked
5. **Logging**: Duplicate detection is logged with `duplicate_asset_skipped` and `duplicate_asset_processing_skipped` messages

This prevents the common issue where duplicate assets would be skipped from database insertion but still queued for review, leading to unnecessary review queue entries.

### Asset-Collection Relationships

Every asset maintains a direct relationship to its source collection via `collection_id`:

1. **New Ingest Process**:

   - Assets are created with `collection_id` set to the collection UUID
   - This enables efficient querying and deletion by collection
   - Supports proper cascade operations and cleanup

2. **Legacy Asset Handling**:

   - Existing assets without `collection_id` are identified via path mapping patterns
   - Path mappings provide fallback identification for pre-migration assets
   - Ensures backward compatibility during transition period

3. **Collection Deletion**:

   - Assets can be efficiently located using `collection_id` queries
   - Hierarchy cleanup follows proper order: review queue → episode-assets → assets → orphaned episodes → orphaned seasons → orphaned titles
   - **IMPORTANT**: Path mappings and collection itself are preserved for re-ingest

4. **Data Integrity**:
   - Foreign key constraints ensure referential integrity
   - Cascade deletes handle orphaned relationships
   - UUID-based relationships provide stable references across operations

## Collection Lifecycle Management

Collections support a complete lifecycle from creation to deletion:

### Creation and Discovery

- Collections are discovered from sources via `retrovue source discover`
- Path mappings are configured to make collections ingestible
- Collections can be enabled/disabled for sync

### Ingest Operations

- Individual collections can be ingested via `retrovue collection ingest`
- Full source ingest processes all enabled collections
- Selective ingest supports title/season/episode filtering

### Maintenance and Cleanup

- **Soft Delete**: `retrovue collection delete` removes collection and path mappings
- **Complete Wipe**: `retrovue collection wipe` removes ALL associated data:
  - All assets, episodes, seasons, and titles
  - All review queue entries and catalog entries
  - All path mappings and the collection itself
- **Fresh Start**: Wipe + re-discover + re-ingest provides complete reset

### Safety and Recovery

- All destructive operations require confirmation (unless `--force`)
- Dry-run mode shows what would be affected before making changes
- Transaction safety ensures atomic operations (all succeed or all fail)
- Soft-deleted assets can be restored if needed

## Failure / fallback behavior

The ingest unit is a Collection, not an entire Source.

Collections act as content filters. Example: "Movies" may be included, "Adult" may be excluded.

Collections also act as path translation points. Each collection can map source_path → local_path.

A collection is considered ineligible for ingest if:

- sync_enabled is false, OR
- collection is not ingestible (no valid, accessible local paths)

Enricher failures on a single Asset do not abort ingest. Failures are logged and ingest continues.

**Asset Lifecycle**: Assets created during ingest start in `state='new'` and progress through `enriching` → `ready` states. Only assets in `ready` state with `approved_for_broadcast=true` are eligible for scheduling and playout.

Fatal stop conditions are:

- collection is disabled,
- collection storage path cannot be resolved,
- importer cannot enumerate assets for that collection.

## Operator workflows

- `retrovue source add ...` registers a new Source.
- `retrovue source list` shows all configured Sources.
- `retrovue source list-types` shows all importer types currently available to this build and loaded into the registry.
- `retrovue source discover <source_id>` discovers and adds Collections from a Source.
- `retrovue collection list --source <source_id>` shows Collections, including sync_enabled, ingestible status, and path mappings.
- `retrovue collection update <collection_id> --sync-disable` disables ingest for that Collection.
- `retrovue collection update <collection_id> --path-mapping "R:\\Media\\TV"` configures path mapping.
- `retrovue source <source_id> ingest` ingests all eligible Collections under that Source.
- `retrovue source <source_id> attach-enricher <enricher_id> --priority <n>` attaches an enricher to all collections in a source.
- `retrovue collection <collection_id> ingest` ingests just that Collection.
- `retrovue collection <collection_id> ingest --title <title>` ingests specific content.
- `retrovue collection <collection_id> wipe --dry-run` shows what would be deleted for a complete fresh start.
- `retrovue collection <collection_id> wipe` completely wipes a collection and all its data (nuclear option).

## Naming rules

- "Source" always refers to an external system instance (e.g. a Plex server).
- "Collection" always refers to a logical library or subtree inside that Source (e.g. "TV Shows").
- "Asset" is the single entity representing media content, with lifecycle states (`new`, `enriching`, `ready`, `retired`).
- "AssetData" is the raw data structure produced by importers before Asset creation.
- "Ingest Enricher" refers to enrichers with scope=ingest, which run on Assets during the `enriching` state. These enrichers may update metadata, classification, runtime, rating, ad markers, etc., and may advance an Asset toward `ready`.

## See also

- [Source](Source.md) - External content providers
- [Asset](Asset.md) - Media file management
- [Enricher](Enricher.md) - Content enhancement
- [Operator CLI](../cli/README.md) - Operational procedures
