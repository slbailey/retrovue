# Ingest Architecture - Layered Implementation Strategy

## Problem Statement

The ingest hierarchy is:

- **Source Ingest** → loops over Collections → calls Collection Ingest
- **Collection Ingest** → loops over Assets → calls Asset Processing

The challenge: Avoid code duplication while maintaining efficient, testable, and maintainable code that respects contract boundaries (especially Unit of Work requirements).

## Solution: Three-Layer Architecture

### Layer 1: Core Asset Processing (Reusable, No Transaction)

**Purpose**: Pure, reusable logic for processing a single asset. No transaction management - called from within transactions.

**Key Characteristics**:

- No database session management
- No transaction boundaries
- Pure business logic
- Accepts database session as parameter
- Idempotent and stateless

```python
class AssetProcessor:
    """Core asset processing logic - reusable across all ingest levels."""

    def process_asset(
        self,
        db: Session,
        asset_data: dict,  # Normalized Asset data from importer
        collection: Collection,
        enrichers: list[Enricher]
    ) -> AssetProcessingResult:
        """
        Process a single asset through the ingest pipeline.

        Pre-conditions:
        - All validations occur at caller level
        - Session is already within transaction

        Returns:
        - AssetProcessingResult with created/updated/skipped status
        """
        # 1. Check for duplicate (canonical identity)
        existing_asset = self._find_existing_asset(db, asset_data, collection)

        if existing_asset:
            # 2. Check if update needed (content change or enricher change)
            if self._needs_update(db, existing_asset, asset_data, collection):
                return self._update_asset(db, existing_asset, asset_data, enrichers)
            else:
                return AssetProcessingResult.skipped(existing_asset)

        # 3. Create new asset
        return self._create_asset(db, asset_data, collection, enrichers)

    def _find_existing_asset(
        self,
        db: Session,
        asset_data: dict,  # Normalized Asset data from importer
        collection: Collection
    ) -> Asset | None:
        """Find existing asset by canonical identity."""
        canonical_id = self._get_canonical_identity(asset_data, collection)
        return db.query(Asset).filter(
            Asset.collection_id == collection.id,
            Asset.canonical_id == canonical_id
        ).first()

    def _needs_update(
        self,
        db: Session,
        existing_asset: Asset,
        asset_data: dict,  # Normalized Asset data from importer
        collection: Collection
    ) -> bool:
        """Check if asset needs update (content changed or enricher changed)."""
        # Content change detection
        content_changed = self._has_content_changed(existing_asset, asset_data)

        # Enricher change detection
        enrichers_changed = self._have_enrichers_changed(
            db, existing_asset, collection
        )

        return content_changed or enrichers_changed

    def _create_asset(
        self,
        db: Session,
        asset_data: dict,  # Normalized Asset data from importer
        collection: Collection,
        enrichers: list[Enricher]
    ) -> AssetProcessingResult:
        """Create new asset and apply enrichers."""
        asset = Asset(
            collection_id=collection.id,
            state='new',
            # ... other fields from normalized asset_data
        )
        db.add(asset)

        # Apply enrichers
        for enricher in sorted(enrichers, key=lambda e: e.priority):
            asset = enricher.enrich(asset)
            if asset.state == 'enriching':
                break  # Enricher changed state, stop

        return AssetProcessingResult.created(asset)

    def _update_asset(
        self,
        db: Session,
        existing_asset: Asset,
        asset_data: dict,  # Normalized Asset data from importer
        enrichers: list[Enricher]
    ) -> AssetProcessingResult:
        """Update existing asset and re-apply enrichers."""
        # Update metadata from normalized asset data
        existing_asset.update_from_data(asset_data)

        # Reset state if needed
        if existing_asset.state == 'ready':
            existing_asset.state = 'new'  # Re-process through enrichers

        # Re-apply enrichers
        for enricher in sorted(enrichers, key=lambda e: e.priority):
            existing_asset = enricher.enrich(existing_asset)
            if existing_asset.state == 'enriching':
                break

        existing_asset.updated_at = datetime.utcnow()
        return AssetProcessingResult.updated(existing_asset)
```

### Layer 2: Collection Ingest Orchestration (Transaction Boundary + Importer Integration)

**Purpose**: Orchestrates asset processing for a collection. Manages transaction boundary and collection-level concerns. Integrates with importer for asset enumeration.

**Key Characteristics**:

- Manages Unit of Work for entire collection
- **Uses Importer to enumerate assets** (importer handles source-specific discovery logic)
- Calls Layer 1 (AssetProcessor) for each discovered asset
- Updates collection.last_ingest_time
- Handles collection-level validation

**Important**: The importer (`ImporterInterface`) is responsible for:

- **Enumeration**: Discovering/enumerating assets from external sources (Plex API, filesystem, etc.)
- **Normalization**: Returning canonicalized asset descriptions (normalized Asset data)
- **NOT Persistence**: Importers NEVER persist to database - they only return data

The service layer owns persistence within Unit of Work boundaries.

```python
class CollectionIngestService:
    """Orchestrates ingestion for a single collection."""

    def __init__(self, asset_processor: AssetProcessor):
        self.asset_processor = asset_processor

    def ingest_collection(
        self,
        collection_id: str,
        filters: IngestFilters | None = None,
        dry_run: bool = False
    ) -> CollectionIngestResult:
        """
        Ingest a collection - wraps entire operation in Unit of Work.

        Pre-conditions:
        - Collection exists and is ingestible
        - sync_enabled=true for full ingest (unless targeted)

        Post-conditions:
        - All assets processed (or skipped)
        - collection.last_ingest_time updated
        - Transaction committed or rolled back
        """
        with session() as db:
            try:
                # Phase 1: Pre-flight validation
                collection = self._validate_collection(db, collection_id, filters)
                importer = self._get_importer(db, collection)
                enrichers = self._get_enrichers(db, collection)

                if dry_run:
                    return self._dry_run(db, collection, importer, filters)

                # Phase 2: Execute ingest
                result = self._execute_ingest(
                    db, collection, importer, enrichers, filters
                )

                # Phase 3: Update collection timestamp
                collection.last_ingest_time = datetime.utcnow()
                db.commit()

                # Phase 4: Post-operation validation
                self._validate_result(db, result)

                return result

            except Exception as e:
                db.rollback()
                logger.error("collection_ingest_failed",
                           collection_id=collection_id, error=str(e))
                raise IngestError(f"Collection ingest failed: {e}")

    def _execute_ingest(
        self,
        db: Session,
        collection: Collection,
        importer: ImporterInterface,
        enrichers: list[Enricher],
        filters: IngestFilters | None
    ) -> CollectionIngestResult:
        """
        Execute the actual ingest.

        The importer enumerates assets from the external source (Plex API calls,
        filesystem scanning, etc.) and returns normalized Asset data.
        The service layer then processes each asset through Layer 1 which handles
        persistence.
        """
        stats = IngestStats()

        # IMPORTANT: Importer handles enumeration/discovery (not persistence)
        # This is where source-specific logic lives:
        # - Plex: Makes API calls to get library items
        # - Filesystem: Scans directories for media files
        # - Returns: Normalized Asset data (no database writes)
        asset_data_list = importer.enumerate_assets(
            collection,
            filters=filters  # Title/season/episode scope if provided
        )

        # For each asset discovered by importer, process it through Layer 1
        for asset_data in asset_data_list:
            # Call Layer 1 - pure processing logic (handles persistence)
            result = self.asset_processor.process_asset(
                db, asset_data, collection, enrichers
            )

            # Accumulate statistics
            if result.action == 'created':
                stats.assets_ingested += 1
            elif result.action == 'updated':
                stats.assets_updated += 1
            elif result.action == 'skipped':
                stats.assets_skipped += 1

            stats.assets_discovered += 1

        return CollectionIngestResult(stats=stats)

    def _get_importer(self, db: Session, collection: Collection) -> ImporterInterface:
        """Get importer instance for the collection's source type."""
        source = db.query(Source).filter(Source.id == collection.source_id).one()
        return importer_registry.get_importer(source.type, source.config)
```

### Layer 3: Source Ingest Orchestration (No Transaction, Delegates)

**Purpose**: Orchestrates multiple collection ingests. Does NOT wrap everything in a transaction - each collection has its own transaction.

**Key Characteristics**:

- No transaction management (delegates to Layer 2)
- Iterates over eligible collections
- Calls Layer 2 (CollectionIngestService) for each
- Aggregates results
- Handles partial failures gracefully

```python
class SourceIngestService:
    """Orchestrates ingestion for a source - delegates to collection level."""

    def __init__(self, collection_ingest_service: CollectionIngestService):
        self.collection_ingest_service = collection_ingest_service

    def ingest_source(
        self,
        source_id: str,
        dry_run: bool = False
    ) -> SourceIngestResult:
        """
        Ingest all eligible collections for a source.

        Important: Each collection runs in its own transaction.
        Failures in one collection do NOT rollback others.

        Pre-conditions:
        - Source exists
        - Source has at least one eligible collection

        Post-conditions:
        - All eligible collections processed
        - Partial success allowed (some collections may fail)
        """
        with session() as db:
            # Phase 1: Pre-flight validation (read-only)
            source = self._validate_source(db, source_id)
            eligible_collections = self._get_eligible_collections(db, source)

            if not eligible_collections:
                raise IngestError("No eligible collections found")

        # Phase 2: Process each collection (each in its own transaction)
        collection_results = []
        errors = []

        for collection in eligible_collections:
            try:
                # Call Layer 2 - each call manages its own transaction
                result = self.collection_ingest_service.ingest_collection(
                    collection_id=collection.id,
                    filters=None,  # Full collection ingest
                    dry_run=dry_run
                )
                collection_results.append(
                    CollectionResult(collection=collection, result=result)
                )
            except Exception as e:
                errors.append(
                    CollectionError(collection=collection, error=str(e))
                )
                logger.error("collection_ingest_failed",
                           collection_id=collection.id, error=str(e))
                # Continue to next collection - don't abort

        # Phase 3: Aggregate results
        return SourceIngestResult(
            collections_processed=len(collection_results),
            collection_results=collection_results,
            errors=errors,
            status=self._determine_status(collection_results, errors)
        )

    def _get_eligible_collections(
        self,
        db: Session,
        source: Source
    ) -> list[Collection]:
        """Get collections that are sync_enabled=true AND ingestible=true."""
        return db.query(Collection).filter(
            Collection.source_id == source.id,
            Collection.sync_enabled == True,
            Collection.ingestible == True
        ).all()
```

## Key Architectural Benefits

### 1. **Zero Code Duplication**

- Asset processing logic exists once in `AssetProcessor`
- Called identically from collection ingest and any future direct asset ingest
- Collection orchestration exists once in `CollectionIngestService`
- Source orchestration exists once in `SourceIngestService`

### 2. **Efficient Transaction Management**

- **Source Ingest**: No transaction - delegates to collections
- **Collection Ingest**: Single transaction per collection (atomic)
- **Asset Processing**: No transaction - runs within collection's transaction
- Matches contract requirements (partial success allowed at source level)

### 3. **Testability**

- Layer 1 (AssetProcessor) is pure - easy to unit test with mock sessions
- Layer 2 (CollectionIngestService) can be tested with transaction rollback
- Layer 3 (SourceIngestService) can be tested with mock Layer 2

### 4. **Maintainability**

- Clear separation of concerns
- Changes to asset processing logic happen in one place
- Changes to collection orchestration happen in one place
- Changes to source orchestration happen in one place

### 5. **Contract Compliance**

- **Collection Ingest**: Single UoW per collection ✅
- **Source Ingest**: Each collection in its own UoW ✅
- **Partial Success**: Source ingest allows partial failures ✅
- **Atomicity**: Collection ingest is atomic ✅

## Usage Patterns

### Direct Collection Ingest (CLI)

```python
# CLI handler calls Layer 2 directly
collection_service = CollectionIngestService(asset_processor)
result = collection_service.ingest_collection(
    collection_id=collection_id,
    filters=IngestFilters(title="The Big Bang Theory", season=1),
    dry_run=False
)
```

### Source Ingest (CLI)

```python
# CLI handler calls Layer 3
source_service = SourceIngestService(collection_service)
result = source_service.ingest_source(
    source_id=source_id,
    dry_run=False
)
```

### Future: Direct Asset Ingest

```python
# Future CLI command could call Layer 1 directly (with transaction wrapper)
with session() as db:
    result = asset_processor.process_asset(
        db, asset_draft, collection, enrichers
    )
    db.commit()
```

## Transaction Boundary Diagram

```
Source Ingest (Layer 3)
  ├─ No transaction (read-only validation)
  │
  ├─ Collection 1 Ingest (Layer 2)
  │   └─ Transaction START
  │       ├─ Importer.enumerate_assets() ────────┐
  │       │   (Source-specific discovery logic)   │ Plex API / filesystem scan
  │       │   Returns: [Asset data, Asset data]  │
  │       └─────────────────────────────────────┘
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┐
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┤ All within
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┤ same transaction
  │       └─ Update collection.last_ingest_time ──────────┘
  │   └─ Transaction COMMIT (or ROLLBACK on error)
  │
  ├─ Collection 2 Ingest (Layer 2)
  │   └─ Transaction START
  │       ├─ Importer.enumerate_assets()
  │       ├─ AssetProcessor.process_asset()
  │       └─ Update collection.last_ingest_time
  │   └─ Transaction COMMIT (or ROLLBACK on error)
  │
  └─ Collection 3 Ingest (Layer 2)
      └─ [Similar pattern]
```

## Responsibility Separation: Importer vs Service

### Importer Responsibilities (`ImporterInterface`)

- ✅ **Discovery**: Enumerate collections from external sources
- ✅ **Enumeration**: Enumerate assets from a collection (with optional scope filters)
- ✅ **Normalization**: Return canonicalized Asset data
- ✅ **Validation**: `validate_ingestible()` checks prerequisites
- ❌ **NOT Persistence**: Importers NEVER write to database
- ❌ **NOT Transaction Management**: Importers have no transaction boundaries

### Service Layer Responsibilities

- ✅ **Transaction Management**: Owns Unit of Work boundaries
- ✅ **Persistence**: Creates/updates Asset records in database
- ✅ **Orchestration**: Coordinates importer + asset processor
- ✅ **Statistics**: Tracks ingest results
- ✅ **Collection State**: Updates `last_ingest_time`, etc.

This separation ensures:

- **Importer = Infrastructure**: Handles external source communication
- **Service = Business Logic**: Handles persistence and orchestration
- **Clear Boundaries**: Each layer has well-defined responsibilities

## Implementation Checklist

- [ ] Create `AssetProcessor` class (Layer 1)
  - [ ] Implement `process_asset()` method
  - [ ] Implement duplicate detection
  - [ ] Implement content change detection
  - [ ] Implement enricher change detection
  - [ ] Implement asset creation/update logic
- [ ] Create `CollectionIngestService` class (Layer 2)
  - [ ] Implement `ingest_collection()` with UoW
  - [ ] Integrate `AssetProcessor`
  - [ ] Implement collection-level validation
  - [ ] Implement `last_ingest_time` updates
  - [ ] Implement statistics aggregation
- [ ] Create `SourceIngestService` class (Layer 3)

  - [ ] Implement `ingest_source()` without transaction
  - [ ] Implement collection enumeration
  - [ ] Integrate `CollectionIngestService`
  - [ ] Implement result aggregation
  - [ ] Implement partial failure handling

- [ ] Update CLI handlers
  - [ ] `collection ingest` → calls `CollectionIngestService`
  - [ ] `source ingest` → calls `SourceIngestService`

## See Also

- [Unit of Work Contract](../contracts/_ops/UnitOfWorkContract.md)
- [Collection Ingest Contract](../contracts/resources/CollectionIngestContract.md)
- [Source Ingest Contract](../contracts/resources/SourceIngestContract.md)
- [Ingest Pipeline Domain](../domain/IngestPipeline.md)
