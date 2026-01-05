"""
Ingest Orchestrator - canonical orchestration of content ingestion.

This module provides the single source of truth for all ingest orchestration
logic, consolidating all ingest operations into a single orchestrator.

TODO: Channel runtime and Producer MUST NOT call ingest_orchestrator.
This orchestrator is offline/batch. Runtime will only consume canonical assets
that have already been imported and enriched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ..adapters.registry import get_enricher, get_importer
from ..domain.entities import Asset, Source
from .library_service import LibraryService
from .source_service import CollectionDTO, SourceService

logger = structlog.get_logger(__name__)


@dataclass
class IngestReport:
    """Report of ingest operation results."""

    discovered: int = 0
    """Number of items discovered"""

    registered: int = 0
    """Number of assets registered"""

    enriched: int = 0
    """Number of assets enriched"""

    canonicalized: int = 0
    """Number of assets marked as canonical"""

    queued_for_review: int = 0
    """Number of assets queued for review"""

    errors: int = 0
    """Number of processing errors"""

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary format for API responses."""
        return {
            "discovered": self.discovered,
            "registered": self.registered,
            "enriched": self.enriched,
            "canonicalized": self.canonicalized,
            "queued_for_review": self.queued_for_review,
            "errors": self.errors,
        }


class IngestOrchestrator:
    """
    Orchestrator for content ingestion operations.

    This orchestrator coordinates the complex multi-step process of content
    ingestion, managing the flow from external sources through discovery,
    enrichment, and final registration in the content library.

    **Architectural Role:** Orchestrator

    **Coordination Responsibilities:**
    - Coordinates SourceService (where does content live)
    - Coordinates registered Importers (adapters) for content discovery
    - Coordinates Enrichers for metadata enhancement
    - Coordinates LibraryService (which commits state)
    - Manages confidence calculation and canonicalization decisions

    **Critical Rule:** All ingest entrypoints (CLI, API) must call this
    orchestrator instead of reimplementing ingest steps. This ensures
    consistent behavior and prevents duplication of ingest logic.
    """

    def __init__(self, db: Session):
        """Initialize the orchestrator with a database session."""
        self.db = db
        self.library_service = LibraryService(db)
        self.source_service = SourceService(db)

    def run_full_ingest(
        self,
        *,
        source_id: str | None = None,
        collection_id: str | None = None,
        dry_run: bool = False,
    ) -> IngestReport:
        """
        Run full ingest operation for enabled collections.

        Args:
            source_id: Optional source ID to limit to specific source
            collection_id: Optional collection ID to limit to specific collection
            dry_run: If True, don't actually register/enrich assets

        Returns:
            IngestReport with operation results
        """
        report = IngestReport()

        try:
            # Step 1: Get collections to scan
            collections = self._get_collections_to_scan(source_id, collection_id)
            logger.info("ingest_started", collections_count=len(collections), dry_run=dry_run)

            # Step 2: Process each collection
            for collection in collections:
                try:
                    collection_report = self._process_collection(collection, dry_run)
                    self._merge_reports(report, collection_report)
                except Exception as e:
                    logger.error(
                        "collection_processing_failed",
                        collection_id=collection.external_id,
                        error=str(e),
                    )
                    report.errors += 1
                    continue

            logger.info("ingest_completed", report=report.to_dict())
            return report

        except Exception as e:
            logger.error("ingest_failed", error=str(e))
            raise

    def ingest_single_episode(
        self, source_id: str, episode_id: str, collection_id: str, dry_run: bool = False
    ) -> IngestReport:
        """
        Ingest a single episode from a Plex source.

        Args:
            source_id: Source ID (e.g., "plex")
            episode_id: Plex episode rating key
            dry_run: If True, don't actually register/enrich assets

        Returns:
            IngestReport with operation results
        """
        report = IngestReport()

        try:
            # Get the source
            source = self.db.query(Source).filter(Source.external_id == source_id).first()
            if not source:
                raise ValueError(f"Source {source_id} not found")

            # Get importer for the source
            importer = self._get_importer_for_source(source)

            # Get the collection
            collection = self.source_service.get_collection(source_id, collection_id)
            if not collection:
                raise ValueError(f"Collection {collection_id} not found for source {source_id}")

            # Discover the specific episode
            discovered_items = importer.discover_episode(episode_id)
            report.discovered = len(discovered_items)

            # Process each discovered item
            for item in discovered_items:
                try:
                    item_report = self._process_discovered_item(item, collection, dry_run)
                    self._merge_reports(report, item_report)
                except Exception as e:
                    logger.error("episode_processing_failed", episode_id=episode_id, error=str(e))
                    report.errors += 1
                    continue

            logger.info(
                "single_episode_ingest_completed", episode_id=episode_id, report=report.to_dict()
            )
            return report

        except Exception as e:
            logger.error("single_episode_ingest_failed", episode_id=episode_id, error=str(e))
            raise

    def _get_collections_to_scan(
        self, source_id: str | None = None, collection_id: str | None = None
    ) -> list[CollectionDTO]:
        """Get collections to scan based on parameters."""
        collections = []

        if source_id and collection_id:
            # Specific source and collection
            collection = self.source_service.get_collection(source_id, collection_id)
            if collection:
                collections = [collection]
        elif source_id:
            # All enabled collections for a source
            collections = self.source_service.list_enabled_collections(source_id)
        else:
            # All enabled collections from all sources
            sources = self.db.query(Source).all()
            for source in sources:
                source_collections = self.source_service.list_enabled_collections(
                    source.external_id
                )
                collections.extend(source_collections)

        return collections

    def _process_collection(
        self,
        collection: CollectionDTO,
        dry_run: bool,
        title_filter: str | None = None,
        season_filter: int | None = None,
        episode_filter: int | None = None,
    ) -> IngestReport:
        """Process a single collection."""
        report = IngestReport()

        # Get importer for the collection's source type
        importer = self._get_importer_for_collection(collection)

        # Discover items from the collection
        discovered_items = self._discover_from_collection(
            importer, collection, title_filter, season_filter, episode_filter
        )
        report.discovered = len(discovered_items)

        # Process each discovered item
        for item in discovered_items:
            try:
                item_report = self._process_discovered_item(item, collection, dry_run)
                self._merge_reports(report, item_report)
            except Exception as e:
                item_uri = getattr(item, "file_path", getattr(item, "path_uri", "unknown"))
                logger.error("item_processing_failed", item_uri=item_uri, error=str(e))
                report.errors += 1
                continue

        return report

    def _discover_from_collection(
        self,
        importer,
        collection: CollectionDTO,
        title_filter: str | None = None,
        season_filter: int | None = None,
        episode_filter: int | None = None,
    ) -> list:
        """Discover items from a collection using the appropriate importer."""
        if collection.source_type == "plex":
            # For Plex, use collection-specific discovery
            # Build source config and collection descriptor
            source_config: dict[str, Any] = {}  # PlexImporter doesn't need source config
            collection_descriptor = {"id": collection.external_id, "name": collection.name}
            # Use first local path from mapping pairs
            local_path = collection.mapping_pairs[0][1] if collection.mapping_pairs else ""

            return importer.fetch_assets_for_collection(
                source_config,
                collection_descriptor,
                local_path,
                title_filter=title_filter,
                season_filter=season_filter,
                episode_filter=episode_filter,
            )
        else:
            # For other sources, use general discovery
            return importer.discover()

    def _process_discovered_item(
        self, item, collection: CollectionDTO, dry_run: bool
    ) -> IngestReport:
        """Process a single discovered item."""
        report = IngestReport()

        if dry_run:
            # In dry run mode, just count as discovered
            report.discovered = 1
            return report

        try:
            # Check if this is an AssetDraft (from Plex importer) or legacy discovery data
            if hasattr(item, "series_title") and hasattr(item, "season_number"):
                # This is an AssetDraft with TV show hierarchy
                asset, is_newly_created = self._process_asset_draft_with_hierarchy(item, collection)
            else:
                # Legacy discovery data
                asset = self.library_service.register_asset_from_discovery(item)
                is_newly_created = True  # Assume legacy discovery creates new assets

            report.registered = 1

            # Step 2: Apply enrichers (only if enabled for this collection)
            enabled_enrichers = self._get_enabled_enrichers_for_collection(collection)
            for enricher_name in enabled_enrichers:
                try:
                    enricher = get_enricher(enricher_name)
                    asset = enricher.enrich(asset)
                    report.enriched = 1
                except Exception as e:
                    logger.warning("enricher_failed", enricher=enricher_name, error=str(e))
                    continue

            # Step 3: Calculate confidence and make canonicalization decision
            # Only do this for newly created assets, not existing duplicates
            if is_newly_created:
                confidence = self._calculate_confidence(item, asset)

                if confidence >= 0.8:
                    self.library_service.mark_asset_canonical(asset.id)
                    report.canonicalized = 1
                    logger.debug(
                        "asset_processed",
                        asset_id=str(asset.id),
                        status="canonicalized",
                        confidence=confidence,
                        series_title=getattr(item, "series_title", "unknown"),
                        season=getattr(item, "season_number", "unknown"),
                        episode=getattr(item, "episode_number", "unknown"),
                    )
                else:
                    reason = self._get_review_reason(asset, item)
                    self.library_service.enqueue_review(asset.id, reason, confidence)
                    report.queued_for_review = 1
                    logger.debug(
                        "asset_processed",
                        asset_id=str(asset.id),
                        status="queued_for_review",
                        confidence=confidence,
                        series_title=getattr(item, "series_title", "unknown"),
                        season=getattr(item, "season_number", "unknown"),
                        episode=getattr(item, "episode_number", "unknown"),
                    )
            else:
                # For duplicate assets, just log that we skipped processing
                logger.debug(
                    "asset_processed",
                    asset_id=str(asset.id),
                    status="duplicate_skipped",
                    series_title=getattr(item, "series_title", "unknown"),
                    season=getattr(item, "season_number", "unknown"),
                    episode=getattr(item, "episode_number", "unknown"),
                )

            return report

        except Exception as e:
            item_uri = getattr(item, "file_path", getattr(item, "path_uri", "unknown"))
            logger.error("item_processing_failed", item_uri=item_uri, error=str(e))
            report.errors = 1
            return report

    def _process_asset_draft_with_hierarchy(self, asset_draft, collection: CollectionDTO):
        """
        Process an AssetDraft with TV show hierarchy, creating proper database entities.

        This method creates the full TV show hierarchy:
        - Title (TV show/series)
        - Season
        - Episode
        - Asset
        - EpisodeAsset (junction table)

        Returns:
            tuple: (asset, is_newly_created) where is_newly_created is True if asset was created,
                   False if it was an existing duplicate
        """
        import uuid

        from ..domain.entities import Asset, Episode, EpisodeAsset, Season, Title

        session = self.db

        try:
            # Get the actual collection entity from the database
            from ..domain.entities import Collection

            collection_entity = (
                session.query(Collection)
                .filter(Collection.external_id == collection.external_id)
                .first()
            )

            if not collection_entity:
                raise ValueError(
                    f"Collection with external_id '{collection.external_id}' not found in database"
                )
            # Step 1: Create or find the Title (TV show)
            title = (
                session.query(Title)
                .filter(Title.name == asset_draft.series_title, Title.kind == "show")
                .first()
            )

            if not title:
                title = Title(
                    id=uuid.uuid4(),
                    name=asset_draft.series_title,
                    kind="show",
                    year=None,  # Could extract from asset_draft if available
                )
                session.add(title)
                session.flush()  # Get the ID

            # Step 2: Create or find the Season
            season = (
                session.query(Season)
                .filter(Season.title_id == title.id, Season.number == asset_draft.season_number)
                .first()
            )

            if not season:
                season = Season(
                    id=uuid.uuid4(), title_id=title.id, number=asset_draft.season_number
                )
                session.add(season)
                session.flush()  # Get the ID

            # Step 3: Create or find the Episode
            episode = (
                session.query(Episode)
                .filter(
                    Episode.title_id == title.id,
                    Episode.season_id == season.id,
                    Episode.number == asset_draft.episode_number,
                )
                .first()
            )

            if not episode:
                episode = Episode(
                    id=uuid.uuid4(),
                    title_id=title.id,
                    season_id=season.id,
                    number=asset_draft.episode_number,
                    name=asset_draft.episode_title,
                    external_ids={"plex_rating_key": asset_draft.external_id},
                )
                session.add(episode)
                session.flush()  # Get the ID

            # Step 4: Check for duplicate Asset before creating
            existing_asset = session.query(Asset).filter(Asset.uri == asset_draft.file_path).first()

            if existing_asset:
                # Check if EpisodeAsset junction exists, create if not
                existing_junction = (
                    session.query(EpisodeAsset)
                    .filter(
                        EpisodeAsset.episode_id == episode.id,
                        EpisodeAsset.asset_id == existing_asset.id,
                    )
                    .first()
                )

                if not existing_junction:
                    episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=existing_asset.id)
                    session.add(episode_asset)
                    session.commit()

                return existing_asset, False  # False = not newly created (duplicate)

            # Create the Asset
            asset = Asset(
                uuid=asset_draft.uuid,
                uri=asset_draft.file_path,
                size=asset_draft.file_size or 0,
                hash_sha256=None,  # Will be calculated by enrichers
                canonical=False,  # Start as non-canonical
                discovered_at=asset_draft.discovered_at,
                collection_id=collection_entity.id,
            )
            session.add(asset)
            session.flush()  # Get the ID

            # Step 5: Create the EpisodeAsset junction
            episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=asset.id)
            session.add(episode_asset)

            session.commit()

            return asset, True  # True = newly created

        except Exception as e:
            session.rollback()
            logger.error(
                "tv_show_hierarchy_creation_failed",
                series_title=asset_draft.series_title,
                season=asset_draft.season_number,
                episode=asset_draft.episode_number,
                error=str(e),
            )
            raise

    def _get_importer_for_source(self, source: Source):
        """Get importer for a source."""
        if source.type == "plex":
            # Build server configuration from source
            config = source.config or {}
            servers = [{"base_url": config.get("base_url"), "token": config.get("token")}]
            return get_importer("plex", servers=servers)
        else:
            return get_importer(source.type)

    def _get_importer_for_collection(self, collection: CollectionDTO):
        """Get importer for a collection."""
        if collection.source_type == "plex":
            # Get Plex sources from database
            plex_sources = self.db.query(Source).filter(Source.type == "plex").all()
            if not plex_sources:
                raise ValueError("No Plex sources configured")

            # Use the first Plex source for now
            # TODO: Support multiple Plex sources
            plex_source = plex_sources[0]
            config = plex_source.config or {}

            # Get server configuration from the servers array
            servers = config.get("servers", [])
            if not servers:
                raise ValueError("No Plex servers configured in source")

            server = servers[0]  # Use first server
            base_url = server.get("base_url")
            token = server.get("token")

            if not base_url or not token:
                raise ValueError(
                    f"Plex server configuration incomplete: base_url={base_url}, token={'***' if token else None}"
                )

            return get_importer("plex", base_url=base_url, token=token)
        else:
            return get_importer(collection.source_type)

    def _calculate_confidence(self, discovered_item, asset: Asset) -> float:
        """
        Calculate confidence score for canonicalization decision.

        This is the canonical confidence calculation logic.
        """
        confidence = 0.5  # Base confidence

        # Handle DiscoveredItem objects, AssetDraft objects, and dicts
        if hasattr(discovered_item, "raw_labels"):
            raw_labels = discovered_item.raw_labels or {}
        elif hasattr(discovered_item, "raw_metadata"):
            # AssetDraft object - use the rich metadata from the source
            raw_metadata = discovered_item.raw_metadata or {}
            raw_labels = raw_metadata  # Use raw_metadata as our labels
        else:
            # Dictionary
            raw_labels = discovered_item.get("raw_labels", {})

        # Ensure raw_labels is a dict
        if isinstance(raw_labels, list):
            # Convert list of strings to dict for processing
            labels_dict = {}
            for label in raw_labels:
                if ":" in label:
                    key, value = label.split(":", 1)
                    labels_dict[key] = value
            raw_labels = labels_dict

        # +0.4 for title match (strong indicator) - check multiple title fields
        title_fields = ["title_guess", "show_title", "plex_title", "title"]
        for field in title_fields:
            if field in raw_labels and raw_labels[field]:
                title = raw_labels[field]
                # Only boost confidence for titles that look meaningful (not just random strings)
                if len(title) > 3 and not title.isdigit() and not title.isalnum():
                    confidence += 0.4
                    break
                elif len(title) > 5:  # Allow longer alphanumeric titles
                    confidence += 0.2
                    break

        # +0.2 for season/episode structured data - check multiple field names
        season_fields = ["season", "season_index", "season_number"]
        episode_fields = ["episode", "episode_index", "episode_number"]
        has_season = any(field in raw_labels and raw_labels[field] for field in season_fields)
        has_episode = any(field in raw_labels and raw_labels[field] for field in episode_fields)
        if has_season and has_episode:
            confidence += 0.2

        # +0.2 for year data - check multiple field names
        year_fields = ["year", "plex_year", "release_year"]
        if any(field in raw_labels and raw_labels[field] for field in year_fields):
            confidence += 0.2

        # +0.2 for duration present (if we can detect it from file size or metadata)
        if (
            hasattr(discovered_item, "file_size")
            and discovered_item.file_size
            and discovered_item.file_size > 100 * 1024 * 1024
        ):  # > 100MB
            confidence += 0.2

        # +0.2 for codecs present (if we can detect from filename)
        file_path = getattr(
            discovered_item, "file_path", getattr(discovered_item, "path_uri", None)
        )
        if file_path:
            filename = file_path.split("/")[-1].lower()
            # Check for common codec indicators in filename
            codec_indicators = ["h264", "h265", "hevc", "x264", "x265", "avc", "aac", "ac3", "dts"]
            if any(codec in filename for codec in codec_indicators):
                confidence += 0.2

        # Additional boost for structured content type
        if "type" in raw_labels or "plex_type" in raw_labels:
            confidence += 0.1

        # Boost confidence for Plex metadata (legacy support)
        if "title" in raw_labels or "plex_title" in raw_labels:
            confidence += 0.3  # Plex provides good metadata

        # Additional confidence from asset enrichment (if available)
        if asset.duration_ms and asset.duration_ms > 0:
            confidence += 0.1

        if asset.video_codec or asset.audio_codec:
            confidence += 0.1

        return min(confidence, 1.0)

    def _get_review_reason(self, asset: Asset, discovered_item) -> str:
        """Get reason for review queue."""
        if asset.hash_sha256 is None:
            return "No hash available"
        if asset.size < 1024 * 1024:
            return "File size too small"
        return "Manual review required"

    def ingest_collection(
        self,
        collection_id: str,
        dry_run: bool = False,
        title_filter: str | None = None,
        season_filter: int | None = None,
        episode_filter: int | None = None,
    ) -> dict:
        """
        Ingest a single collection by ID.

        Args:
            collection_id: UUID of the collection to ingest

        Returns:
            Dictionary with ingest results
        """
        try:
            # Get the collection from database
            import uuid

            from ..domain.entities import Collection

            collection = None

            # Try to find by UUID first
            try:
                if len(collection_id) == 36 and collection_id.count("-") == 4:
                    collection_uuid = uuid.UUID(collection_id)
                    collection = (
                        self.db.query(Collection).filter(Collection.uuid == collection_uuid).first()
                    )
            except (ValueError, TypeError):
                pass

            # If not found by UUID, try by external_id
            if not collection:
                collection = (
                    self.db.query(Collection)
                    .filter(Collection.external_id == collection_id)
                    .first()
                )

            # If not found by external_id, try by name (case-insensitive)
            if not collection:
                name_matches = (
                    self.db.query(Collection).filter(Collection.name.ilike(collection_id)).all()
                )
                if len(name_matches) == 1:
                    collection = name_matches[0]
                elif len(name_matches) > 1:
                    raise ValueError(
                        f"Multiple collections found with name '{collection_id}'. Use full UUID to specify."
                    )

            if not collection:
                raise ValueError(f"Collection '{collection_id}' not found")

            # Convert to DTO
            # Get path mappings for this collection
            from ..domain.entities import PathMapping
            from .source_service import CollectionDTO

            mappings = (
                self.db.query(PathMapping)
                .filter(PathMapping.collection_id == collection.uuid)
                .all()
            )

            mapping_pairs = [(m.plex_path, m.local_path) for m in mappings]

            # Get source info
            from ..domain.entities import Source

            source = self.db.query(Source).filter(Source.id == collection.source_id).first()

            collection_dto = CollectionDTO(
                external_id=collection.external_id,
                name=collection.name,
                sync_enabled=collection.sync_enabled,
                mapping_pairs=mapping_pairs,
                source_type=source.type if source else "unknown",
                config=collection.config,
            )

            # Process the collection
            report = self._process_collection(
                collection_dto,
                dry_run=dry_run,
                title_filter=title_filter,
                season_filter=season_filter,
                episode_filter=episode_filter,
            )

            return {
                "assets_processed": report.registered,
                "assets_enriched": report.enriched,
                "assets_canonicalized": report.canonicalized,
                "assets_queued_for_review": report.queued_for_review,
                "errors": report.errors,
            }

        except Exception as e:
            logger.error("collection_ingest_failed", collection_id=collection_id, error=str(e))
            raise

    def _get_enabled_enrichers_for_collection(self, collection: CollectionDTO) -> list[str]:
        """
        Get list of enabled enrichers for a collection.

        For now, this returns a default set of enrichers.
        In the future, this will check the database for enricher attachments.

        Args:
            collection: The collection to check for enabled enrichers

        Returns:
            List of enricher names that are enabled for this collection
        """
        # TODO: Implement actual enricher attachment checking from database
        # For now, return empty list to test enricher behavior
        return []

    def _merge_reports(self, target: IngestReport, source: IngestReport):
        """Merge source report into target report."""
        target.discovered += source.discovered
        target.registered += source.registered
        target.enriched += source.enriched
        target.canonicalized += source.canonicalized
        target.queued_for_review += source.queued_for_review
        target.errors += source.errors
