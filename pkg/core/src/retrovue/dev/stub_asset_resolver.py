"""
In-memory AssetResolver for dev harness and CLI preview commands.

Moved from retrovue.runtime.asset_resolver to satisfy
INV-PRODUCTION-BOUNDARY-001. Used by:
- CLI: retrovue schedule compile / validate (preview without catalog)
- Tests: most schedule compiler and contract tests
"""
from __future__ import annotations

from typing import Any

from retrovue.runtime.asset_resolver import AssetMetadata, PoolDiagnostics
from retrovue.runtime.pool_dsl_normalize import normalize_pool_definition


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
        self._pools.update(
            {k: normalize_pool_definition(v) for k, v in pools.items()}
        )

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
        matched, _ = self._query_inner(match)
        return matched

    def query_with_diagnostics(self, match: dict[str, Any]) -> tuple[list[str], PoolDiagnostics]:
        """Query with per-filter exclusion diagnostics.

        INV-POOL-RESOLUTION-VISIBILITY-001: returns both matched IDs and a
        PoolDiagnostics breakdown explaining every exclusion.
        """
        return self._query_inner(match)

    def _query_inner(self, match: dict[str, Any]) -> tuple[list[str], PoolDiagnostics]:
        """Shared query engine that tracks per-filter exclusion reasons."""
        from retrovue.domain.tag_normalization import expand_tag_match_set

        # Container filter: return only assets in the named container
        collection = match.get("collection")
        if collection and collection in self._collections:
            candidate_ids = self._collections[collection]
        else:
            candidate_ids = [
                aid for aid, meta in self._assets.items()
                if meta.type not in ("collection", "pool")
            ]

        total_considered = len(candidate_ids)
        excluded_by_type = 0
        excluded_by_tags = 0
        excluded_by_rating = 0
        excluded_by_duration = 0
        excluded_by_editorial = 0
        exclusion_reasons: dict[str, list[str]] = {}
        results = []

        for asset_id in candidate_ids:
            meta = self._assets.get(asset_id)
            if meta is None:
                continue

            reasons: list[str] = []

            # Filter: type
            if "type" in match and meta.type != match["type"]:
                reasons.append(
                    f"type mismatch: expected '{match['type']}', got '{meta.type}'"
                )

            # Filter: max_duration_sec
            if "max_duration_sec" in match and meta.duration_sec > match["max_duration_sec"]:
                reasons.append(
                    f"duration too long: {meta.duration_sec}s > max {match['max_duration_sec']}s"
                )

            # Filter: min_duration_sec
            if "min_duration_sec" in match and meta.duration_sec < match["min_duration_sec"]:
                reasons.append(
                    f"duration too short: {meta.duration_sec}s < min {match['min_duration_sec']}s"
                )

            # Filter: rating
            rating_cfg = match.get("rating")
            if rating_cfg:
                if "include" in rating_cfg and meta.rating not in rating_cfg["include"]:
                    reasons.append(
                        f"rating excluded: '{meta.rating}' not in {rating_cfg['include']}"
                    )
                if "exclude" in rating_cfg and meta.rating in rating_cfg["exclude"]:
                    reasons.append(
                        f"rating excluded: '{meta.rating}' in exclude list {rating_cfg['exclude']}"
                    )

            # Filter: tags (contains_all, contains_any, excludes_any)
            tags_cfg = match.get("tags")
            tags_any_cfg = match.get("tags_any")
            tags_exclude_cfg = match.get("tags_exclude")
            if tags_cfg or tags_any_cfg or tags_exclude_cfg:
                asset_tags_expanded = expand_tag_match_set(set(meta.tags))

                if tags_cfg:
                    if isinstance(tags_cfg, str):
                        tags_cfg = [tags_cfg]
                    required = {t.lower() for t in tags_cfg}
                    missing = required - asset_tags_expanded
                    if missing:
                        reasons.append(
                            f"missing required tags: {sorted(missing)}"
                        )

                if tags_any_cfg:
                    if isinstance(tags_any_cfg, str):
                        tags_any_cfg = [tags_any_cfg]
                    wanted = {t.lower() for t in tags_any_cfg}
                    if not (wanted & asset_tags_expanded):
                        reasons.append(
                            f"none of required tags_any present: {sorted(wanted)}"
                        )

                if tags_exclude_cfg:
                    if isinstance(tags_exclude_cfg, str):
                        tags_exclude_cfg = [tags_exclude_cfg]
                    forbidden = {t.lower() for t in tags_exclude_cfg}
                    present_forbidden = forbidden & asset_tags_expanded
                    if present_forbidden:
                        reasons.append(
                            f"excluded tag present: {sorted(present_forbidden)}"
                        )

            if reasons:
                exclusion_reasons[asset_id] = reasons
                # Classify into buckets (an asset may fail multiple filters;
                # count the first for the summary bucket)
                for reason in reasons:
                    if reason.startswith("type mismatch"):
                        excluded_by_type += 1
                        break
                    elif reason.startswith("missing required tags"):
                        excluded_by_tags += 1
                        break
                    elif reason.startswith("rating excluded"):
                        excluded_by_rating += 1
                        break
                    elif reason.startswith("duration too"):
                        excluded_by_duration += 1
                        break
                    elif reason.startswith("missing editorial"):
                        excluded_by_editorial += 1
                        break
            else:
                results.append(asset_id)

        results.sort()
        diagnostics = PoolDiagnostics(
            total_considered=total_considered,
            excluded_by_type=excluded_by_type,
            excluded_by_tags=excluded_by_tags,
            excluded_by_rating=excluded_by_rating,
            excluded_by_duration=excluded_by_duration,
            excluded_by_editorial=excluded_by_editorial,
            matched=len(results),
            exclusion_reasons=exclusion_reasons,
        )
        return results, diagnostics
