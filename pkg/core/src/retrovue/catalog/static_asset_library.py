"""
StaticAssetLibrary — loads a JSON asset catalog and satisfies the
AssetLibrary protocol used by the planning pipeline.

Usage:
    from retrovue.catalog.static_asset_library import StaticAssetLibrary
    lib = StaticAssetLibrary("config/asset_catalog.json")
    dur = lib.get_duration_ms("/path/to/episode.mp4")
"""

from __future__ import annotations

import json
from pathlib import Path

from retrovue.runtime.planning_pipeline import FillerAsset, MarkerInfo


class StaticAssetLibrary:
    """Read-only AssetLibrary backed by a JSON catalog file.

    Implements the AssetLibrary protocol defined in planning_pipeline.
    """

    def __init__(self, catalog_path: str | Path) -> None:
        catalog_path = Path(catalog_path)
        with open(catalog_path) as f:
            data = json.load(f)

        self._durations: dict[str, int] = {}
        self._markers: dict[str, list[MarkerInfo]] = {}
        self._fillers: list[FillerAsset] = []

        for uri, entry in data.get("assets", {}).items():
            duration_ms = entry["duration_ms"]
            self._durations[uri] = duration_ms

            markers = [
                MarkerInfo(
                    kind=m["kind"],
                    offset_ms=m["offset_ms"],
                    label=m.get("label", ""),
                )
                for m in entry.get("markers", [])
            ]
            if markers:
                self._markers[uri] = markers

            if entry.get("asset_type") == "filler":
                self._fillers.append(FillerAsset(
                    asset_uri=uri,
                    duration_ms=duration_ms,
                    asset_type="filler",
                ))

    def get_duration_ms(self, asset_uri: str) -> int:
        return self._durations.get(asset_uri, 0)

    def get_markers(self, asset_uri: str) -> list[MarkerInfo]:
        return list(self._markers.get(asset_uri, []))

    def get_filler_assets(
        self, max_duration_ms: int, count: int = 1
    ) -> list[FillerAsset]:
        eligible = [f for f in self._fillers if f.duration_ms <= max_duration_ms]
        return eligible[:count]
