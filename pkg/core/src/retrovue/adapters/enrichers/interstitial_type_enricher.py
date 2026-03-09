"""
InterstitialTypeEnricher — stamps canonical interstitial_type on assets
during ingest based on the collection name.

INV-INTERSTITIAL-TYPE-STAMP-001: Every asset ingested from a filesystem
interstitial source MUST have editorial.interstitial_type set to a
canonical type. The type is determined by collection name, not file path.

TrafficManager and TrafficPolicy operate ONLY on canonical types. They
must never reference collection names. This enricher is the boundary
between storage topology and editorial semantics.
"""

from __future__ import annotations

from typing import Any

from ..importers.base import DiscoveredItem
from .base import BaseEnricher, EnricherConfig, EnricherConfigurationError, EnricherError


# Canonical interstitial types recognized by the traffic system.
CANONICAL_INTERSTITIAL_TYPES: frozenset[str] = frozenset({
    "commercial",
    "promo",
    "psa",
    "bumper",
    "station_id",
    "trailer",
    "teaser",
    "shortform",
    "filler",
})

# Authoritative mapping: collection directory name → canonical type.
# This table is the single source of truth for the mapping.
COLLECTION_TYPE_MAP: dict[str, str] = {
    "bumpers": "bumper",
    "commercials": "commercial",
    "promos": "promo",
    "psas": "psa",
    "station_ids": "station_id",
    "trailers": "trailer",
    "teasers": "teaser",
    "shortform": "shortform",
    "oddities": "filler",
}


class InterstitialTypeEnricher(BaseEnricher):
    """Stamps canonical interstitial_type onto DiscoveredItems during ingest.

    Constructed with a collection_name. On enrich(), merges
    ``interstitial_type`` into the item's editorial dict.

    Raises EnricherConfigurationError if the collection name is not in
    COLLECTION_TYPE_MAP (no silent fallback).
    """

    name = "interstitial-type"
    scope = "ingest"

    def __init__(self, collection_name: str = "", **config: Any) -> None:
        self._collection_name = collection_name
        # Validate before calling super (which calls _validate_config)
        super().__init__(collection_name=collection_name, **config)

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Stamp interstitial_type onto the item's editorial dict.

        Merges with existing editorial — does not overwrite other fields.
        Collection-level type DOES overwrite any file-level inference
        (collection is authoritative).
        """
        try:
            canonical_type = COLLECTION_TYPE_MAP[self._collection_name]
        except KeyError:
            raise EnricherError(
                f"INV-INTERSTITIAL-TYPE-STAMP-001: collection "
                f"'{self._collection_name}' has no canonical type mapping"
            ) from None

        # Merge editorial: preserve existing fields, stamp type
        base_editorial = dict(discovered_item.editorial or {})
        base_editorial["interstitial_type"] = canonical_type

        return DiscoveredItem(
            path_uri=discovered_item.path_uri,
            provider_key=discovered_item.provider_key,
            raw_labels=discovered_item.raw_labels,
            last_modified=discovered_item.last_modified,
            size=discovered_item.size,
            hash_sha256=discovered_item.hash_sha256,
            editorial=base_editorial,
            sidecar=discovered_item.sidecar,
            source_payload=discovered_item.source_payload,
            probed=discovered_item.probed,
        )

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        return EnricherConfig(
            required_params=[
                {
                    "name": "collection_name",
                    "description": (
                        "Filesystem collection directory name "
                        "(e.g. 'commercials', 'bumpers'). Must be a key "
                        "in COLLECTION_TYPE_MAP."
                    ),
                },
            ],
            optional_params=[],
            scope="ingest",
            description=(
                "Stamps canonical interstitial_type on assets based on "
                "collection name. INV-INTERSTITIAL-TYPE-STAMP-001."
            ),
        )

    def _validate_parameter_types(self) -> None:
        name = self._collection_name
        if not name:
            raise EnricherConfigurationError(
                "INV-INTERSTITIAL-TYPE-STAMP-001: collection_name is required "
                "and must not be empty"
            )
        if name not in COLLECTION_TYPE_MAP:
            raise EnricherConfigurationError(
                f"INV-INTERSTITIAL-TYPE-STAMP-001: collection '{name}' "
                f"has no canonical type mapping. Known collections: "
                f"{sorted(COLLECTION_TYPE_MAP.keys())}"
            )
