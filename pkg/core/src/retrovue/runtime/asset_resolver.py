"""
Asset Resolver interface and stub for the Programming DSL compiler.

Provides the AssetResolver protocol that the schedule compiler depends on
for looking up asset metadata (duration, rating, tags, availability).
Production code supplies a catalog-backed resolver; tests use StubAssetResolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AssetMetadata:
    """Metadata for a resolved asset from the catalog."""

    type: str  # "episode", "movie", "pool", "virtual", "bumper", "promo", "filler", etc.
    duration_sec: int
    title: str = ""  # Display title from catalog
    tags: tuple[str, ...] = ()
    rating: str | None = None  # MPAA rating: G, PG, PG-13, R, etc.
    availability_window: tuple[str, str] | None = None  # (start_date, end_date) ISO strings
    file_uri: str = ""
    chapter_markers_sec: tuple[float, ...] | None = None  # Times where ad breaks should be inserted
    description: str = ""  # Synopsis/description from editorial metadata
    loudness_gain_db: float = 0.0  # INV-LOUDNESS-NORMALIZED-001: per-asset gain in dB (0.0 = unity)


class AssetResolver(Protocol):
    """Protocol for resolving asset IDs and pool queries."""

    def lookup(self, asset_id: str) -> AssetMetadata:
        """
        Look up an asset by ID. Also resolves pool names to collection-type
        metadata with matching asset IDs in tags.

        Raises:
            KeyError: If the asset_id is not found.
        """
        ...

    def query(self, match: dict[str, Any]) -> list[str]:
        """
        Query the catalog with match criteria (pool evaluation).

        All criteria are AND-combined. Array values are OR within that field.

        Returns:
            Ordered list of matching asset IDs.
        """
        ...

    def resolve_pool(self, pool_name: str) -> list[str]:
        """
        Resolve a named pool to its matching asset IDs.

        Returns:
            Ordered list of matching asset IDs.

        Raises:
            KeyError: If pool_name is not registered.
        """
        ...


class StubAssetResolver:
    """
    Test-friendly resolver preloaded with fixture data.

    Supports both lookup() and query() for pool-based tests.

    Usage:
        resolver = StubAssetResolver({
            "asset.foo": AssetMetadata(type="episode", duration_sec=1440),
        })
        meta = resolver.lookup("asset.foo")
    """

    def __init__(self, assets: dict[str, AssetMetadata] | None = None) -> None:
        self._assets: dict[str, AssetMetadata] = dict(assets) if assets else {}
        self._pools: dict[str, dict[str, Any]] = {}
        self._collections: dict[str, list[str]] = {}  # collection_name → [asset_id, ...]

    def add(self, asset_id: str, meta: AssetMetadata) -> None:
        self._assets[asset_id] = meta

    def register_pools(self, pools: dict[str, dict[str, Any]]) -> None:
        self._pools.update(pools)

    def register_collection(self, collection_name: str, asset_ids: list[str]) -> None:
        """Register assets as belonging to a named collection."""
        self._collections[collection_name] = list(asset_ids)

    def lookup(self, asset_id: str) -> AssetMetadata:
        # Direct lookup
        if asset_id in self._assets:
            return self._assets[asset_id]

        # Pool lookup — return pool-type metadata with matching tags
        if asset_id in self._pools:
            pool_def = self._pools[asset_id]
            # For stub, pool tags must be pre-registered as a collection entry
            # or we filter _assets by the match criteria
            match = pool_def.get("match", {})
            matching = self.query(match)
            return AssetMetadata(
                type="pool",
                duration_sec=0,
                tags=tuple(matching),
            )

        raise KeyError(f"Asset not found: {asset_id}")

    def resolve_pool(self, pool_name: str) -> list[str]:
        """Resolve a named pool to matching asset IDs."""
        if pool_name not in self._pools:
            raise KeyError(f"Pool not found: {pool_name}")
        match = self._pools[pool_name].get("match", {})
        asset_ids = self.query(match)
        if not asset_ids:
            raise KeyError(f"Pool '{pool_name}' matched 0 assets")
        return asset_ids

    def query(self, match: dict[str, Any]) -> list[str]:
        """Simple query implementation for tests — filters by type, collection, and tags."""
        # Collection filter: return only assets in the named collection
        collection = match.get("collection")
        if collection and collection in self._collections:
            candidate_ids = self._collections[collection]
        else:
            candidate_ids = [
                aid for aid, meta in self._assets.items()
                if meta.type not in ("collection", "pool")
            ]

        results = []
        for asset_id in candidate_ids:
            meta = self._assets.get(asset_id)
            if meta is None:
                continue

            # Filter: type
            if "type" in match and meta.type != match["type"]:
                continue

            # Filter: max_duration_sec
            if "max_duration_sec" in match and meta.duration_sec > match["max_duration_sec"]:
                continue

            # Filter: min_duration_sec
            if "min_duration_sec" in match and meta.duration_sec < match["min_duration_sec"]:
                continue

            # Filter: rating
            rating_cfg = match.get("rating")
            if rating_cfg:
                if "include" in rating_cfg and meta.rating not in rating_cfg["include"]:
                    continue
                if "exclude" in rating_cfg and meta.rating in rating_cfg["exclude"]:
                    continue

            # Filter: tags (AND-combined, case-insensitive)
            tags_cfg = match.get("tags")
            if tags_cfg:
                if isinstance(tags_cfg, str):
                    tags_cfg = [tags_cfg]
                required = {t.lower() for t in tags_cfg}
                asset_tags = {t.lower() for t in meta.tags}
                if not required.issubset(asset_tags):
                    continue

            results.append(asset_id)

        results.sort()
        return results
