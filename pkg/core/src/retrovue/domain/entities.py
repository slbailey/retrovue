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


class Asset(Base):
    """Represents a media asset (file) in the system."""

    __tablename__ = "assets"

    uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4, nullable=False
    )
    collection_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collections.uuid", ondelete="RESTRICT"), nullable=False
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
    container: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.text("false"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_enricher_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    collection: Mapped[Collection | None] = relationship("Collection", passive_deletes=True)
    review_queue: Mapped[list[ReviewQueue]] = relationship(
        "ReviewQueue", back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
    provider_refs: Mapped[list[ProviderRef]] = relationship("ProviderRef", back_populates="asset")

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
            "collection_uuid", "canonical_key_hash", name="ix_assets_collection_canonical_unique"
        ),
        UniqueConstraint("collection_uuid", "uri", name="ix_assets_collection_uri_unique"),
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
        Index("ix_assets_collection_uuid", "collection_uuid"),
        Index("ix_assets_state", "state"),
        Index("ix_assets_approved", "approved_for_broadcast"),
        Index("ix_assets_operator_verified", "operator_verified"),
        Index("ix_assets_discovered_at", "discovered_at"),
        Index("ix_assets_is_deleted", "is_deleted"),
        Index("ix_assets_collection_canonical_uri", "collection_uuid", "canonical_uri"),
        # Partial schedulable index (hot path)
        Index(
            "ix_assets_schedulable",
            "collection_uuid",
            "discovered_at",
            postgresql_where=sa.text(
                "state = 'ready' AND approved_for_broadcast = true AND is_deleted = false"
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<Asset(uuid={self.uuid}, uri={self.uri}, size={self.size}, state={self.state}, approved_for_broadcast={self.approved_for_broadcast})>"


class AssetEditorial(Base):
    __tablename__ = "asset_editorial"

    asset_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.uuid", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        PG_JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    asset: Mapped[Asset] = relationship("Asset", back_populates="editorial_meta")


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
    collections: Mapped[list[Collection]] = relationship(
        "Collection", back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name={self.name}, type={self.type})>"


class Collection(Base):
    """A collection within a content source (e.g., Plex library)."""

    __tablename__ = "collections"

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
        "Source", back_populates="collections", passive_deletes=True
    )
    path_mappings: Mapped[list[PathMapping]] = relationship(
        "PathMapping", back_populates="collection", cascade="all, delete-orphan"
    )
    assets: Mapped[list[Asset]] = relationship("Asset", passive_deletes=True, overlaps="collection")

    __table_args__ = (
        Index("ix_collections_source_id", "source_id"),
        Index("ix_collections_sync_enabled", "sync_enabled"),
        Index("ix_collections_ingestible", "ingestible"),
        UniqueConstraint("source_id", "external_id", name="uq_collections_source_external"),
    )

    def __repr__(self) -> str:
        return f"<Collection(uuid={self.uuid}, source_id={self.source_id}, name={self.name}, sync_enabled={self.sync_enabled}, ingestible={self.ingestible})>"


class PathMapping(Base):
    """A path mapping for a collection (Plex path -> local path)."""

    __tablename__ = "path_mappings"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    collection_uuid: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collections.uuid", ondelete="CASCADE"), nullable=False
    )
    plex_path: Mapped[str] = mapped_column(String(500), nullable=False)
    local_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    collection: Mapped[Collection] = relationship(
        "Collection", back_populates="path_mappings", passive_deletes=True
    )

    __table_args__ = (Index("ix_path_mappings_collection_uuid", "collection_uuid"),)

    def __repr__(self) -> str:
        return f"<PathMapping(id={self.id}, collection_uuid={self.collection_uuid}, plex_path={self.plex_path}, local_path={self.local_path})>"


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


class Program(Base):
    """
    Represents a scheduled program in a SchedulePlan.

    Programs define what content runs when within a schedule plan, using
    schedule-time (00:00 to 24:00 relative to programming day) and duration.
    """

    __tablename__ = "programs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("schedule_plans.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[str] = mapped_column(
        String(5), nullable=False, comment="Start time in 'HH:MM' format (schedule-time)"
    )
    duration: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Duration in minutes"
    )
    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of content: 'series', 'asset', 'rule', 'random', 'virtual_package'",
    )
    content_ref: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Content reference (UUID or JSON depending on content_type)"
    )
    label_id: Mapped[uuid_module.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("schedule_plan_labels.id", ondelete="SET NULL"), nullable=True
    )
    episode_policy: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Episode selection policy (e.g., 'sequential', 'seasonal')"
    )
    playback_rules: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Additional playback rules and directives"
    )
    operator_intent: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Operator-defined metadata describing programming intent"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    channel: Mapped[Channel | None] = relationship("Channel", passive_deletes=True)
    # plan relationship would be defined in SchedulePlan model
    # label relationship would be defined in SchedulePlanLabel model

    __table_args__ = (
        Index("ix_programs_channel_id", "channel_id"),
        Index("ix_programs_plan_id", "plan_id"),
        Index("ix_programs_start_time", "plan_id", "start_time"),
        Index("ix_programs_label_id", "label_id"),
    )

    def __repr__(self) -> str:
        return f"<Program(id={self.id}, plan_id={self.plan_id}, start_time={self.start_time}, duration={self.duration}, content_type={self.content_type})>"


class SchedulePlan(Base):
    """
    Represents a schedule plan for a channel.

    Schedule plans define programming patterns using Zones and Patterns.
    Higher priority numbers indicate higher priority when multiple plans overlap.
    """

    __tablename__ = "schedule_plans"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    channel_id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="Higher number = higher priority"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    channel: Mapped[Channel | None] = relationship("Channel", passive_deletes=True)

    __table_args__ = (
        UniqueConstraint("channel_id", "name", name="uq_schedule_plans_channel_name"),
        CheckConstraint("priority >= 0", name="chk_schedule_plans_priority_non_negative"),
        Index("ix_schedule_plans_channel_id", "channel_id"),
        Index("ix_schedule_plans_name", "name"),
        Index("ix_schedule_plans_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<SchedulePlan(id={self.id}, channel_id={self.channel_id}, name={self.name}, priority={self.priority}, is_active={self.is_active})>"


class SchedulePlanLabel(Base):
    """
    Represents a label for organizing programs within schedule plans.

    Labels are purely visual/organizational and do not affect scheduling logic.
    """

    __tablename__ = "schedule_plan_labels"

    id: Mapped[uuid_module.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_schedule_plan_labels_name", "name"),
        Index("ix_schedule_plan_labels_category", "category"),
    )

    def __repr__(self) -> str:
        return f"<SchedulePlanLabel(id={self.id}, name='{self.name}', category={self.category})>"
