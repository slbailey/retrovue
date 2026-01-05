from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

try:
    # pydantic v2
    from pydantic import ConfigDict
except Exception:  # pragma: no cover
    ConfigDict = dict  # type: ignore


class AssetTypeEnum(str, Enum):
    series = "series"
    episode = "episode"
    movie = "movie"
    bumper = "bumper"
    promo = "promo"
    ad = "ad"
    block = "block"


class ToneEnum(str, Enum):
    light = "light"
    serious = "serious"
    humorous = "humorous"
    dark = "dark"
    whimsical = "whimsical"
    edgy = "edgy"
    earnest = "earnest"


class DecadeEnum(str, Enum):
    d1950s = "1950s"
    d1960s = "1960s"
    d1970s = "1970s"
    d1980s = "1980s"
    d1990s = "1990s"
    d2000s = "2000s"
    d2010s = "2010s"
    d2020s = "2020s"


class ColorEnum(str, Enum):
    color = "color"
    bw = "bw"
    colorized = "colorized"


class BumpTypeEnum(str, Enum):
    station_id = "station_id"
    rating_bump = "rating_bump"
    network_ident = "network_ident"
    coming_up_next = "coming_up_next"
    interstitial = "interstitial"
    slate = "slate"


class PersonCredit(BaseModel):
    name: str
    person_id: str | None = None
    role: str | None = None
    character: str | None = None


class Credits(BaseModel):
    directors: list[PersonCredit] | None = None
    writers: list[PersonCredit] | None = None
    cast: list[PersonCredit] | None = None
    producers: list[PersonCredit] | None = None
    guest_stars: list[PersonCredit] | None = None


class ContentRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str
    code: str
    reason: str | None = None


class BaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Shared/common fields
    title: str | None = None
    original_title: str | None = None
    sort_title: str | None = None
    description: str | None = None
    tagline: str | None = None

    genres: list[str] | None = None
    subgenres: list[str] | None = None
    themes: list[str] | None = None
    keywords: list[str] | None = None

    tone: ToneEnum | None = None
    mood: list[str] | None = None

    production_year: int | None = None
    release_date: date | None = None
    original_air_date: date | None = None
    decade: DecadeEnum | None = None

    country_of_origin: str | None = None
    original_language: str | None = None
    spoken_languages: list[str] | None = None

    content_rating: ContentRating | None = None

    runtime_seconds: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    color: ColorEnum | None = None
    audio_channels: int | None = None
    audio_format: str | None = None
    closed_captions: bool | None = None
    subtitles: list[str] | None = None

    poster_image_url: str | None = None
    backdrop_image_url: str | None = None
    thumbnail_url: str | None = None

    credits: Credits | None = None
    external_ids: dict[str, str] | None = None

    source_name: str | None = None
    source_uid: str | None = None
    source_path: str | None = None
    file_sha256: str | None = None
    canonical_key: str | None = None

    ai_summary: str | None = None
    ai_keywords: list[str] | None = None
    ai_genres: list[str] | None = None
    ai_tone: ToneEnum | None = None


class SeriesMetadata(BaseMetadata):
    series_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.series)
    title: str

    # Series-specific optional fields
    studio: str | None = None
    network: str | None = None
    seasons_count: int | None = None
    episode_count: int | None = None
    franchise_id: str | None = None


class EpisodeMetadata(BaseMetadata):
    episode_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.episode)
    series_id: str
    season_number: int
    episode_number: int
    title: str
    runtime_seconds: int

    # Episode-specific optional fields
    absolute_episode_number: int | None = None
    production_code: str | None = None


class MovieMetadata(BaseMetadata):
    movie_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.movie)
    title: str
    runtime_seconds: int


class BumperMetadata(BaseMetadata):
    bumper_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.bumper)
    title: str
    bump_type: BumpTypeEnum
    runtime_seconds: int


class PromoMetadata(BaseMetadata):
    promo_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.promo)
    title: str
    runtime_seconds: int

    # Cross-links (optional)
    promoted_asset_type: AssetTypeEnum | None = None
    promoted_asset_id: str | None = None

    # Optional campaign metadata
    campaign_name: str | None = None
    air_window_start: date | None = None
    air_window_end: date | None = None
    network: str | None = None
    call_to_action: str | None = None


class AdMetadata(BaseMetadata):
    ad_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.ad)
    title: str
    advertiser: str
    runtime_seconds: int

    # Optional ad fields
    product: str | None = None
    campaign_name: str | None = None
    air_date: date | None = None
    air_window_start: date | None = None
    air_window_end: date | None = None
    region: str | None = None
    regulatory_disclaimers: list[str] | None = None
    content_warnings: list[str] | None = None


class BlockLineupEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int
    asset_type: AssetTypeEnum
    asset_id: str
    scheduled_runtime_seconds: int
    start_offset_seconds: int | None = None
    notes: str | None = None


class BlockMetadata(BaseMetadata):
    block_id: str
    asset_type: AssetTypeEnum = Field(default=AssetTypeEnum.block)
    title: str
    date: date
    lineup: list[BlockLineupEntry]


__all__ = [
    "AssetTypeEnum",
    "ToneEnum",
    "DecadeEnum",
    "ColorEnum",
    "BumpTypeEnum",
    "PersonCredit",
    "Credits",
    "ContentRating",
    "BaseMetadata",
    "SeriesMetadata",
    "EpisodeMetadata",
    "MovieMetadata",
    "BumperMetadata",
    "PromoMetadata",
    "AdMetadata",
    "BlockLineupEntry",
    "BlockMetadata",
]


# ---- Sidecar models (docs/metadata/sidecar-spec.md) ----

class SidecarMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())

    schema_id: Literal["retrovue.sidecar"] = Field(alias="schema")
    version: str
    scope: Literal["file", "series", "collection"] | None = None
    importer_hints: dict[str, str | None] | None = None  # {source_system, source_uri}
    authoritative_fields: list[str] | None = None
    notes: str | None = None


class SidecarRelationships(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str | None = None
    season_id: str | None = None
    promoted_asset_id: str | None = None


class SidecarStationOps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_class: str | None = None
    daypart_profile: str | None = None
    ad_avail_model: str | None = None


PROBE_ONLY_FIELDS: tuple[str, ...] = (
    "runtime_seconds",
    "resolution",
    "aspect_ratio",
    "audio_channels",
    "audio_format",
    "container",
    "video_codec",
)


class BaseRetroVueSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    asset_type: str
    title: str | None = None
    description: str | None = None
    genres: list[str] | None = None

    # Probe-only technicals (allowed but will be overwritten by probe)
    runtime_seconds: int | None = Field(default=None, json_schema_extra={"probe_only": True})
    aspect_ratio: str | None = Field(default=None, json_schema_extra={"probe_only": True})
    resolution: str | None = Field(default=None, json_schema_extra={"probe_only": True})
    audio_channels: int | None = Field(default=None, json_schema_extra={"probe_only": True})
    audio_format: str | None = Field(default=None, json_schema_extra={"probe_only": True})
    container: str | None = Field(default=None, json_schema_extra={"probe_only": True})
    video_codec: str | None = Field(default=None, json_schema_extra={"probe_only": True})

    content_rating: ContentRating | None = None
    external_ids: dict[str, str] | None = None

    relationships: SidecarRelationships | None = None
    station_ops: SidecarStationOps | None = None
    meta: SidecarMeta = Field(alias="_meta")

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> BaseRetroVueSidecar:
        m = super().model_validate(obj, *args, **kwargs)
        # Enforce: probe-only fields cannot be authoritative
        try:
            auth = set(m.meta.authoritative_fields or [])
            bad = auth.intersection(PROBE_ONLY_FIELDS)
            if bad:
                raise ValueError(
                    f"Probe-only fields cannot be authoritative: {', '.join(sorted(bad))}"
                )
        except Exception:
            raise
        return m


class EpisodeSidecar(BaseRetroVueSidecar):
    asset_type: Literal["episode"]
    season_number: int | None = None
    episode_number: int | None = None


class MovieSidecar(BaseRetroVueSidecar):
    asset_type: Literal["movie"]


class PromoSidecar(BaseRetroVueSidecar):
    asset_type: Literal["promo"]

    # Ensure relationships.promoted_asset_id is present when validating this model
    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> PromoSidecar:
        from typing import cast
        m = cast("PromoSidecar", super().model_validate(obj, *args, **kwargs))
        rel = getattr(m, "relationships", None)
        if rel is None or not getattr(rel, "promoted_asset_id", None):
            raise ValueError("Promo sidecar requires relationships.promoted_asset_id")
        return m


class BumperSidecar(BaseRetroVueSidecar):
    asset_type: Literal["bumper"]
    bump_type: str | None = None
    runtime_seconds: int | None = Field(default=None, json_schema_extra={"probe_only": True})


class AdSidecar(BaseRetroVueSidecar):
    asset_type: Literal["ad"]
    advertiser: str | None = None
    campaign_name: str | None = None
    runtime_seconds: int | None = Field(default=None, json_schema_extra={"probe_only": True})


class BlockSidecar(BaseRetroVueSidecar):
    asset_type: Literal["block"]
    # minimal stubs per schema
    # title/description already inherited


# Discriminated union root
RetroVueSidecar = Annotated[
    EpisodeSidecar | MovieSidecar | PromoSidecar | BumperSidecar | AdSidecar | BlockSidecar,
    Field(discriminator="asset_type"),
]


class IngestEditorial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    description: str | None = None
    genres: list[str] | None = None


class IngestProbed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_seconds: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    audio_channels: int | None = None
    audio_format: str | None = None
    video_codec: str | None = None
    container: str | None = None


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    importer_name: str
    importer: str | None = None  # alias accepted
    asset_type: str
    source_uri: str
    source_payload: dict[str, Any] | None = None
    editorial: IngestEditorial | None = None
    probed: IngestProbed | None = None
    sidecar: RetroVueSidecar | None = None
    sidecars: list[RetroVueSidecar] | None = None
    station_ops: SidecarStationOps | None = None


__all__ += [
    "SidecarMeta",
    "SidecarRelationships",
    "SidecarStationOps",
    "EpisodeSidecar",
    "MovieSidecar",
    "PromoSidecar",
    "BumperSidecar",
    "AdSidecar",
    "BlockSidecar",
    "RetroVueSidecar",
    "IngestEditorial",
    "IngestProbed",
    "IngestPayload",
]


# ---- CLI for schema export ----
def _export_schema_cli(argv: list[str]) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(prog="python -m retrovue.domain.metadata_schema")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export-schema", help="Export JSON Schema for models")
    p.add_argument(
        "--schema",
        choices=["sidecar", "ingest"],
        default="sidecar",
        help="Which schema to export (default: sidecar)",
    )
    p.add_argument("--format", choices=["json"], default="json")

    args = parser.parse_args(argv)

    if args.schema == "sidecar":
        ta: TypeAdapter[RetroVueSidecar] = TypeAdapter(RetroVueSidecar)
        schema = ta.json_schema()
    else:  # ingest
        schema = IngestPayload.model_json_schema()

    print(json.dumps(schema, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys
    _sys.exit(_export_schema_cli(_sys.argv[1:]))

