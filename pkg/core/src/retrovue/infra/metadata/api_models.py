from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ProbedPayload(BaseModel):
    runtime_seconds: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    audio_channels: int | None = None
    audio_format: str | None = None
    video_codec: str | None = None
    container: str | None = None


class EditorialPayload(BaseModel):
    title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    description: str | None = None
    genres: list[str] | None = None


class IngestRequest(BaseModel):
    importer_name: str
    importer: str | None = None  # alias accepted
    asset_type: str
    source_uri: str
    source_payload: dict[str, Any] | None = None
    editorial: EditorialPayload | None = None
    probed: ProbedPayload | None = None
    sidecar: dict[str, Any] | None = None
    sidecars: list[dict[str, Any]] | None = None
    station_ops: dict[str, Any] | None = None


class IngestResult(BaseModel):
    asset_id: UUID
    canonical_uri: str
    resolved_fields: dict[str, Any]
    enriched_fields: dict[str, Any]
    provenance: dict[str, Any]


__all__ = [
    "ProbedPayload",
    "EditorialPayload",
    "IngestRequest",
    "IngestResult",
]


