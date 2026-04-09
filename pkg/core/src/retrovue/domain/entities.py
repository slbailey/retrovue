"""
Domain entities for Retrovue.

This module contains the core business entities that represent the domain model.
These entities are independent of any external concerns and contain pure business logic.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ..infra.db import Base
from ..shared.types import (
    EntityType,
    MarkerKind,
    Provider,
    ReviewStatus,
    TitleKind,
)


# NOTE: Title/Season/Episode tables have been dropped - these classes are deprecated
# Series/episode data is stored in asset_editorial.payload instead
# These classes are kept for reference only and should not be used
class Title(Base):
    """
    DEPRECATED: Title table has been dropped.
    
    Represents a title (movie or show) in the content library.
    Series/episode data is now stored in asset_editorial.payload (JSONB).
    This class is kept for reference only and should not be used.
    """

    __tablename__ = "titles"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    kind: Mapped[TitleKind] = mapped_column(SQLEnum(TitleKind), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_ids: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships removed - Title table is being dropped
    # Series/episode data is stored in asset_editorial.payload instead

    def __repr__(self) -> str:
        return f"<Title(id={self.id}, kind={self.kind}, name={self.name}, year={self.year})>"


# NOTE: Season table has been dropped
class Season(Base):
    """
    DEPRECATED: Season table has been dropped.
    
    Represents a season of a show.
    Series/episode data is now stored in asset_editorial.payload (JSONB).
    This class is kept for reference only and should not be used.
    """

    __tablename__ = "seasons"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    title_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("titles.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships removed - Season table is being dropped

    def __repr__(self) -> str:
        return f"<Season(id={self.id}, title_id={self.title_id}, number={self.number})>"


# NOTE: Episode table has been dropped
class Episode(Base):
    """
    DEPRECATED: Episode table has been dropped.
    
    Represents an episode of a show or a movie.
    Series/episode data is now stored in asset_editorial.payload (JSONB).
    This class is kept for reference only and should not be used.
    """

    __tablename__ = "episodes"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    title_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("titles.id", ondelete="CASCADE"), nullable=False
    )
    season_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=True
    )
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_ids: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships removed - Episode table is being dropped
    # Series/episode data is stored in asset_editorial.payload instead

    def __repr__(self) -> str:
        return f"<Episode(id={self.id}, title_id={self.title_id}, season_id={self.season_id}, number={self.number}, name={self.name})>"


_LEGAL_STATE_TRANSITIONS: dict[str, set[str]] = {
    "new": {"enriching", "retired"},
    "enriching": {"ready", "new", "retired"},
    "ready": {"retired"},
    "retired": set(),
}


def validate_state_transition(current_state: str, new_state: str) -> None:
    """Validate an asset state transition against the legal state machine.

    Raises ValueError with INV-ASSET-STATE-MACHINE-001-VIOLATED if the
    transition is not permitted.
    """
    if current_state == new_state:
        return
    allowed = _LEGAL_STATE_TRANSITIONS.get(current_state, set())
    if new_state not in allowed:
        raise ValueError(
            f"INV-ASSET-STATE-MACHINE-001-VIOLATED: "
            f"illegal state transition {current_state!r} -> {new_state!r}"
        )


def validate_marker_bounds(
    start_ms: int, end_ms: int, asset_duration_ms: int
) -> None:
    """Validate marker timestamps are within asset duration bounds.

    Raises ValueError with INV-ASSET-MARKER-BOUNDS-001-VIOLATED if the
    marker timestamps are outside [0, asset_duration_ms].
    """
    if start_ms < 0:
        raise ValueError(
            f"INV-ASSET-MARKER-BOUNDS-001-VIOLATED: "
            f"start_ms={start_ms} is negative"
        )
    if end_ms > asset_duration_ms:
        raise ValueError(
            f"INV-ASSET-MARKER-BOUNDS-001-VIOLATED: "
            f"end_ms={end_ms} exceeds asset duration {asset_duration_ms}"
        )


class Asset(Base):
    """Represents a media asset (file) in the system."""

    __tablename__ = "assets"

    uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4, nullable=False
    )
    container_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("containers.uuid", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)  # size in bytes
    state: Mapped[str] = mapped_column(
        SQLEnum("new", "enriching", "ready", "retired", name="asset_state"),
        nullable=False,
        comment="Asset lifecycle state: new, enriching, ready, retired",
    )
    approved_for_broadcast: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa.text("false"),
        nullable=False,
        comment="Asset approval status for broadcast. Must be true when state='ready'.",
    )
    operator_verified: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa.text("false"),
        nullable=False,
        comment="Asset approval status for downstream schedulers and runtime. "
        "True = approved for playout without human review. "
        "False = exists in inventory but not yet approved; may be in review_queue.",
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    container_format: Mapped[str | None] = mapped_column("container", String(50), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.text("false"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_enricher_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Fingerprint for reconciliation (compare with discovered size/mtime)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_mtime: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    # Episode relationship removed - episodes table is being dropped
    # Series/episode data is stored in asset_editorial.payload instead
    markers: Mapped[list[Marker]] = relationship(
        "Marker", back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
    container: Mapped[Container | None] = relationship("Container", passive_deletes=True)
    review_queue: Mapped[list[ReviewQueue]] = relationship(
        "ReviewQueue", back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
    provider_refs: Mapped[list[ProviderRef]] = relationship("ProviderRef", back_populates="asset")

    # Tags (many-to-one normalized association — INV-ASSET-TAG-PERSISTENCE-001)
    tags: Mapped[list[AssetTag]] = relationship(
        "AssetTag", back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )

    # Metadata child tables (one-to-one, cascade delete via FK)
    editorial_meta: Mapped[AssetEditorial | None] = relationship(
        "AssetEditorial", uselist=False, back_populates="asset", cascade="all, delete-orphan"
    )
    probed_meta: Mapped[AssetProbed | None] = relationship(
        "AssetProbed", uselist=False, back_populates="asset", cascade="all, delete-orphan"
    )
    station_ops_meta: Mapped[AssetStationOps | None] = relationship(
        "AssetStationOps", uselist=False, back_populates="asset", cascade="all, delete-orphan"
    )
    relationships_meta: Mapped[AssetRelationships | None] = relationship(
        "AssetRelationships", uselist=False, back_populates="asset", cascade="all, delete-orphan"
    )
    sidecar_meta: Mapped[AssetSidecar | None] = relationship(
        "AssetSidecar", uselist=False, back_populates="asset", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Uniques
        UniqueConstraint(
            "container_id", "canonical_key_hash", name="ix_assets_container_canonical_unique"
        ),
        UniqueConstraint("container_id", "uri", name="ix_assets_container_uri_unique"),
        UniqueConstraint(
            "source_id", "container_id", "uri", name="uq_assets_source_container_locator"
        ),
        # Checks
        CheckConstraint(
            "(NOT approved_for_broadcast) OR (state = 'ready')", name="chk_approved_implies_ready"
        ),
        CheckConstraint(
            "(is_deleted = TRUE AND deleted_at IS NOT NULL) OR (is_deleted = FALSE AND deleted_at IS NULL)",
            name="chk_deleted_at_sync",
        ),
        CheckConstraint("char_length(canonical_key_hash) = 64", name="chk_canon_hash_len"),
        CheckConstraint("canonical_key_hash ~ '^[0-9a-f]{64}$'", name="chk_canon_hash_hex"),
        # Indexes
        Index("ix_assets_container_id", "container_id"),
        Index("ix_assets_state", "state"),
        Index("ix_assets_approved", "approved_for_broadcast"),
        Index("ix_assets_operator_verified", "operator_verified"),
        Index("ix_assets_discovered_at", "discovered_at"),
        Index("ix_assets_is_deleted", "is_deleted"),
        Index("ix_assets_container_canonical_uri", "container_id", "canonical_uri"),
        # Partial schedulable index (hot path)
        Index(
            "ix_assets_schedulable",
            "container_id",
            "discovered_at",
            postgresql_where=sa.text(
                "state = 'ready' AND approved_for_broadcast = true AND is_deleted = false"
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<Asset(uuid={self.uuid}, uri={self.uri}, size={self.size}, state={self.state}, approved_for_broadcast={self.approved_for_broadcast})>"


class ProcessorJob(Base):
    """Processor job queue: one row per (target_type, target_id) when pending/running.

    Contract: ProcessorJobQueueContract. Runtime runs all applicable processors for the target.
    """

    __tablename__ = "processor_jobs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid_module.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_processor_jobs_status_priority", "status", "priority"),
    )


class ProcessorRun(Base):
    """Execution history: one row per processor run within a job.

    Contract: ProcessorExecutionContract. Immutable; supports staleness and audit.
    """

    __tablename__ = "processor_runs"

    run_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    job_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("processor_jobs.id", ondelete="CASCADE"), nullable=False
    )
    processor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid_module.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    processor_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_processor_runs_job_id", "job_id"),
        Index("ix_processor_runs_processor_target", "processor_id", "target_type", "target_id"),
    )


class ProcessorOutput(Base):
    """Flexible/processor-specific metadata. One row per (processor_id, target_type, target_id).

    Contract: ProcessorMetadataContract. Runtime upserts from result.flexible.
    """

    __tablename__ = "processor_outputs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    processor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid_module.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_processor_outputs_processor_target", "processor_id", "target_type", "target_id", unique=True),
    )


class EnricherRun(Base):
    """Per-enricher execution record for queryable enricher progress.

    Contract: INV-ENRICHER-OBSERVABILITY-001. One row per enricher per asset per execution.
    Provides per-enricher granularity that ProcessorJob does not expose.

    Status values: pending, running, succeeded, failed.
    """

    __tablename__ = "enricher_runs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    asset_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), nullable=False
    )
    enricher_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enricher_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        PG_JSONB, nullable=True
    )

    __table_args__ = (
        Index("ix_enricher_runs_asset_id", "asset_id"),
        Index("ix_enricher_runs_asset_enricher", "asset_id", "enricher_name"),
        Index("ix_enricher_runs_enricher_version", "enricher_name", "enricher_version"),
    )


class AssetEditorial(Base):
    __tablename__ = "asset_editorial"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    # Indexed columns — metadata consolidation contract (docs/contracts/metadata_consolidation.md)
    series_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_rating: Mapped[str | None] = mapped_column(String(32), nullable=True)
    production_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    asset: Mapped[Asset] = relationship("Asset", back_populates="editorial_meta")

    __table_args__ = (
        Index("ix_asset_editorial_series_title_lower", sa.func.lower(sa.column("series_title"))),
        Index("ix_asset_editorial_season_episode", "season_number", "episode_number"),
        Index("ix_asset_editorial_content_rating", "content_rating"),
        Index("ix_asset_editorial_production_year", "production_year"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sync_columns_from_payload()

    def sync_columns_from_payload(self) -> None:
        """Populate indexed columns from JSONB payload (dual-write rule D-1)."""
        p = self.payload or {}
        self.series_title = p.get("series_title") or None
        raw_season = p.get("season_number")
        self.season_number = int(raw_season) if raw_season is not None else None
        raw_episode = p.get("episode_number")
        self.episode_number = int(raw_episode) if raw_episode is not None else None
        raw_rating = p.get("content_rating")
        if isinstance(raw_rating, dict):
            self.content_rating = raw_rating.get("code")
        else:
            self.content_rating = raw_rating or None
        raw_year = p.get("production_year") or p.get("year")
        self.production_year = int(raw_year) if raw_year is not None else None


class AssetProbed(Base):
    __tablename__ = "asset_probed"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="probed_meta")


class AssetStationOps(Base):
    __tablename__ = "asset_station_ops"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="station_ops_meta")


class AssetRelationships(Base):
    __tablename__ = "asset_relationships"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="relationships_meta")


class AssetSidecar(Base):
    __tablename__ = "asset_sidecar"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="sidecar_meta")


class AssetTag(Base):
    """Normalized tag association for an asset.

    Tags are persisted here — not in JSONB payloads — so they are queryable.
    See: INV-ASSET-TAG-PERSISTENCE-001, AssetTaggingContract.md D-1/D-2.
    """

    __tablename__ = "asset_tags"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("assets.uuid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="operator",
        comment="Provenance: 'ingest', 'operator', or 'enricher'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="tags")

    __table_args__ = (
        Index("ix_asset_tags_asset_uuid", "asset_uuid"),
        Index("ix_asset_tags_tag", "tag"),
    )

    def __repr__(self) -> str:
        return f"<AssetTag(asset_uuid={self.asset_uuid}, tag={self.tag!r}, source={self.source!r})>"


# NOTE: EpisodeAsset table has been dropped
class EpisodeAsset(Base):
    """
    DEPRECATED: EpisodeAsset junction table has been dropped.
    
    Junction table for episodes and assets (many-to-many relationship).
    Series/episode data is now stored in asset_editorial.payload (JSONB).
    This class is kept for reference only and should not be used.
    """

    __tablename__ = "episode_assets"

    episode_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), primary_key=True
    )
    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"<EpisodeAsset(episode_id={self.episode_id}, asset_uuid={self.asset_uuid})>"


class ProviderRef(Base):
    """References to entities in external providers (Plex, Jellyfin, etc.)."""

    __tablename__ = "provider_refs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    entity_type: Mapped[EntityType] = mapped_column(SQLEnum(EntityType), nullable=False)
    entity_id: Mapped[uuid_module.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    provider: Mapped[Provider] = mapped_column(SQLEnum(Provider), nullable=False)
    provider_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Foreign key relationships (polymorphic)
    # Note: title_id and episode_id foreign keys removed - titles/episodes tables dropped
    # Series/episode data is stored in asset_editorial.payload instead
    asset_uuid: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), nullable=True
    )

    # Relationships
    asset: Mapped[Asset | None] = relationship("Asset", back_populates="provider_refs")

    def __repr__(self) -> str:
        return f"<ProviderRef(id={self.id}, entity_type={self.entity_type}, provider={self.provider}, provider_key={self.provider_key})>"


class Marker(Base):
    """Markers placed on assets (chapters, availability windows, etc.)."""

    __tablename__ = "markers"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[MarkerKind] = mapped_column(SQLEnum(MarkerKind), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    asset: Mapped[Asset] = relationship("Asset", back_populates="markers", passive_deletes=True)

    __table_args__ = (
        Index("ix_markers_asset_uuid", "asset_uuid"),
        Index("ix_markers_kind", "kind"),
    )

    def __repr__(self) -> str:
        return f"<Marker(id={self.id}, asset_uuid={self.asset_uuid}, kind={self.kind}, start_ms={self.start_ms}, end_ms={self.end_ms})>"


class ReviewQueue(Base):
    """Items that need human review for quality assurance."""

    __tablename__ = "review_queue"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        SQLEnum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    asset: Mapped[Asset] = relationship(
        "Asset", back_populates="review_queue", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_review_queue_asset_uuid", "asset_uuid"),
        Index("ix_review_queue_status", "status"),
        Index("ix_review_queue_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ReviewQueue(id={self.id}, asset_uuid={self.asset_uuid}, reason={self.reason}, status={self.status})>"


class Source(Base):
    """A content source (e.g., Plex server, filesystem)."""

    __tablename__ = "sources"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    external_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )  # External identifier
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'plex', 'filesystem', etc.
    config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Additional configuration
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    containers: Mapped[list[Container]] = relationship(
        "Container", back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )
    path_mappings: Mapped[list[PathMapping]] = relationship(
        "PathMapping", back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name={self.name}, type={self.type})>"


class Container(Base):
    """Container (ingest/catalog entity). Subdivision of a Source for discovery."""

    __tablename__ = "containers"

    uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    source_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Plex library ID, etc.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sync_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false")
    )
    ingestible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false")
    )
    config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Plex library type, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    source: Mapped[Source] = relationship(
        "Source", back_populates="containers", passive_deletes=True
    )
    path_mappings: Mapped[list[PathMapping]] = relationship(
        "PathMapping", back_populates="container", cascade="all, delete-orphan"
    )
    assets: Mapped[list[Asset]] = relationship("Asset", passive_deletes=True, overlaps="container")

    __table_args__ = (
        Index("ix_containers_source_id", "source_id"),
        Index("ix_containers_sync_enabled", "sync_enabled"),
        Index("ix_containers_ingestible", "ingestible"),
        UniqueConstraint("source_id", "external_id", name="uq_containers_source_external"),
    )

    def __repr__(self) -> str:
        return f"<Container(uuid={self.uuid}, source_id={self.source_id}, name={self.name}, sync_enabled={self.sync_enabled}, ingestible={self.ingestible})>"


class PathMapping(Base):
    """Path mapping: source_path -> retrovue_path.

    Mappings may be scoped to a source (source_id set, container_id NULL) or
    to a container (container_id set).  Container-level overrides take
    precedence per-prefix over inherited source-level mappings.

    INV-PATH-MAPPING-SOURCE-SCOPED-001.
    """

    __tablename__ = "path_mappings"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    source_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=True
    )
    container_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("containers.uuid", ondelete="CASCADE"), nullable=True
    )
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    retrovue_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    source: Mapped[Source | None] = relationship(
        "Source", back_populates="path_mappings", passive_deletes=True
    )
    container: Mapped[Container | None] = relationship(
        "Container", back_populates="path_mappings", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_path_mappings_container_id", "container_id"),
        Index("ix_path_mappings_source_id", "source_id"),
        CheckConstraint(
            "source_id IS NOT NULL OR container_id IS NOT NULL",
            name="ck_path_mappings_scope",
        ),
    )

    def __repr__(self) -> str:
        return f"<PathMapping(id={self.id}, source_id={self.source_id}, container_id={self.container_id}, source_path={self.source_path}, retrovue_path={self.retrovue_path})>"


class Channel(Base):
    """Channel model for scheduling."""

    __tablename__ = "channels"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    grid_block_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        SQLEnum("network", "premium", "specialty", name="channel_kind", native_enum=True),
        nullable=False,
    )
    programming_day_start: Mapped[dt_time] = mapped_column(Time(timezone=False), nullable=False)
    block_start_offsets_minutes: Mapped[dict[str, Any] | list[int]] = mapped_column(
        PG_JSONB, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("slug", name="ix_channels_slug"),
    )

    def __repr__(self) -> str:
        return f"<Channel(id={self.id}, slug={self.slug}, title={self.title})>"


class Enricher(Base):
    """Enricher model for storing configured enricher instances."""

    __tablename__ = "enrichers"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    enricher_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )  # Format: "enricher-{type}-{hash}"
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # "ingest" or "playout"
    scope: Mapped[str] = mapped_column(String(50), nullable=False)  # "ingest" or "playout"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    protected_from_removal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # Operational criticality flag
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_enrichers_type", "type"),
        Index("ix_enrichers_scope", "scope"),
        Index("ix_enrichers_enricher_id", "enricher_id"),
        Index("ix_enrichers_protected", "protected_from_removal"),
    )

    def __repr__(self) -> str:
        return f"<Enricher(id={self.id}, enricher_id={self.enricher_id}, type={self.type}, scope={self.scope}, name={self.name}, protected={self.protected_from_removal})>"


class ProgramLogDay(Base):
    """Program schedule cache: compiled schedule for a channel/broadcast-day pair.

    DB-first: once a row exists with locked=True, the schedule is never
    recompiled unless the row is explicitly deleted (e.g. via rebuild CLI).
    """

    __tablename__ = "program_log_days"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    broadcast_day: Mapped[date] = mapped_column(Date, nullable=False)
    schedule_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    program_log_json: Mapped[dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)
    locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.text("true")
    )
    range_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,  # nullable for backward compat with existing rows
    )
    range_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "broadcast_day", name="uq_program_log_days_channel_day"),
        Index("ix_program_log_days_channel_id", "channel_id"),
        Index("ix_program_log_days_broadcast_day", "broadcast_day"),
        Index("ix_program_log_days_range", "channel_id", "range_start", "range_end"),
    )

    def __repr__(self) -> str:
        return f"<ProgramLogDay(id={self.id}, channel_id={self.channel_id}, broadcast_day={self.broadcast_day}, locked={self.locked})>"


# ═══════════════════════════════════════════════════════════════════════════════
# Schedule Revisions (program_schedule authority snapshots)
# ═══════════════════════════════════════════════════════════════════════════════


class ScheduleRevision(Base):
    """Immutable program schedule authority snapshot for one channel/broadcast_day.

    Lifecycle: draft → active → superseded.
    At most one revision per (channel_id, broadcast_day) may be 'active'
    at any time (enforced by partial unique index in the DB).
    """

    __tablename__ = "schedule_revisions"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    broadcast_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Lifecycle: draft | active | superseded",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", PG_JSONB, nullable=True
    )

    # Relationships
    channel: Mapped[Channel | None] = relationship("Channel", passive_deletes=True)
    items: Mapped[list["ScheduleItem"]] = relationship(
        "ScheduleItem", back_populates="revision", cascade="all, delete-orphan",
        order_by="ScheduleItem.slot_index",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'superseded')",
            name="chk_schedule_revisions_status_valid",
        ),
        Index("ix_schedule_revisions_channel_day", "channel_id", "broadcast_day"),
        # Partial unique index created via raw SQL in migration
        # (SQLAlchemy doesn't natively support partial unique indexes in table_args)
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleRevision(id={self.id}, channel_id={self.channel_id}, "
            f"day={self.broadcast_day}, status={self.status!r})>"
        )


class ScheduleItem(Base):
    """Editorial schedule unit belonging to exactly one ScheduleRevision.

    Does NOT carry channel_id or broadcast_day — those are inherited from
    the parent ScheduleRevision via FK join.  This prevents split-authority
    bugs (item claiming channel B inside revision for channel A).

    Does NOT store execution details (segments, ad breaks, file offsets,
    playlist artifacts). Those belong to PlaylistEvent and ExecutionSegment.
    """

    __tablename__ = "schedule_items"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    schedule_revision_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    container_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    content_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="episode | movie | filler | bumper | promo | station_id",
    )
    window_uuid: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", PG_JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    revision: Mapped[ScheduleRevision | None] = relationship(
        "ScheduleRevision", back_populates="items"
    )

    __table_args__ = (
        UniqueConstraint("schedule_revision_id", "slot_index", name="uq_schedule_items_revision_slot"),
        UniqueConstraint("schedule_revision_id", "start_time", name="uq_schedule_items_revision_start"),
        Index("ix_schedule_items_revision_id", "schedule_revision_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleItem(id={self.id}, revision={self.schedule_revision_id}, "
            f"slot={self.slot_index}, type={self.content_type!r})>"
        )




class ChannelActiveRevision(Base):
    """Direct pointer to active ScheduleRevision for a channel+broadcast_day."""

    __tablename__ = "channel_active_revisions"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    broadcast_day: Mapped[date] = mapped_column(Date, nullable=False)
    schedule_revision_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "broadcast_day", name="uq_channel_active_revisions_channel_day"),
        Index("ix_channel_active_revisions_channel_day", "channel_id", "broadcast_day"),
    )

    def __repr__(self) -> str:
        return (
            "<ChannelActiveRevision(channel_id=%s, day=%s, revision=%s)>"
            % (self.channel_id, self.broadcast_day, self.schedule_revision_id)
        )
# ═══════════════════════════════════════════════════════════════════════════════
# Traffic Management
# ═══════════════════════════════════════════════════════════════════════════════


class TrafficPlayLog(Base):
    """Log of every interstitial played on a channel.

    Used for cooldown enforcement and rotation analytics.
    Keyed by channel_slug to match YAML channel configs.
    """

    __tablename__ = "traffic_play_log"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"),
        nullable=False,
    )
    asset_uri: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    break_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_group: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_traffic_play_log_channel_played", "channel_slug", "played_at"),
        Index("ix_traffic_play_log_channel_asset", "channel_slug", "asset_uuid", "played_at"),
        Index("ix_traffic_play_log_channel_group", "channel_slug", "cooldown_group", "played_at"),
    )

    def __repr__(self) -> str:
        return f"<TrafficPlayLog(channel={self.channel_slug}, asset={self.asset_uri}, played_at={self.played_at})>"


# ═══════════════════════════════════════════════════════════════════════════════
# Playlist Events (Playlog Plan — persisted horizon; see INV-PLAYLOG-PLAN-VS-RUNTIME-001)
# Contract: docs/contracts/runtime/TransmissionLogPersistenceContract.md
# INV-TRAFFIC-LATE-BIND-001
# ═══════════════════════════════════════════════════════════════════════════════


class PlaylistEvent(Base):
    """Playlog Plan row (`playlog_plan`): persisted horizon, not the runtime playlog.

    Written by PlaylistBuilderDaemon after filling ad break placeholders
    with real interstitials. ChannelManager reads these rows and constructs the
    runtime playlog (join-aware segments) for AIR. EvidenceServicer uses rows
    to enrich .asrun logs. See INV-PLAYLOG-PLAN-VS-RUNTIME-001.

    See: docs/contracts/runtime/TransmissionLogPersistenceContract.md
    """

    __tablename__ = "playlist_events"

    block_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, nullable=False
    )
    channel_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    broadcast_day: Mapped[date] = mapped_column(Date, nullable=False)
    start_utc_ms: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    end_utc_ms: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(PG_JSONB, nullable=False)
    window_uuid: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )

    __table_args__ = (
        Index("ix_playlist_events_channel_day", "channel_slug", "broadcast_day"),
        Index("ix_playlist_events_window_uuid", "window_uuid"),
    )

    def __repr__(self) -> str:
        return (
            f"<PlaylistEvent(block_id={self.block_id!r}, "
            f"channel={self.channel_slug!r}, "
            f"day={self.broadcast_day})>"
        )


# =============================================================================
# Serial Episode Progression
# See: docs/contracts/runtime/INV-SERIAL-EPISODE-PROGRESSION.md
# =============================================================================


class SerialRun(Base):
    """
    Persistent serial episode progression record.

    Binds a recurring program placement on a channel timeline to an anchor
    point and progression policy.  Episode selection is a pure computation
    from (anchor, target_date, placement_days) — no runtime counters.

    Placement identity: (channel_id, placement_time, placement_days, content_source_id).
    At most one active run may exist per placement identity (PI-001).
    """

    __tablename__ = "serial_runs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    run_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Operator-facing name (e.g. 'Bonanza Weekday Strip')"
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    placement_time: Mapped[dt_time] = mapped_column(
        Time, nullable=False, comment="Schedule-time HH:MM for this strip"
    )
    placement_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment="7-bit DOW bitmask: bit0=Mon … bit6=Sun. 127=daily, 31=weekday, 96=weekend",
    )
    content_source_id: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Program, collection, or pool identifier"
    )
    content_source_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Type of content source: 'program', 'collection', 'pool'",
    )
    anchor_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When anchor_episode_index airs (day-of-week must match placement_days)",
    )
    anchor_episode_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Index into the ordered episode list at the anchor date",
    )
    progression_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="serial",
        comment="Progression mode: 'serial'",
    )
    wrap_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="wrap",
        comment="Wrap policy: 'wrap', 'hold_last', 'stop'",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", passive_deletes=True)

    __table_args__ = (
        # PI-001: Partial unique index enforced via migration (Alembic)
        # because SQLAlchemy ORM UniqueConstraint does not support WHERE.
        # See: alembic/versions/20260306_create_serial_runs.py
        Index("ix_serial_runs_channel_id", "channel_id"),
        Index("ix_serial_runs_active", "channel_id", "is_active"),
        CheckConstraint(
            "placement_days >= 1 AND placement_days <= 127",
            name="ck_serial_runs_placement_days_range",
        ),
        CheckConstraint(
            "anchor_episode_index >= 0",
            name="ck_serial_runs_anchor_ep_nonneg",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SerialRun(id={self.id}, run_name={self.run_name!r}, "
            f"channel_id={self.channel_id}, "
            f"placement_time={self.placement_time}, "
            f"placement_days={self.placement_days}, "
            f"content_source_id={self.content_source_id!r})>"
        )


class ProgressionRun(Base):
    """Persistent episode progression run record.

    Contract: docs/contracts/episode_progression.md § Progression Run Model

    Binds a recurring program placement to an anchor point, a day-of-week
    pattern, and an exhaustion policy.  Episode selection is a pure
    computation from (anchor_date, target_date, placement_days) — no
    runtime counters.

    Lookup key: (channel_id, run_id) where run_id is unique per channel.
    """

    __tablename__ = "progression_runs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4,
    )
    run_id: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Stable identity — explicit from DSL or derived from placement",
    )
    channel_id: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Channel slug (string, not FK — matches DSL channel identifier)",
    )
    content_source_id: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Pool or program providing episodes",
    )
    anchor_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="Calendar origin for occurrence counting",
    )
    anchor_episode_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
        comment="Episode index at anchor_date (0-based)",
    )
    placement_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment="7-bit DOW bitmask: bit0=Mon … bit6=Sun. 127=daily",
    )
    exhaustion_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="wrap",
        comment="wrap | hold_last | stop",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "placement_days >= 1 AND placement_days <= 127",
            name="ck_progression_runs_placement_days_range",
        ),
        CheckConstraint(
            "anchor_episode_index >= 0",
            name="ck_progression_runs_anchor_ep_nonneg",
        ),
        CheckConstraint(
            "exhaustion_policy IN ('wrap', 'hold_last', 'stop')",
            name="ck_progression_runs_exhaustion_policy_valid",
        ),
        Index("ix_progression_runs_channel_id", "channel_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProgressionRun(run_id={self.run_id!r}, "
            f"channel_id={self.channel_id!r}, "
            f"anchor_date={self.anchor_date}, "
            f"placement_days={self.placement_days})>"
        )


class Pool(Base):
    """Persistent named pool definition for asset matching."""

    __tablename__ = "pools"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_criteria: Mapped[dict[str, Any]] = mapped_column(PG_JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    assignments: Mapped[list[PoolAssignment]] = relationship(
        "PoolAssignment", back_populates="pool", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_pools_name"),
    )

    def __repr__(self) -> str:
        return f"<Pool(id={self.id}, name={self.name})>"


class PoolAssignment(Base):
    """Advisory association between a pool and a channel."""

    __tablename__ = "pool_assignments"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    pool_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pools.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channels.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    pool: Mapped[Pool] = relationship("Pool", back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("pool_id", "channel_id", name="uq_pool_assignments_pool_channel"),
    )
