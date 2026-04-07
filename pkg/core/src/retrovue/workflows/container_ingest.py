"""
Container ingest workflow.

Cross-domain workflow extracted from cli/commands/_ops/ per the Asset Domain
Alignment Plan (Phase 1).  All business logic is preserved; only the package
location and relative imports changed.

This module encapsulates all non-IO logic needed to satisfy
docs/contracts/resources/ContainerIngestContract.md, specifically rules B-1 through B-21,
and D-1 through D-18.

The module provides:
- Container selector resolution (UUID, external ID, case-insensitive name)
- Validation ordering (container resolution → prerequisites → scope resolution)
- Importer interaction boundary (validate_ingestible before enumerate_assets)
- Unit of Work wrapping for atomic ingest operations
- Result shape matching contract output format

This module MUST NOT read from stdin or write to stdout. All IO stays in the CLI command wrapper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from retrovue.infra.metadata.persistence import persist_asset_metadata

from ..adapters.registry import ENRICHERS
from ..catalog.discovery import discover_locators
from ..catalog.processor_jobs import enqueue_processor_jobs
from ..catalog.reconciliation import (
    ReconciliationOutcome,
    determine_reconciliation_outcomes,
    load_catalog_state_for_container,
)
from ..domain.entities import Asset, Container
from ..infra.canonical import canonical_hash, canonical_key_for
from ..infra.exceptions import IngestError
from ..infra.settings import settings
from ..usecases.metadata_handler import handle_ingest
from ..usecases.asset_path_resolver import AssetPathResolver

logger = structlog.get_logger(__name__)


class _AssetRepository:
    """Private repository for Asset operations scoped to this service."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_container_and_canonical_hash(self, container_id, canonical_key_hash):
        stmt = select(Asset).where(
            Asset.container_id == container_id,
            Asset.canonical_key_hash == canonical_key_hash,
        )
        # Session.scalar returns the first column of the first row or None
        return self.db.scalar(stmt)

    def create(self, asset: Asset) -> None:
        self.db.add(asset)


@dataclass
class IngestStats:
    """Statistics for an ingest operation."""

    assets_discovered: int = 0
    assets_ingested: int = 0
    assets_skipped: int = 0
    assets_changed_content: int = 0
    assets_changed_enricher: int = 0
    assets_updated: int = 0
    duplicates_prevented: int = 0
    assets_removed: int = 0
    assets_auto_ready: int = 0
    assets_needs_enrichment: int = 0
    assets_needs_review: int = 0
    errors: list[str] = None

    def __post_init__(self):
        """Initialize errors list if None."""
        if self.errors is None:
            self.errors = []


@dataclass
class ContainerIngestResult:
    """Result of a container ingest operation."""

    container_id: str
    container_name: str
    scope: str  # "container", "title", "season", "episode"
    stats: IngestStats
    last_ingest_time: str | None = None
    title: str | None = None
    season: int | None = None
    episode: int | None = None
    # Verbose-only fields (included in JSON only when populated by verbose flag)
    created_assets: list[dict[str, str]] | None = None
    updated_assets: list[dict[str, str]] | None = None
    thresholds: dict[str, float] | None = None
    # Processors that were enqueued (worker will run these on each asset)
    enqueued_processors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        result = {
            "status": "success",
            "scope": self.scope,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "stats": {
                "assets_discovered": self.stats.assets_discovered,
                "assets_ingested": self.stats.assets_ingested,
                "assets_skipped": self.stats.assets_skipped,
                "assets_changed_content": self.stats.assets_changed_content,
                "assets_changed_enricher": self.stats.assets_changed_enricher,
                "assets_updated": self.stats.assets_updated,
                "assets_removed": self.stats.assets_removed,
                "duplicates_prevented": self.stats.duplicates_prevented,
                "assets_auto_ready": self.stats.assets_auto_ready,
                "assets_needs_enrichment": self.stats.assets_needs_enrichment,
                "assets_needs_review": self.stats.assets_needs_review,
                "errors": self.stats.errors,
            },
        }

        if self.thresholds is not None:
            result["thresholds"] = self.thresholds

        if self.last_ingest_time:
            result["last_ingest_time"] = self.last_ingest_time.isoformat() + "Z"

        if self.title:
            result["title"] = self.title
        if self.season is not None:
            result["season"] = self.season
        if self.episode is not None:
            result["episode"] = self.episode
        if self.enqueued_processors is not None:
            result["enqueued_processors"] = self.enqueued_processors
        # Only include verbose lists when populated
        if self.created_assets is not None:
            result["created_assets"] = self.created_assets
        if self.updated_assets is not None:
            result["updated_assets"] = self.updated_assets

        return result


def get_container_by_id(db: Session, container_id: uuid.UUID) -> Container | None:
    """Return the container with the given UUID, or None if not found."""
    return db.get(Container, container_id)


def resolve_container_selector(db: Session, container_selector: str) -> Container:
    """
    Resolve container selector to a concrete Container.

    Implements B-1 resolution logic:
    - UUID (exact match)
    - External ID (exact match)
    - Case-insensitive name (single match required, multiple matches raise error)

    Args:
        db: Database session
        container_selector: The selector string (UUID, external ID, or name)

    Returns:
        Container entity

    Raises:
        ValueError: If container not found or ambiguous
    """
    container = None

    # Try UUID first (B-1: UUID resolution)
    try:
        if len(container_selector) == 36 and container_selector.count("-") == 4:
            container_uuid = uuid.UUID(container_selector)
            container = db.query(Container).filter(Container.uuid == container_uuid).one()
    except (ValueError, TypeError):
        pass

    # If not found by UUID, try external_id (B-1: external ID resolution)
    if not container:
        container = (
            db.query(Container).filter(Container.external_id == container_selector).first()
        )

    # If not found by external_id, try name (case-insensitive) (B-1: name resolution)
    if not container:
        name_matches = db.query(Container).filter(Container.name.ilike(container_selector)).all()

        if len(name_matches) == 0:
            raise ValueError(f"Container '{container_selector}' not found")
        elif len(name_matches) == 1:
            container = name_matches[0]
        else:
            # Multiple matches - must fail with specific error message (B-1)
            raise ValueError(
                f"Multiple containers named '{container_selector}' exist. Please specify the UUID."
            )

    if not container:
        raise ValueError(f"Container '{container_selector}' not found")

    return container


def validate_prerequisites(
    container: Container, is_full_ingest: bool, dry_run: bool = False
) -> None:
    """
    Validate container prerequisites for ingest.

    Implements B-11, B-12, B-13 validation logic:
    - Full ingest requires sync_enabled=true AND ingestible=true
    - Targeted ingest requires ingestible=true (may bypass sync_enabled=false)
    - Dry-run bypasses prerequisite checks

    Args:
        container: The Container to validate
        is_full_ingest: Whether this is a full container ingest (no scope filters)
        dry_run: Whether this is a dry-run (allows bypass of prerequisites)

    Raises:
        ValueError: If prerequisites not met (with appropriate error message)
    """
    # Dry-run bypasses prerequisites but still validates for preview
    if dry_run:
        # Dry-run allows preview even if prerequisites fail
        return

    # Full container ingest requires sync_enabled AND ingestible (B-11, B-12)
    if is_full_ingest:
        if not container.sync_enabled:
            raise ValueError(
                f"Container '{container.name}' is not sync-enabled. "
                "Use targeted ingest (--title/--season/--episode) for surgical operations, "
                f"or enable sync with 'retrovue container update {container.uuid} --sync-enable'."
            )

    # All ingest requires ingestible (B-12, B-13)
    if not container.ingestible:
        raise ValueError(
            f"Container '{container.name}' is not ingestible. "
            f"Check path mappings and prerequisites with 'retrovue container show {container.uuid}'."
        )


def validate_ingestible_with_importer(importer: Any, container: Container) -> bool:
    """
    Validate container ingestibility using importer's validate_ingestible method.

    Implements D-5, D-5a, D-5c:
    - Calls importer.validate_ingestible()
    - MUST be called BEFORE enumerate_assets()
    - Importer does NOT write to database

    Args:
        importer: Importer instance (must have validate_ingestible method)
        container: The Container to validate

    Returns:
        bool: True if container is ingestible according to importer, False otherwise
    """
    return importer.validate_ingestible(container)


class ContainerIngestService:
    """
    Service for performing container ingest operations (discovery + reconciliation + enqueue).

    Implements the contract-compliant orchestration layer for container ingest,
    handling container resolution, validation ordering, importer interaction, and Unit of Work
    boundaries per ContainerIngestContract.md.
    """

    def __init__(self, db: Session):
        """
        Initialize the service.

        Args:
            db: Database session (must be within a transaction context)
        """
        self.db = db

    def ingest_container(
        self,
        container: Container | str,
        importer: Any,
        title: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        dry_run: bool = False,
        test_db: bool = False,
        verbose_assets: bool = False,
        max_new: int | None = None,
        max_updates: int | None = None,
    ) -> ContainerIngestResult:
        """
        Ingest a container following the contract validation order.

        Validation order (B-15, D-4a):
        1. Container resolution (if container is a string selector)
        2. Prerequisite validation (sync_enabled, ingestible)
        3. Importer validate_ingestible() (D-5c)
        4. Scope resolution (title/season/episode)
        5. Actual ingest work

        Args:
            container: Container entity or selector string
            importer: Importer instance (must implement ImporterInterface)
            title: Optional title filter
            season: Optional season filter (requires title)
            episode: Optional episode filter (requires season)
            dry_run: Whether to perform dry-run (no database writes)
            test_db: Whether to use test database context

        Returns:
            ContainerIngestResult with ingest statistics and metadata

        Raises:
            ValueError: If validation fails (exit code 1)
            IngestError: If scope resolution fails (exit code 2)
            RuntimeError: If ingest operation fails
        """
        # Phase 1: Container Resolution (B-15 step 1, D-4a)
        if isinstance(container, str):
            try:
                container = resolve_container_selector(self.db, container)
            except ValueError as e:
                # Container not found or ambiguous - exit code 1 (B-1)
                raise ValueError(str(e)) from e

        # Phase 2: Importer Validation (B-14a, D-5c)
        # MUST call validate_ingestible() BEFORE enumerate_assets(); call early to satisfy contract tests
        importer_ok = validate_ingestible_with_importer(importer, container)
        if not importer_ok:
            # Validation failed - exit code 1 (or allow dry-run preview)
            if not dry_run:
                # Defer raising until after prerequisite validation has had a chance to run
                pass

        # Phase 3: Prerequisite Validation (B-15 step 2, D-4a)
        is_full_ingest = title is None and season is None and episode is None

        try:
            validate_prerequisites(container, is_full_ingest, dry_run=dry_run)
        except ValueError as e:
            # Prerequisite validation failed - exit code 1 (B-11, B-12, B-13)
            raise ValueError(str(e)) from e

        # If importer validation failed and not dry-run, raise after prerequisites
        if not importer_ok and not dry_run:
            raise ValueError(
                f"Container '{container.name}' is not ingestible according to importer. "
                f"Check path mappings and prerequisites with 'retrovue container show {container.uuid}'."
            )

        # Phase 4: Scope Resolution (B-15 step 3, D-4a)
        # Determine scope from filters
        if episode is not None:
            scope = "episode"
        elif season is not None:
            scope = "season"
        elif title is not None:
            scope = "title"
        else:
            scope = "container"

        # Phase 5: Execute Ingest Work
        stats = IngestStats()
        repo = _AssetRepository(self.db)
        created_assets: list[dict[str, str]] | None = [] if verbose_assets else None
        updated_assets: list[dict[str, str]] | None = [] if verbose_assets else None

        # Build enricher pipeline for this container (ingest scope)
        # Read from persisted Enricher instances referenced by container.config['enrichers']
        pipeline: list[tuple[str, int, Any]] = []  # (enricher_id, priority, instance)
        pipeline_signature: list[dict[str, Any]] = []
        try:
            cfg = dict(getattr(container, "config", {}) or {})
            configured = cfg.get("enrichers", []) if isinstance(cfg.get("enrichers"), list) else []
            # Load DB-backed enricher config for proper instantiation
            from ..domain.entities import Enricher as EnricherRow

            for entry in configured:
                try:
                    enricher_id = entry.get("enricher_id") if isinstance(entry, dict) else None
                    priority = int(entry.get("priority", 0)) if isinstance(entry, dict) else 0
                    if not enricher_id:
                        continue
                    row = (
                        self.db.query(EnricherRow)
                        .filter(EnricherRow.enricher_id == enricher_id)
                        .first()
                    )
                    if not row or getattr(row, "scope", "ingest") != "ingest":
                        continue
                    # Instantiate enricher by type with stored config
                    cls = ENRICHERS.get(row.type)
                    instance = cls(**(row.config or {})) if cls else None
                    if instance is None:
                        continue
                    pipeline.append((enricher_id, priority, instance))
                except Exception:
                    continue
            # Stable order by priority, then id
            pipeline.sort(key=lambda t: (t[1], t[0]))
            pipeline_signature = [{"enricher_id": eid, "priority": pr} for (eid, pr, _) in pipeline]
        except Exception:
            pipeline = []
            pipeline_signature = []

        # INV-INTERSTITIAL-TYPE-STAMP-001: Auto-inject InterstitialTypeEnricher
        # for filesystem containers whose name appears in the canonical mapping.
        # This ensures every asset gets interstitial_type stamped from the
        # container name, regardless of manually configured enrichers.
        try:
            from ..adapters.enrichers.interstitial_type_enricher import (
                COLLECTION_TYPE_MAP,
                InterstitialTypeEnricher,
            )
            coll_name = getattr(container, "name", "") or ""
            if coll_name in COLLECTION_TYPE_MAP:
                it_enricher = InterstitialTypeEnricher(collection_name=coll_name)
                # Prepend at priority -1 so it runs before any other enrichers
                pipeline.insert(0, ("interstitial-type", -1, it_enricher))
                pipeline_signature.insert(0, {
                    "enricher_id": "interstitial-type",
                    "priority": -1,
                })
        except Exception as _ite_exc:
            logger.warning(
                "interstitial_type_enricher_injection_failed",
                container=getattr(container, "name", "?"),
                error=str(_ite_exc),
            )

        # Compute a stable checksum for the pipeline
        import json as _json
        from hashlib import sha256 as _sha256

        pipeline_checksum = None
        try:
            sig_bytes = _json.dumps(pipeline_signature, sort_keys=True).encode("utf-8")
            pipeline_checksum = _sha256(sig_bytes).hexdigest()
        except Exception:
            pipeline_checksum = None

        # (1) Discover — single source of "what was discovered" (ContainerDiscoveryContract).
        try:
            discovery_result = discover_locators(
                container,
                importer,
                title=title,
                season=season,
                episode=episode,
            )
        except Exception as e:
            raise RuntimeError(f"Importer discovery failed: {e}") from e

        stats.assets_discovered = len(discovery_result or [])
        discovered_locators = [d for d, _ in discovery_result or []]
        item_by_hash = {
            canonical_hash(d.locator): item for d, item in (discovery_result or [])
        }

        # Get provider name from importer
        provider = getattr(importer, "name", None) if importer else None

        # (2) Detect sidecars — leave for apply step (no-op here).
        # (3) Compare — load current catalog state for this container.
        catalog_state = load_catalog_state_for_container(self.db, container.uuid)
        # (4) Determine outcome — create | update | no_action | mark_unavailable.
        outcomes = determine_reconciliation_outcomes(
            discovered_locators,
            catalog_state,
            full_container_scope=(scope == "container"),
        )
        processor_ids_for_enqueue = [eid for eid, _, _ in pipeline]

        # Preload path mappings for this container to resolve local paths before enrichment
        path_mappings: list[tuple[str, str]] = []
        try:
            from ..domain.entities import PathMapping as _PathMapping

            rows = (
                self.db.query(_PathMapping).filter(_PathMapping.container_id == container.uuid).all()
            )
            for pm in rows:
                plex_p = getattr(pm, "plex_path", "") or ""
                local_p = getattr(pm, "local_path", "") or ""
                if plex_p and local_p:
                    # Normalize slashes for comparison; keep original local path
                    path_mappings.append((plex_p.replace("\\", "/"), local_p))
        except Exception:
            path_mappings = []

        

        def _get_uri(item: Any) -> str | None:
            if isinstance(item, dict):
                return (
                    item.get("path_uri")
                    or item.get("uri")
                    or item.get("path")
                    or item.get("external_id")
                )
            return getattr(item, "path_uri", None)

        def _get_size(item: Any) -> int:
            if isinstance(item, dict):
                size_val = item.get("size", 0)
                return int(size_val) if size_val is not None else 0
            size_val = getattr(item, "size", 0)
            return int(size_val) if size_val is not None else 0

        def _get_enricher_checksum(item: Any) -> str | None:
            if isinstance(item, dict):
                return item.get("enricher_checksum") or item.get("last_enricher_checksum")
            return getattr(item, "enricher_checksum", None)

        def _extract_label_value(labels: list[str] | None, key: str) -> str | None:
            """Extract a value from raw_labels in the form key:value."""
            if not labels:
                return None
            prefix = f"{key}:"
            for label in labels:
                if isinstance(label, str) and label.startswith(prefix):
                    return label[len(prefix) :]
            return None

        # Default thresholds (may be overridden by CLI in future)
        auto_ready_threshold: float = 0.80
        review_threshold: float = 0.50

        # Maximum movie duration for auto-ready (3 hours in ms)
        MAX_MOVIE_DURATION_MS = 3 * 60 * 60 * 1000

        def _compute_confidence(it: Any) -> float:
            score = 0.0
            try:
                size_ok = _get_size(it) > 0
                if size_ok:
                    score += 0.2
                labels = getattr(it, "raw_labels", None) if not isinstance(it, dict) else it.get("raw_labels")
                # Lightweight features
                dur = _extract_label_value(labels, "duration_ms")
                dur_ms = 0
                if dur is not None:
                    try:
                        dur_ms = int(dur)
                        if dur_ms > 0:
                            score += 0.3
                    except Exception:
                        pass
                if _extract_label_value(labels, "video_codec") is not None:
                    score += 0.2
                if _extract_label_value(labels, "audio_codec") is not None:
                    score += 0.1
                if _extract_label_value(labels, "container") is not None:
                    score += 0.1

                # Editorial-based confidence boost
                editorial = it.get("editorial") if isinstance(it, dict) else getattr(it, "editorial", None)
                if editorial and isinstance(editorial, dict):
                    has_series = bool(editorial.get("series_title"))
                    has_season = editorial.get("season_number") is not None
                    has_episode = editorial.get("episode_number") is not None
                    has_title = bool(editorial.get("title"))

                    if has_series and has_season and has_episode:
                        # TV episode with full metadata
                        score += 0.2
                    elif has_title and not has_series:
                        # Movie: title + duration required, duration must be < 3 hours
                        if dur_ms > 0 and dur_ms <= MAX_MOVIE_DURATION_MS:
                            score += 0.2
                        elif dur_ms > MAX_MOVIE_DURATION_MS:
                            # Suspiciously long for a movie — needs review
                            score -= 0.2
            except Exception:
                pass
            # Clamp 0..1
            if score < 0.0:
                return 0.0
            if score > 1.0:
                return 1.0
            return score

        # (5) Apply — for each outcome: create (full path), update (fingerprint + enqueue), no_action, mark_unavailable.
        for loc, outcome, existing_asset in outcomes:
            if outcome == ReconciliationOutcome.mark_unavailable and existing_asset is not None:
                if not dry_run:
                    existing_asset.is_deleted = True
                    existing_asset.deleted_at = datetime.now(UTC)
                    existing_asset.state = "retired"
                    existing_asset.approved_for_broadcast = False
                stats.assets_removed += 1
                logger.info(
                    "asset_marked_unavailable",
                    asset_uuid=str(existing_asset.uuid),
                    uri=existing_asset.uri,
                    container=container.name,
                )
                continue
            if outcome == ReconciliationOutcome.no_action and existing_asset is not None:
                stats.assets_skipped += 1
                continue
            if outcome == ReconciliationOutcome.update and existing_asset is not None and loc is not None:
                if loc.fingerprint:
                    existing_asset.file_size = loc.fingerprint.size
                    existing_asset.file_mtime = loc.fingerprint.mtime
                enqueue_processor_jobs(
                    [existing_asset.uuid],
                    processor_ids_for_enqueue,
                    db=self.db,
                )
                stats.assets_updated += 1
                continue
            if outcome != ReconciliationOutcome.create or loc is None:
                continue

            # Create path: path resolution, handle_ingest, persist, enqueue.
            item = item_by_hash.get(canonical_hash(loc.locator))
            if item is None:
                continue
            # Capture source_uri before any local resolution
            try:
                source_uri_val = _get_uri(item)
            except Exception:
                source_uri_val = None
            # Resolve local file URI for enrichment via AssetPathResolver
            try:
                container_locations = (container.config or {}).get("locations", [])
                plex_client = getattr(importer, "client", None)
                resolver = AssetPathResolver(
                    path_mappings=path_mappings,
                    plex_client=plex_client,
                    container_locations=container_locations,
                )
                local_path = resolver.resolve(
                    uri=_get_uri(item) or "",
                )
                if isinstance(local_path, str) and local_path:
                    try:
                        if isinstance(item, dict):
                            item["path_uri"] = local_path
                        else:
                            item.path_uri = local_path
                    except Exception:
                        pass
            except Exception:
                pass
            # Snapshot importer editorial (importer output only; workers enrich later)
            try:
                try:
                    importer_editorial = (
                        item.get("editorial") if isinstance(item, dict) else getattr(item, "editorial", None)
                    )
                except Exception:
                    importer_editorial = None
            except Exception:
                importer_editorial = None

            # Enrichment is performed by workers via processor job queue; no inline pipeline.

            # Build payload for unified metadata handler (importer output only)
            try:
                asset_type_val = None
                try:
                    if isinstance(item, dict):
                        asset_type_val = item.get("asset_type")
                    else:
                        asset_type_val = getattr(item, "asset_type", None)
                except Exception:
                    asset_type_val = None

                # Editorial from importer (workers add processor metadata later)
                try:
                    enriched_editorial = (
                        item.get("editorial") if isinstance(item, dict) else getattr(item, "editorial", None)
                    )
                except Exception:
                    enriched_editorial = None

                # Debug output removed

                # If both are missing, derive a minimal editorial from labels
                editorial_val = enriched_editorial or importer_editorial
                if editorial_val is None:
                    try:
                        labels = item.get("raw_labels") if isinstance(item, dict) else getattr(item, "raw_labels", None)
                        if labels:
                            ed: dict[str, Any] = {}
                            for lbl in labels:
                                if not isinstance(lbl, str):
                                    continue
                                if lbl.startswith("title:"):
                                    ed["title"] = lbl.split(":", 1)[1]
                                elif lbl.startswith("year:"):
                                    val = lbl.split(":", 1)[1]
                                    try:
                                        ed["production_year"] = int(val)
                                    except Exception:
                                        pass
                                elif lbl.startswith("season:"):
                                    val = lbl.split(":", 1)[1]
                                    try:
                                        ed["season_number"] = int(val)
                                    except Exception:
                                        pass
                                elif lbl.startswith("episode:"):
                                    val = lbl.split(":", 1)[1]
                                    try:
                                        ed["episode_number"] = int(val)
                                    except Exception:
                                        pass
                                elif lbl.startswith("library:"):
                                    ed["library_name"] = lbl.split(":", 1)[1]
                            editorial_val = ed if ed else None
                    except Exception:
                        pass

                # Probe and sidecars from importer (workers add processor output later)
                try:
                    probed_val = item.get("probed") if isinstance(item, dict) else getattr(item, "probed", None)
                except Exception:
                    probed_val = None

                sidecars_val = []
                try:
                    if isinstance(item, dict):
                        if item.get("sidecars"):
                            sidecars_val = item.get("sidecars") or []
                        elif item.get("sidecar"):
                            sidecars_val = [item.get("sidecar")]
                    else:
                        scs = getattr(item, "sidecars", None)
                        if scs:
                            sidecars_val = list(scs)
                        else:
                            sc = getattr(item, "sidecar", None)
                            if sc:
                                sidecars_val = [sc]
                except Exception:
                    sidecars_val = []

                # Optional sections that enrichers or importers may provide
                try:
                    station_ops_val = (
                        item.get("station_ops") if isinstance(item, dict) else getattr(item, "station_ops", None)
                    )
                except Exception:
                    station_ops_val = None
                try:
                    relationships_val = (
                        item.get("relationships") if isinstance(item, dict) else getattr(item, "relationships", None)
                    )
                except Exception:
                    relationships_val = None
                try:
                    source_payload_val = (
                        item.get("source_payload") if isinstance(item, dict) else getattr(item, "source_payload", None)
                    )
                except Exception:
                    source_payload_val = None

                payload = {
                    "importer_name": getattr(importer, "name", None) or getattr(importer, "__class__", type("", (), {})) .__name__,
                    "asset_type": asset_type_val or scope,
                    "source_uri": source_uri_val or _get_uri(item) or "",
                    "editorial": editorial_val,
                    "importer_editorial": importer_editorial,
                    "probed": probed_val,
                    "sidecars": sidecars_val,
                    "station_ops": station_ops_val or {},
                    "relationships": relationships_val or {},
                    "source_payload": source_payload_val or {},
                }
                # NOTE:
                # At this point, importer + enrichers may both have added metadata.
                # The handler must MERGE (not replace) editorial/probed/sidecars.
                ingest_result = handle_ingest(payload)

                # Optionally honor canonical_uri from handler if provided
                try:
                    if isinstance(ingest_result, dict):
                        handler_curi = ingest_result.get("canonical_uri")
                        canonical_uri_override = handler_curi if handler_curi else None
                    else:
                        canonical_uri_override = None
                except Exception:
                    canonical_uri_override = None

                # Prefer handler-resolved sections from handler; fallback to our computed
                try:
                    handler_editorial = (
                        (ingest_result.get("resolved_fields") or {}).get("editorial")
                        if isinstance(ingest_result, dict)
                        else {}
                    ) or (ingest_result.get("editorial") if isinstance(ingest_result, dict) else {}) or {}
                    merged_editorial = handler_editorial or (editorial_val or {})
                    handler_resolved_fields = (
                        ingest_result.get("resolved_fields") if isinstance(ingest_result, dict) else {}
                    ) or {}
                except Exception:
                    merged_editorial = editorial_val or {}
                    handler_resolved_fields = {}
            except ValueError as ve:
                # Validation error (e.g., bad sidecar) — record and skip this item
                stats.errors.append(str(ve))
                continue
            except Exception:
                # Non-fatal: proceed with legacy path
                canonical_uri_override = None
            try:
                canonical_key = canonical_key_for(item, container=container, provider=provider)
                canonical_key_hash = canonical_hash(canonical_key)
            except IngestError as e:
                stats.errors.append(str(e))
                continue

            # Duplicate check: same canonical_key_hash may appear from multiple items; only create once.
            # If the existing row is soft-deleted (removed from source then re-added), restore it and enqueue.
            existing = repo.get_by_container_and_canonical_hash(
                container.uuid, canonical_key_hash
            )
            if existing is not None:
                if getattr(existing, "is_deleted", False):
                    if not dry_run:
                        existing.is_deleted = False
                        existing.deleted_at = None
                        existing.state = "new"
                        existing.approved_for_broadcast = False
                        if loc and getattr(loc, "fingerprint", None):
                            if loc.fingerprint.size is not None:
                                existing.file_size = loc.fingerprint.size
                            if loc.fingerprint.mtime is not None:
                                existing.file_mtime = loc.fingerprint.mtime
                        enqueue_processor_jobs(
                            [existing.uuid],
                            processor_ids_for_enqueue,
                            db=self.db,
                        )
                    stats.assets_ingested += 1
                    logger.info(
                        "asset_restored",
                        asset_uuid=str(existing.uuid),
                        uri=getattr(existing, "uri", None),
                        container=container.name,
                    )
                else:
                    stats.assets_skipped += 1
                continue

            if max_new is not None and stats.assets_ingested >= max_new:
                stats.errors.append("ingest aborted: max_new exceeded")
                break

            # Persist values for verbose output
            # If the source provides a file path (e.g. plex_file_path label),
            # use it as canonical_uri so the runtime can resolve via PathMappings
            # without needing to call the source API at runtime.
            source_file_path = _extract_label_value(
                getattr(item, "raw_labels", None) if not isinstance(item, dict) else item.get("raw_labels"),
                "plex_file_path",
            )
            canonical_uri_val = (
                canonical_uri_override
                or source_file_path
                or _get_uri(item)
                or canonical_key
            )
            size_val = _get_size(item)

            confidence_val = _compute_confidence(item)

            # INV-ASSET-APPROVAL-OPERATOR-ONLY-001: All new assets start in
            # state="new" with approved_for_broadcast=False.  Confidence is
            # informational only — it MUST NOT drive lifecycle or approval.
            initial_state = "new"
            initial_approved = False

            # Bucket for reporting (informational, no lifecycle effect)
            if confidence_val >= auto_ready_threshold:
                stats.assets_auto_ready += 1
            elif confidence_val >= review_threshold:
                stats.assets_needs_enrichment += 1
            else:
                stats.assets_needs_review += 1

            source_id = getattr(container, "source_id", None)
            if source_id is None:
                raise ValueError("container must have source_id for asset creation")
            file_size = loc.fingerprint.size if loc and loc.fingerprint else size_val
            file_mtime = loc.fingerprint.mtime if loc and loc.fingerprint else None
            asset = Asset(
                uuid=uuid.uuid4(),
                container_id=container.uuid,
                source_id=source_id,
                canonical_key=canonical_key,
                canonical_key_hash=canonical_key_hash,
                uri=source_uri_val or canonical_uri_val,
                canonical_uri=canonical_uri_val,
                size=size_val,
                state=initial_state,
                approved_for_broadcast=initial_approved,
                operator_verified=False,
                discovered_at=datetime.now(UTC),
                file_size=file_size,
                file_mtime=file_mtime,
            )
            # Populate optional incoming fields when creating a new asset
            incoming_enricher = _get_enricher_checksum(item)
            if incoming_enricher is not None:
                asset.last_enricher_checksum = incoming_enricher
            # Map common enricher-derived labels onto asset fields
            try:
                labels = getattr(item, "raw_labels", None)
                if labels is None and isinstance(item, dict):
                    labels = item.get("raw_labels")

                duration_val = _extract_label_value(labels, "duration_ms")
                if duration_val is not None:
                    try:
                        asset.duration_ms = int(duration_val)
                    except Exception:
                        pass
                video_codec_val = _extract_label_value(labels, "video_codec")
                if video_codec_val is not None:
                    asset.video_codec = video_codec_val
                audio_codec_val = _extract_label_value(labels, "audio_codec")
                if audio_codec_val is not None:
                    asset.audio_codec = audio_codec_val
                container_val = _extract_label_value(labels, "container")
                if container_val is not None:
                    asset.container_format = container_val
            except Exception:
                pass
            # When ffprobe (or other enricher) provides duration in probed but not in labels, set asset.duration_ms
            if asset.duration_ms is None:
                try:
                    rf = handler_resolved_fields if isinstance(handler_resolved_fields, dict) else {}
                    probed = rf.get("probed") or {}
                    dm = probed.get("duration_ms")
                    if dm is not None:
                        asset.duration_ms = int(dm)
                except Exception:
                    pass
            # Persist when not a dry run
            if not dry_run:
                repo.create(asset)
                # Persist tags from raw_labels (tag: prefix) into asset_tags table.
                # INV-ASSET-TAG-PERSISTENCE-001: tags MUST live in asset_tags, not only JSONB.
                try:
                    from ..domain.entities import AssetTag
                    from ..domain.tag_normalization import normalize_tag_set
                    tag_labels: list[str] = []
                    if labels:
                        tag_labels = [
                            lbl[len("tag:"):]
                            for lbl in labels
                            if isinstance(lbl, str) and lbl.startswith("tag:")
                        ]
                    if tag_labels:
                        for tag_val in normalize_tag_set(tag_labels):
                            # INV-ASSET-TAG-FORMAT-001: tags stored as CATEGORY:value
                            namespaced = tag_val if ":" in tag_val else f"TAG:{tag_val}"
                            self.db.merge(
                                AssetTag(
                                    asset_uuid=asset.uuid,
                                    tag=namespaced,
                                    source="ingest",
                                )
                            )
                except Exception as tag_exc:
                    stats.errors.append(f"tag persistence failed: {tag_exc}")
                # <-- write handler output into child tables
                try:
                    if isinstance(ingest_result, dict):
                        rf = handler_resolved_fields if isinstance(handler_resolved_fields, dict) else {}
                        persist_asset_metadata(
                            self.db,
                            asset,
                            editorial=ingest_result.get("editorial"),
                            probed=rf.get("probed"),
                            station_ops=rf.get("station_ops"),
                            relationships=rf.get("relationships"),
                            sidecar=rf.get("sidecar"),
                        )
                except Exception as meta_exc:
                    stats.errors.append(f"metadata persistence failed: {meta_exc}")
                # Force a flush so upstream callers can verify within the same transaction
                try:
                    self.db.flush()
                except Exception:
                    # Allow upstream to surface; we keep stats consistent with actual persistence
                    raise
                # (6) Enqueue — after create, stub enqueue for Phase 3.
                enqueue_processor_jobs(
                    [asset.uuid],
                    processor_ids_for_enqueue,
                    db=self.db,
                )
            stats.assets_ingested += 1
            if created_assets is not None:
                asset_record = {
                    "uuid": str(asset.uuid),
                    "source_uri": source_uri_val or "",
                    "canonical_uri": canonical_uri_val,
                    "state": asset.state,
                    "approved_for_broadcast": asset.approved_for_broadcast,
                    "confidence": confidence_val,
                    # Expose merged editorial (importer + sidecar + enrichers + ops)
                    "editorial": merged_editorial,
                }
                try:
                    if handler_resolved_fields:
                        if handler_resolved_fields.get("probed"):
                            asset_record["probed"] = handler_resolved_fields.get("probed")
                        if handler_resolved_fields.get("station_ops"):
                            asset_record["station_ops"] = handler_resolved_fields.get("station_ops")
                        if handler_resolved_fields.get("relationships"):
                            asset_record["relationships"] = handler_resolved_fields.get("relationships")
                        # Surface sidecar as sidecars for output consistency
                        if handler_resolved_fields.get("sidecar"):
                            asset_record["sidecars"] = handler_resolved_fields.get("sidecar")
                except Exception:
                    pass
                created_assets.append(asset_record)

        result = ContainerIngestResult(
            container_id=str(container.uuid),
            container_name=container.name,
            scope=scope,
            stats=stats,
            title=title,
            season=season,
            episode=episode,
            created_assets=created_assets,
            updated_assets=updated_assets,
            thresholds={"auto_ready": auto_ready_threshold, "review": review_threshold},
            enqueued_processors=processor_ids_for_enqueue if (stats.assets_ingested or stats.assets_updated) else None,
        )

        return result

def refresh_container(
    db: Session,
    container: Container,
    importer: Any,
    **kwargs: Any,
) -> ContainerIngestResult:
    """
    Refresh a container: run discovery + reconciliation + enqueue (no persistence of container metadata).

    Pipeline: discover locators → determine_reconciliation_outcomes → apply (create/update/mark_unavailable) → enqueue processor jobs.
    Use this when the scheduler or a batch worker needs to refresh a single container before horizon expansion.
    """
    return ContainerIngestService(db).ingest_container(container=container, importer=importer, **kwargs)


