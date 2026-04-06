"""
Asset Resolver interface for the Programming DSL compiler.

Provides the AssetResolver protocol that the schedule compiler depends on
for looking up asset metadata (duration, rating, tags, availability).
Production code supplies a catalog-backed resolver; tests and CLI preview
commands use StubAssetResolver from retrovue.dev.stub_asset_resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from retrovue.runtime.pool_dsl_normalize import normalize_pool_definition


# ---------------------------------------------------------------------------
# Pool resolution diagnostics — INV-POOL-RESOLUTION-VISIBILITY-001
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolDiagnostics:
    """Per-filter exclusion breakdown for a pool query.

    INV-POOL-RESOLUTION-VISIBILITY-001: when a pool resolves to zero assets,
    the system MUST be able to explain why via this structure.
    """

    total_considered: int
    excluded_by_type: int
    excluded_by_tags: int
    excluded_by_rating: int
    excluded_by_duration: int
    excluded_by_editorial: int
    matched: int
    exclusion_reasons: dict[str, list[str]]  # asset_id → [reason, ...]


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


