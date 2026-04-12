# Ingest Architecture - Layered Implementation Strategy

## Problem Statement

The ingest hierarchy is:

- **Source Ingest** → loops over containers → calls Container Ingest
- **Container Ingest** → loops over Assets → calls Asset Processing

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
        container: Container,
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
        existing_asset = self._find_existing_asset(db, asset_data, container)

        if existing_asset:
            # 2. Check if update needed (content change or enricher change)
            if self._needs_update(db, existing_asset, asset_data, container):
                return self._update_asset(db, existing_asset, asset_data, enrichers)
            else:
                return AssetProcessingResult.skipped(existing_asset)

        # 3. Create new asset
        return self._create_asset(db, asset_data, container, enrichers)

    def _find_existing_asset(
        self,
        db: Session,
        asset_data: dict,  # Normalized Asset data from importer
        container: Container
    ) -> Asset | None:
        """Find existing asset by canonical identity."""
        canonical_id = self._get_canonical_identity(asset_data, container)
        return db.query(Asset).filter(
            Asset.container_id == container.uuid,
            Asset.canonical_id == canonical_id
        ).first()

    def _needs_update(
        self,
        db: Session,
        existing_asset: Asset,
        asset_data: dict,  # Normalized Asset data from importer
        container: Container
    ) -> bool:
        """Check if asset needs update (content changed or enricher changed)."""
        # Content change detection
        content_changed = self._has_content_changed(existing_asset, asset_data)

        # Enricher change detection
        enrichers_changed = self._have_enrichers_changed(
            db, existing_asset, container
        )

        return content_changed or enrichers_changed

    def _create_asset(
        self,
        db: Session,
        asset_data: dict,  # Normalized Asset data from importer
        container: Container,
        enrichers: list[Enricher]
    ) -> AssetProcessingResult:
        """Create new asset and apply enrichers."""
        asset = Asset(
            container_id=container.uuid,
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

### Layer 2: Container Ingest Orchestration (Transaction Boundary + Importer Integration)

**Purpose**: Orchestrates asset processing for a container. Manages transaction boundary and container-level concerns. Integrates with importer for asset enumeration.

**Key Characteristics**:

- Manages Unit of Work for entire container
- **Uses Importer to enumerate assets** (importer handles source-specific discovery logic)
- Calls Layer 1 (AssetProcessor) for each discovered asset
- Updates container.last_ingest_time
- Handles container-level validation

**Important**: The importer (`ImporterInterface`) is responsible for:

- **Enumeration**: Discovering/enumerating assets from external sources (Plex API, filesystem, etc.)
- **Normalization**: Returning canonicalized asset descriptions (normalized Asset data)
- **NOT Persistence**: Importers NEVER persist to database - they only return data

The service layer owns persistence within Unit of Work boundaries.

```python
class ContainerIngestService:
    """Orchestrates ingestion for a single container."""

    def __init__(self, asset_processor: AssetProcessor):
        self.asset_processor = asset_processor

    def ingest_container(
        self,
        container_id: str,
        filters: IngestFilters | None = None,
        dry_run: bool = False
    ) -> ContainerIngestResult:
        """
        Ingest a container - wraps entire operation in Unit of Work.

        Pre-conditions:
        - Container exists and is ingestible
        - sync_enabled=true for full ingest (unless targeted)

        Post-conditions:
        - All assets processed (or skipped)
        - container.last_ingest_time updated
        - Transaction committed or rolled back
        """
        with session() as db:
            try:
                # Phase 1: Pre-flight validation
                container = self._validate_container(db, container_id, filters)
                importer = self._get_importer(db, container)
                enrichers = self._get_enrichers(db, container)

                if dry_run:
                    return self._dry_run(db, container, importer, filters)

                # Phase 2: Execute ingest
                result = self._execute_ingest(
                    db, container, importer, enrichers, filters
                )

                # Phase 3: Update container timestamp
                container.last_ingest_time = datetime.utcnow()
                db.commit()

                # Phase 4: Post-operation validation
                self._validate_result(db, result)

                return result

            except Exception as e:
                db.rollback()
                logger.error("container_ingest_failed",
container_id=container_id, error=str(e))
raise IngestError(f"Container ingest failed: {e}")

    def _execute_ingest(
        self,
        db: Session,
        container: Container,
        importer: ImporterInterface,
        enrichers: list[Enricher],
        filters: IngestFilters | None
    ) -> ContainerIngestResult:
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
            container,
            filters=filters  # Title/season/episode scope if provided
        )

        # For each asset discovered by importer, process it through Layer 1
        for asset_data in asset_data_list:
            # Call Layer 1 - pure processing logic (handles persistence)
            result = self.asset_processor.process_asset(
                db, asset_data, container, enrichers
            )

            # Accumulate statistics
            if result.action == 'created':
                stats.assets_ingested += 1
            elif result.action == 'updated':
                stats.assets_updated += 1
            elif result.action == 'skipped':
                stats.assets_skipped += 1

            stats.assets_discovered += 1

        return ContainerIngestResult(stats=stats)

    def _get_importer(self, db: Session, container: Container) -> ImporterInterface:
        """Get importer instance for the container's source type."""
        source = db.query(Source).filter(Source.id == container.source_id).one()
        return importer_registry.get_importer(source.type, source.config)
```

### Layer 3: Source Ingest Orchestration (No Transaction, Delegates)

**Purpose**: Orchestrates multiple container ingests. Does NOT wrap everything in a transaction - each container has its own transaction.

**Key Characteristics**:

- No transaction management (delegates to Layer 2)
- Iterates over eligible containers
- Calls Layer 2 (ContainerIngestService) for each
- Aggregates results
- Handles partial failures gracefully

```python
class SourceIngestService:
    """Orchestrates ingestion for a source - delegates to container level."""

    def __init__(self, container_ingest_service: ContainerIngestService):
        self.container_ingest_service = container_ingest_service

    def ingest_source(
        self,
        source_id: str,
        dry_run: bool = False
    ) -> SourceIngestResult:
        """
        Ingest all eligible containers for a source.

        Important: Each container runs in its own transaction.
        Failures in one container do NOT rollback others.

        Pre-conditions:
        - Source exists
        - Source has at least one eligible container

        Post-conditions:
        - All eligible containers processed
        - Partial success allowed (some containers may fail)
        """
        with session() as db:
            # Phase 1: Pre-flight validation (read-only)
            source = self._validate_source(db, source_id)
            eligible_containers = self._get_eligible_containers(db, source)

            if not eligible_containers:
                raise IngestError("No eligible containers found")

        # Phase 2: Process each container (each in its own transaction)
        container_results = []
        errors = []

        for container in eligible_containers:
            try:
                # Call Layer 2 - each call manages its own transaction
                result = self.container_ingest_service.ingest_container(
                    container_id=container.uuid,
                    filters=None,  # Full container ingest
                    dry_run=dry_run
                )
                container_results.append(
                    ContainerResult(container=container, result=result)
                )
            except Exception as e:
                errors.append(
                    ContainerError(container=container, error=str(e))
                )
                logger.error("container_ingest_failed",
                           container_id=container.uuid, error=str(e))
                # Continue to next container - don't abort

        # Phase 3: Aggregate results
        return SourceIngestResult(
            containers_processed=len(container_results),
            container_results=container_results,
            errors=errors,
            status=self._determine_status(container_results, errors)
        )

    def _get_eligible_containers(
        self,
        db: Session,
        source: Source
    ) -> list[Container]:
        """Get containers that are sync_enabled=true AND ingestible=true."""
        return db.query(Container).filter(
            Container.source_id == source.id,
            Container.sync_enabled == True,
            Container.ingestible == True
        ).all()
```

## Key Architectural Benefits

### 1. **Zero Code Duplication**

- Asset processing logic exists once in `AssetProcessor`
- Called identically from container ingest and any future direct asset ingest
- Container orchestration exists once in `ContainerIngestService`
- Source orchestration exists once in `SourceIngestService`

### 2. **Efficient Transaction Management**

- **Source Ingest**: No transaction - delegates to containers
- **Container Ingest**: Single transaction per container (atomic)
- **Asset Processing**: No transaction - runs within container's transaction
- Matches contract requirements (partial success allowed at source level)

### 3. **Testability**

- Layer 1 (AssetProcessor) is pure - easy to unit test with mock sessions
- Layer 2 (ContainerIngestService) can be tested with transaction rollback
- Layer 3 (SourceIngestService) can be tested with mock Layer 2

### 4. **Maintainability**

- Clear separation of concerns
- Changes to asset processing logic happen in one place
- Changes to container orchestration happen in one place
- Changes to source orchestration happen in one place

### 5. **Contract Compliance**

- **Container Ingest**: Single UoW per container ✅
- **Source Ingest**: Each collection in its own UoW ✅
- **Partial Success**: Source ingest allows partial failures ✅
- **Atomicity**: Container ingest is atomic ✅

## Usage Patterns

### Direct Container Ingest (CLI)

```python
# CLI handler calls Layer 2 directly
container_service = ContainerIngestService(asset_processor)
result = container_service.ingest_container(
    container_id=container_id,
    filters=IngestFilters(title="The Big Bang Theory", season=1),
    dry_run=False
)
```

### Source Ingest (CLI)

```python
# CLI handler calls Layer 3
source_service = SourceIngestService(container_service)
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
        db, asset_draft, container, enrichers
    )
    db.commit()
```

## Transaction Boundary Diagram

```
Source Ingest (Layer 3)
  ├─ No transaction (read-only validation)
  │
  ├─ Container 1 Ingest (Layer 2)
  │   └─ Transaction START
  │       ├─ Importer.enumerate_assets() ────────┐
  │       │   (Source-specific discovery logic)   │ Plex API / filesystem scan
  │       │   Returns: [Asset data, Asset data]  │
  │       └─────────────────────────────────────┘
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┐
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┤ All within
  │       ├─ AssetProcessor.process_asset() (Layer 1) ────┤ same transaction
  │       └─ Update container.last_ingest_time ──────────┘
  │   └─ Transaction COMMIT (or ROLLBACK on error)
  │
  ├─ Container 2 Ingest (Layer 2)
  │   └─ Transaction START
  │       ├─ Importer.enumerate_assets()
  │       ├─ AssetProcessor.process_asset()
  │       └─ Update container.last_ingest_time
  │   └─ Transaction COMMIT (or ROLLBACK on error)
  │
  └─ Container 3 Ingest (Layer 2)
      └─ [Similar pattern]
```

## Responsibility Separation: Importer vs Service

### Importer Responsibilities (`ImporterInterface`)

- ✅ **Discovery**: Enumerate containers from external sources
- ✅ **Enumeration**: Enumerate assets from a container (with optional scope filters)
- ✅ **Normalization**: Return canonicalized Asset data
- ✅ **Validation**: `validate_ingestible()` checks prerequisites
- ❌ **NOT Persistence**: Importers NEVER write to database
- ❌ **NOT Transaction Management**: Importers have no transaction boundaries

### Service Layer Responsibilities

- ✅ **Transaction Management**: Owns Unit of Work boundaries
- ✅ **Persistence**: Creates/updates Asset records in database
- ✅ **Orchestration**: Coordinates importer + asset processor
- ✅ **Statistics**: Tracks ingest results
- ✅ **Container State**: Updates `last_ingest_time`, etc.

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
- [ ] Create `ContainerIngestService` class (Layer 2)
  - [ ] Implement `ingest_container()` with UoW
  - [ ] Integrate `AssetProcessor`
  - [ ] Implement container-level validation
  - [ ] Implement `last_ingest_time` updates
  - [ ] Implement statistics aggregation
- [ ] Create `SourceIngestService` class (Layer 3)

  - [ ] Implement `ingest_source()` without transaction
  - [ ] Implement container enumeration
  - [ ] Integrate `ContainerIngestService`
  - [ ] Implement result aggregation
  - [ ] Implement partial failure handling

- [ ] Update CLI handlers
  - [ ] `container ingest` → calls `ContainerIngestService`
  - [ ] `source ingest` → calls `SourceIngestService`

## See Also

- [Unit of Work Contract](../contracts/_ops/UnitOfWorkContract.md)
- [Container Ingest Contract](../contracts/resources/ContainerIngestContract.md)
- [Source Ingest Contract](../contracts/resources/SourceIngestContract.md)
- [Ingest Pipeline Domain](../domain/IngestPipeline.md)
