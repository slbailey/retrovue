"""
CatalogAssetResolver — production AssetResolver backed by the RetroVue database.

Supports two resolution modes:
  1. lookup(asset_id) — resolve a single asset by UUID, URI, or slug
  2. query(match) — evaluate pool match criteria against the catalog

Pool match criteria (from the Programming Pools contract):
  - type: episode | movie
  - series_title: str | list[str]
  - season: int | list[int] | range (e.g., "2..10", [1, "3..6", 9])
  - episode: int | list[int] | range
  - max_duration_sec / min_duration_sec: int
  - rating: { include: [...], exclude: [...] }
  - source: str (source name filter)
  - collection: str (source collection name filter)

All lookups are eager-loaded on construction to avoid N+1 queries during compilation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Asset, AssetEditorial, Collection, Marker
from .asset_resolver import AssetMetadata

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Convert a display name to a DSL-friendly slug."""
    s = name.strip().lower()
    s = re.sub(r"\s*\(\d{4}\)\s*", "", s)  # strip year suffix like "(1982)"
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


def _expand_range_value(value: Any) -> set[int] | None:
    """
    Expand a range/list/int value into a set of ints.

    Supports:
      - int: 6 → {6}
      - str range: "2..10" → {2,3,4,...,10}
      - list of int/str: [1, "3..6", 9] → {1,3,4,5,6,9}
      - None → None (no filter)
    """
    if value is None:
        return None

    def _parse_one(v: Any) -> set[int]:
        if isinstance(v, int):
            return {v}
        if isinstance(v, str) and ".." in v:
            parts = v.split("..", 1)
            try:
                lo, hi = int(parts[0].strip()), int(parts[1].strip())
                return set(range(lo, hi + 1))
            except (ValueError, IndexError):
                raise ValueError(f"Invalid range syntax: {v!r}")
        try:
            return {int(v)}
        except (ValueError, TypeError):
            raise ValueError(f"Cannot parse as integer or range: {v!r}")

    if isinstance(value, list):
        result: set[int] = set()
        for item in value:
            result |= _parse_one(item)
        return result

    return _parse_one(value)


@dataclass
class _CatalogEntry:
    """Internal representation of a catalog asset for query filtering."""
    canonical_id: str
    asset_type: str  # "episode", "movie", etc.
    duration_sec: int
    series_title: str
    season: int | None
    episode: int | None
    rating: str | None
    source_name: str
    collection_name: str
    meta: AssetMetadata


class CatalogAssetResolver:
    """
    Production AssetResolver that pre-loads the full catalog from the database.

    Implements both lookup(asset_id) and query(match) for pool evaluation.

    Usage:
        with session() as db:
            resolver = CatalogAssetResolver(db)
        # resolver is now detached from the session and safe to use anywhere
    """

    def __init__(self, db: Session) -> None:
        self._assets: dict[str, AssetMetadata] = {}
        self._aliases: dict[str, str] = {}  # alternate ID → canonical ID
        self._catalog: list[_CatalogEntry] = []  # for query() filtering
        self._pools: dict[str, dict[str, Any]] = {}  # pool_name → match criteria
        self._load(db)

    def _load(self, db: Session) -> None:
        """Eager-load all assets into memory."""

        # Load all ready assets
        assets = db.query(Asset).filter(Asset.state == "ready").all()

        # Load editorial data
        editorials: dict[str, dict[str, Any]] = {}
        for ed in db.query(AssetEditorial).all():
            editorials[str(ed.asset_uuid)] = ed.payload or {}

        # Load chapter markers
        markers: dict[str, list[float]] = {}
        for m in db.query(Marker).filter(Marker.kind == "CHAPTER").order_by(Marker.start_ms).all():
            key = str(m.asset_uuid)
            if key not in markers:
                markers[key] = []
            markers[key].append(m.start_ms / 1000.0)

        # Load collection and source name mappings
        collections = db.query(Collection).all()
        col_name_map: dict[str, str] = {}  # collection_uuid → collection_name
        col_source_map: dict[str, str] = {}  # collection_uuid → source_name
        for col in collections:
            col_name_map[str(col.uuid)] = col.name
            if col.source:
                col_source_map[str(col.uuid)] = col.source.name

        # Process each asset
        for asset in assets:
            uuid_str = str(asset.uuid)
            editorial = editorials.get(uuid_str, {})
            chapter_secs = tuple(markers.get(uuid_str, []))

            duration_sec = round((asset.duration_ms or 0) / 1000)
            series_title = editorial.get("series_title", "")
            season_raw = editorial.get("season_number")
            episode_raw = editorial.get("episode_number")
            rating = editorial.get("content_rating")

            season = int(season_raw) if season_raw is not None else None
            episode_num = int(episode_raw) if episode_raw is not None else None

            col_uuid = str(asset.collection_uuid)
            col_name = col_name_map.get(col_uuid, "")
            source_name = col_source_map.get(col_uuid, "")

            # Prefer canonical_uri (source file path) over uri (provider ref like plex://...)
            # so the runtime resolver can map via PathMappings without calling the source API.
            resolved_file_uri = asset.canonical_uri if asset.canonical_uri and not asset.canonical_uri.startswith("plex://") else asset.uri

            meta = AssetMetadata(
                type="episode",
                duration_sec=duration_sec,
                tags=(),
                rating=rating,
                file_uri=resolved_file_uri,
                chapter_markers_sec=chapter_secs if chapter_secs else None,
            )

            # Register by UUID (canonical)
            self._assets[uuid_str] = meta

            # Alias: URI
            if asset.uri:
                self._aliases[asset.uri] = uuid_str

            # Alias: slug
            if series_title and season is not None and episode_num is not None:
                series_slug = _slugify(series_title)
                slug = f"asset.{series_slug}.s{season:02d}e{episode_num:02d}"
                self._aliases[slug] = uuid_str

            # Catalog entry for query()
            self._catalog.append(_CatalogEntry(
                canonical_id=uuid_str,
                asset_type="episode",  # TODO: detect movies vs episodes from metadata
                duration_sec=duration_sec,
                series_title=series_title,
                season=season,
                episode=episode_num,
                rating=rating,
                source_name=source_name,
                collection_name=col_name,
                meta=meta,
            ))

        logger.info(
            f"CatalogAssetResolver loaded: {len(self._assets)} assets, "
            f"{len(self._aliases)} aliases, {len(self._catalog)} catalog entries"
        )

    def register_pools(self, pools: dict[str, dict[str, Any]]) -> None:
        """
        Register pool definitions from DSL parsing.

        Args:
            pools: Dict of pool_name → {"match": {...}, "order": "sequential"|"random"}
        """
        self._pools.update(pools)
        logger.info(f"Registered {len(pools)} pools")

    def lookup(self, asset_id: str) -> AssetMetadata:
        """
        Look up a single asset by any known ID (UUID, URI, slug).

        Also resolves pool names — returns a collection-type AssetMetadata
        with matching asset IDs in tags.
        """
        # Direct asset lookup
        if asset_id in self._assets:
            return self._assets[asset_id]

        # Alias lookup
        canonical = self._aliases.get(asset_id)
        if canonical and canonical in self._assets:
            return self._assets[canonical]

        # Pool lookup — evaluate match criteria on demand
        if asset_id in self._pools:
            match = self._pools[asset_id].get("match", {})
            asset_ids = self.query(match)
            return AssetMetadata(
                type="pool",
                duration_sec=0,
                tags=tuple(asset_ids),
            )

        raise KeyError(f"Asset not found: {asset_id}")

    def query(self, match: dict[str, Any]) -> list[str]:
        """
        Query the catalog with match criteria from a pool definition.

        All criteria are AND-combined. Array values are OR within that field.

        Returns:
            Ordered list of matching asset IDs (episodes: series/season/episode order).

        Raises:
            ValueError: If match criteria are invalid.
        """
        results = list(self._catalog)  # start with everything

        # Filter: type
        asset_type = match.get("type")
        if asset_type:
            results = [e for e in results if e.asset_type == asset_type]

        # Filter: series_title (string or list of strings, case-insensitive)
        series_title = match.get("series_title")
        if series_title is not None:
            if isinstance(series_title, str):
                series_title = [series_title]
            titles_lower = [t.lower() for t in series_title]
            results = [e for e in results if e.series_title.lower() in titles_lower]

        # Filter: season (int, list, range)
        season_val = match.get("season")
        season_set = _expand_range_value(season_val)
        if season_set is not None:
            results = [e for e in results if e.season is not None and e.season in season_set]

        # Filter: episode (int, list, range)
        episode_val = match.get("episode")
        episode_set = _expand_range_value(episode_val)
        if episode_set is not None:
            results = [e for e in results if e.episode is not None and e.episode in episode_set]

        # Filter: max_duration_sec
        max_dur = match.get("max_duration_sec")
        if max_dur is not None:
            results = [e for e in results if e.duration_sec <= int(max_dur)]

        # Filter: min_duration_sec
        min_dur = match.get("min_duration_sec")
        if min_dur is not None:
            results = [e for e in results if e.duration_sec >= int(min_dur)]

        # Filter: rating
        rating_cfg = match.get("rating")
        if rating_cfg:
            include = rating_cfg.get("include")
            exclude = rating_cfg.get("exclude")
            if include:
                results = [e for e in results if e.rating in include]
            if exclude:
                results = [e for e in results if e.rating not in exclude]

        # Filter: source name
        source = match.get("source")
        if source:
            results = [e for e in results if e.source_name.lower() == source.lower()]

        # Filter: collection name (source collection, not pool)
        collection = match.get("collection")
        if collection:
            results = [e for e in results if e.collection_name.lower() == collection.lower()]

        # Sort: episodes by series/season/episode, default stable
        results.sort(key=lambda e: (
            e.series_title.lower(),
            e.season if e.season is not None else 0,
            e.episode if e.episode is not None else 0,
        ))

        return [e.canonical_id for e in results]

    def resolve_pool(self, pool_name: str) -> list[str]:
        """
        Resolve a named pool to its matching asset IDs.

        Raises:
            KeyError: If pool_name is not registered.
            AssetResolutionError: If pool matches zero assets.
        """
        if pool_name not in self._pools:
            raise KeyError(f"Pool not found: {pool_name}")

        match = self._pools[pool_name].get("match", {})
        asset_ids = self.query(match)

        if not asset_ids:
            from .schedule_compiler import AssetResolutionError
            raise AssetResolutionError(
                f"Pool '{pool_name}' matched 0 assets (match: {match})"
            )

        return asset_ids

    def list_pools(self) -> list[str]:
        """Return all registered pool names."""
        return list(self._pools.keys())

    @property
    def stats(self) -> dict[str, int]:
        """Summary stats for debugging."""
        return {
            "assets": len(self._assets),
            "aliases": len(self._aliases),
            "catalog_entries": len(self._catalog),
            "pools": len(self._pools),
        }
