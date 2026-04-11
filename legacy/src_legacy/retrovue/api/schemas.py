"""
Pydantic schemas for API responses.

This module defines the data transfer objects (DTOs) used for API responses,
ensuring proper serialization and timezone-aware datetime handling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssetSummary(BaseModel):
    """Summary of an Asset for API responses."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(..., description="Internal asset identifier (integer)")
    uuid: UUID = Field(..., description="Asset UUID for stable external reference")
    uri: str = Field(..., description="Asset URI or file path")
    size: int = Field(..., description="Asset size in bytes")
    duration_ms: int | None = Field(None, description="Asset duration in milliseconds")
    video_codec: str | None = Field(None, description="Video codec")
    audio_codec: str | None = Field(None, description="Audio codec")
    container: str | None = Field(None, description="Container format")
    hash_sha256: str | None = Field(None, description="SHA-256 hash")
    discovered_at: datetime = Field(..., description="When the asset was discovered")
    canonical: bool = Field(
        ...,
        description="Asset approval status for downstream schedulers and runtime. "
        "True = approved for playout without human review. "
        "False = exists in inventory but not yet approved; may be in review_queue.",
    )

    @classmethod
    def from_orm(cls, asset: Any) -> AssetSummary:
        """Create AssetSummary from ORM Asset entity."""
        return cls(
            id=asset.id,
            uuid=asset.uuid,
            uri=asset.uri,
            size=asset.size,
            duration_ms=asset.duration_ms,
            video_codec=asset.video_codec,
            audio_codec=asset.audio_codec,
            container=asset.container,
            hash_sha256=asset.hash_sha256,
            discovered_at=asset.discovered_at,
            canonical=asset.canonical,
        )


class ReviewQueueSummary(BaseModel):
    """Summary of a ReviewQueue item for API responses."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: UUID = Field(..., description="Unique review queue identifier")
    asset_id: int = Field(..., description="Associated asset identifier (integer)")
    reason: str = Field(..., description="Reason for review")
    confidence: float = Field(..., description="Confidence score (0.0-1.0)")
    status: str = Field(..., description="Review status")
    created_at: datetime = Field(..., description="When the review was queued")
    resolved_at: datetime | None = Field(None, description="When the review was resolved")

    @classmethod
    def from_orm(cls, review: Any) -> ReviewQueueSummary:
        """Create ReviewQueueSummary from ORM ReviewQueue entity."""
        return cls(
            id=review.id,
            asset_id=review.asset_id,
            reason=review.reason,
            confidence=review.confidence,
            status=review.status.value if hasattr(review.status, "value") else str(review.status),
            created_at=review.created_at,
            resolved_at=review.resolved_at,
        )


class AssetWithReviews(BaseModel):
    """Asset with its associated review queue items."""

    asset: AssetSummary = Field(..., description="Asset information")
    reviews: list[ReviewQueueSummary] = Field(
        default_factory=list, description="Associated review items"
    )

    @classmethod
    def from_orm(cls, asset: Any) -> AssetWithReviews:
        """Create AssetWithReviews from ORM Asset entity."""
        return cls(
            asset=AssetSummary.from_orm(asset),
            reviews=[ReviewQueueSummary.from_orm(review) for review in asset.review_queue],
        )


class AssetListResponse(BaseModel):
    """Response for asset listing endpoints."""

    assets: list[AssetSummary] = Field(..., description="List of assets")
    total: int = Field(..., description="Total number of assets")
    status_filter: str | None = Field(None, description="Applied status filter")


class ReviewQueueListResponse(BaseModel):
    """Response for review queue listing endpoints."""

    reviews: list[ReviewQueueSummary] = Field(..., description="List of review items")
    total: int = Field(..., description="Total number of review items")
    status_filter: str | None = Field(None, description="Applied status filter")


class AssetDetailResponse(BaseModel):
    """Response for asset detail endpoints."""

    asset: AssetWithReviews = Field(..., description="Asset with reviews")
    episode_count: int = Field(0, description="Number of associated episodes")
    marker_count: int = Field(0, description="Number of associated markers")
    provider_ref_count: int = Field(0, description="Number of provider references")


class IngestResponse(BaseModel):
    """Response for ingest operations."""

    source: str = Field(..., description="Source identifier")
    library_id: str | None = Field(None, description="Library ID processed")
    enrichers: list[str] = Field(default_factory=list, description="Enrichers used")
    counts: dict[str, int] = Field(..., description="Ingest operation counts")

    model_config = {
        "json_encoders": {
            # Ensure proper serialization of counts
        }
    }


class SeriesListResponse(BaseModel):
    """Response for series listing endpoints."""

    series: list[str] = Field(..., description="List of series titles")


class EpisodeSummary(BaseModel):
    """Summary of an episode for series endpoints."""

    id: int = Field(..., description="Asset ID (integer)")
    uuid: UUID = Field(..., description="Asset UUID for stable reference")
    title: str = Field(..., description="Episode title")
    series_title: str = Field(..., description="Series title")
    season_number: int = Field(..., description="Season number")
    episode_number: int = Field(..., description="Episode number")
    duration_sec: int | None = Field(None, description="Duration in seconds")
    kind: str = Field(..., description="Asset kind")
    source: str | None = Field(None, description="Source provider")
    source_rating_key: str | None = Field(None, description="Source rating key")


class EpisodesBySeriesResponse(BaseModel):
    """Response for episodes by series endpoints."""

    series: str = Field(..., description="Series title")
    episodes: list[EpisodeSummary] = Field(..., description="List of episodes")
    total: int = Field(..., description="Total number of episodes")
