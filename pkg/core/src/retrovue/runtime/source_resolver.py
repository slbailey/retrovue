"""SourceResolver — unified source-to-asset normalization layer.

Implements the Asset Resolution domain contract (docs/domains/AssetResolution.md).

All source definitions (collection, pool, asset, program) resolve to List[str] of asset IDs.
The resolver never returns Collection, Pool, or Program objects.

Invariants enforced:
  INV-ASSET-RESOLUTION-NORMALIZE-001     — always returns List[str]
  INV-ASSET-RESOLUTION-COLLECTION-QUERY-001 — collection via membership lookup
  INV-ASSET-RESOLUTION-POOL-QUERY-001    — pool via match criteria evaluation
  INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001  — program via episode enumeration
  INV-ASSET-RESOLUTION-PROGRAM-ORDER-001    — program output ordered by (season, episode)
  INV-ASSET-RESOLUTION-EMPTY-FAIL-001    — zero results is a hard failure
  INV-ASSET-RESOLUTION-DISPATCH-001      — unknown source types raise InvalidSourceTypeError
"""

from __future__ import annotations

from typing import Any

from .asset_resolver import AssetMetadata


class InvalidSourceTypeError(Exception):
    """Raised when a source definition has an unrecognized or missing type."""


class AssetResolutionError(Exception):
    """Raised when a source resolves to zero assets."""


class SourceResolver:
    """Unified resolver that normalizes any source definition to List[asset_id].

    Constructor args:
        catalog:     dict[str, AssetMetadata]  — asset_id -> metadata
        collections: dict[str, list[str]]      — collection_name -> [asset_id, ...]
        pools:       dict[str, dict]           — pool_name -> {"match": {...}}
        programs:    dict[str, list[dict]]     — program_name -> [{season, episode, asset_id}, ...]
    """

    _SUPPORTED_TYPES = {"asset", "collection", "pool", "program"}

    def __init__(
        self,
        *,
        catalog: dict[str, AssetMetadata],
        collections: dict[str, list[str]],
        pools: dict[str, dict[str, Any]],
        programs: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._catalog = catalog
        self._collections = collections
        self._pools = pools
        self._programs = programs or {}

    def resolve(self, source: dict[str, Any]) -> list[str]:
        """Resolve a source definition to a list of asset IDs.

        INV-ASSET-RESOLUTION-DISPATCH-001: dispatches by source type.
        INV-ASSET-RESOLUTION-NORMALIZE-001: always returns list[str].
        INV-ASSET-RESOLUTION-EMPTY-FAIL-001: raises on zero results.
        """
        source_type = source.get("type")
        if source_type is None or source_type not in self._SUPPORTED_TYPES:
            raise InvalidSourceTypeError(
                f"Unsupported source type: {source_type!r}"
            )

        if source_type == "asset":
            return self._resolve_asset(source)
        elif source_type == "collection":
            return self._resolve_collection(source)
        elif source_type == "pool":
            return self._resolve_pool(source)
        elif source_type == "program":
            return self._resolve_program(source)

        # Unreachable, but satisfies exhaustiveness
        raise InvalidSourceTypeError(f"Unsupported source type: {source_type!r}")  # pragma: no cover

    def _resolve_asset(self, source: dict[str, Any]) -> list[str]:
        """INV-ASSET-RESOLUTION-NORMALIZE-001: direct lookup returns [asset_id]."""
        asset_id = source.get("id", "")
        if asset_id not in self._catalog:
            raise KeyError(f"Asset not found: {asset_id}")
        return [asset_id]

    def _resolve_collection(self, source: dict[str, Any]) -> list[str]:
        """INV-ASSET-RESOLUTION-COLLECTION-QUERY-001: query by collection name."""
        name = source.get("name", "")
        if name not in self._collections:
            raise AssetResolutionError(
                f"Collection '{name}' not found (zero assets)"
            )
        asset_ids = list(self._collections[name])
        if not asset_ids:
            raise AssetResolutionError(
                f"Collection '{name}' resolved to zero assets"
            )
        return asset_ids

    def _resolve_pool(self, source: dict[str, Any]) -> list[str]:
        """INV-ASSET-RESOLUTION-POOL-QUERY-001: evaluate match criteria."""
        name = source.get("name", "")
        if name not in self._pools:
            raise KeyError(f"Pool not found: {name}")
        pool_def = self._pools[name]
        match = pool_def.get("match", {})
        results = self._evaluate_match(match)
        if not results:
            raise AssetResolutionError(
                f"Pool '{name}' matched zero assets (match: {match})"
            )
        return results

    def _resolve_program(self, source: dict[str, Any]) -> list[str]:
        """INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001: enumerate episodes' backing assets.

        INV-ASSET-RESOLUTION-PROGRAM-ORDER-001: output ordered by (season, episode).
        Episode selection strategies are not implemented — returns all episode assets.
        """
        name = source.get("name", "")
        if name not in self._programs:
            raise KeyError(f"Program not found: {name}")
        episodes = self._programs[name]
        if not episodes:
            raise AssetResolutionError(
                f"Program '{name}' has zero episodes"
            )
        # Sort by (season, episode) to enforce ordering invariant
        sorted_eps = sorted(episodes, key=lambda e: (e.get("season", 0), e.get("episode", 0)))
        result: list[str] = []
        for ep in sorted_eps:
            asset_id = ep.get("asset_id", "")
            if asset_id not in self._catalog:
                raise AssetResolutionError(
                    f"Program '{name}' episode S{ep.get('season', '?'):02}E{ep.get('episode', '?'):02} "
                    f"references non-existent asset: {asset_id}"
                )
            result.append(asset_id)
        return result

    def _evaluate_match(self, match: dict[str, Any]) -> list[str]:
        """Evaluate pool match criteria against the catalog."""
        results: list[str] = []
        for asset_id, meta in self._catalog.items():
            if not self._matches(meta, match):
                continue
            results.append(asset_id)
        results.sort()
        return results

    @staticmethod
    def _matches(meta: AssetMetadata, match: dict[str, Any]) -> bool:
        """Check if an asset's metadata satisfies all match criteria."""
        # type filter
        if "type" in match and meta.type != match["type"]:
            return False

        # tags filter: asset must have ALL required tags
        # Backward-compatible: plain DSL tags match namespaced DB tags
        required_tags = match.get("tags")
        if required_tags:
            from retrovue.domain.tag_normalization import expand_tag_match_set
            meta_tags_expanded = expand_tag_match_set(set(meta.tags))
            for tag in required_tags:
                if tag.lower() not in meta_tags_expanded:
                    return False

        # rating filter
        rating_cfg = match.get("rating")
        if rating_cfg:
            if "include" in rating_cfg and meta.rating not in rating_cfg["include"]:
                return False
            if "exclude" in rating_cfg and meta.rating in rating_cfg["exclude"]:
                return False

        # max_duration_sec
        if "max_duration_sec" in match and meta.duration_sec > match["max_duration_sec"]:
            return False

        # min_duration_sec
        if "min_duration_sec" in match and meta.duration_sec < match["min_duration_sec"]:
            return False

        return True
