"""
Asset Path Resolver — centralised resolution of asset URIs to local filesystem paths.

Handles:
  1. file:// URIs → direct filesystem paths
  2. plex:// URIs → Plex API lookup → path mapping → local path
  3. Bare filesystem paths → validated as-is
  4. Cached canonical_uri on the asset (skip re-resolution if already resolved)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


class PlexClientProtocol(Protocol):
    """Minimal interface for Plex metadata lookups."""

    def get_episode_metadata(self, rating_key: int) -> dict[str, Any]: ...
    def get_libraries(self) -> list[dict[str, Any]]: ...


class AssetPathResolver:
    """
    Resolves asset URIs to local filesystem paths.

    Usage:
        resolver = AssetPathResolver(
            path_mappings=[("/media/retrotv", "/mnt/data/media/retrotv")],
            plex_client=plex_client,  # optional, needed for plex:// URIs
        )
        local_path = resolver.resolve(uri="plex://21929")
        # → "/mnt/data/media/retrotv/Tales from the Crypt/Season 1/episode.mkv"
    """

    def __init__(
        self,
        path_mappings: list[tuple[str, str]] | None = None,
        plex_client: PlexClientProtocol | None = None,
        collection_locations: list[str] | None = None,
    ):
        self._path_mappings = path_mappings or []
        self._plex_client = plex_client
        self._collection_locations = collection_locations or []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        uri: str,
        *,
        canonical_uri: str | None = None,
    ) -> str | None:
        """
        Resolve an asset URI to a local filesystem path.

        If canonical_uri is already a valid local path, return it immediately
        (cache hit). Otherwise resolve from scratch.

        Returns:
            Absolute filesystem path string, or None if resolution fails.
        """
        # 1. Check cached canonical_uri first
        if canonical_uri and not canonical_uri.startswith("plex://"):
            local = self._to_local_path(canonical_uri)
            if local and Path(local).exists():
                return local

        if not uri:
            return None

        # 2. Direct file:// or filesystem path
        if not uri.startswith("plex://"):
            local = self._to_local_path(uri)
            if local:
                # Try path mappings if file doesn't exist at literal path
                if not Path(local).exists():
                    mapped = self._apply_path_mappings(local)
                    if mapped:
                        return mapped
                return local

        # 3. plex:// URI — need API lookup
        return self._resolve_plex_uri(uri)

    # ------------------------------------------------------------------
    # Plex resolution
    # ------------------------------------------------------------------

    def _resolve_plex_uri(self, uri: str) -> str | None:
        """Resolve plex://<rating_key> to a local filesystem path."""
        if not self._plex_client:
            logger.warning("No Plex client available to resolve %s", uri)
            return None

        rating_key_str = uri.replace("plex://", "").strip("/")
        try:
            rating_key = int(rating_key_str)
        except ValueError:
            logger.error("Invalid Plex rating key in URI: %s", uri)
            return None

        # Fetch file path from Plex API
        plex_file_path = self._fetch_plex_file_path(rating_key)
        if not plex_file_path:
            logger.warning("No file path found in Plex metadata for key %d", rating_key)
            return None

        # Try direct path mapping on the raw Plex file path
        mapped = self._apply_path_mappings(plex_file_path)
        if mapped and Path(mapped).exists():
            return mapped

        # Track whether any mapping matched (even if file missing) for better diagnostics
        _mapping_matched = mapped is not None

        # Try stripping collection location prefixes to get relative path,
        # then re-map through path mappings
        for loc in self._collection_locations:
            loc_norm = loc.rstrip("/")
            if plex_file_path.startswith(loc_norm + "/") or plex_file_path.startswith(loc_norm + "\\"):
                relative = plex_file_path[len(loc_norm):]
                # Try each mapping's local side + relative
                for _, local_base in self._path_mappings:
                    candidate = str(Path(local_base) / relative.lstrip("/\\"))
                    _mapping_matched = True
                    if Path(candidate).exists():
                        return candidate

        # Last resort: try the raw Plex path directly (same-machine scenario)
        if Path(plex_file_path).exists():
            return plex_file_path

        if _mapping_matched:
            logger.debug(
                "File not found locally (path mapped OK): %s -> %s",
                plex_file_path,
                mapped,
            )
        else:
            logger.warning(
                "No path mapping matched for Plex file: %s (mappings: %s, locations: %s)",
                plex_file_path,
                self._path_mappings,
                self._collection_locations,
            )
        return None

    def _fetch_plex_file_path(self, rating_key: int) -> str | None:
        """Get the first file path from Plex metadata for a rating key."""
        try:
            meta = self._plex_client.get_episode_metadata(rating_key)
            for media in (meta or {}).get("Media", []):
                for part in media.get("Part", []):
                    fp = part.get("file")
                    if fp:
                        return fp
        except Exception as e:
            logger.error("Plex API error fetching metadata for key %d: %s", rating_key, e)
        return None

    # ------------------------------------------------------------------
    # Path mapping
    # ------------------------------------------------------------------

    def _apply_path_mappings(self, file_path: str) -> str | None:
        """
        Apply path mappings using longest-prefix match.

        Path mappings translate Plex-side paths to local filesystem paths.
        E.g., ("/media/retrotv", "/mnt/data/media/retrotv")
        """
        if not self._path_mappings:
            return None

        normalised = file_path.replace("\\", "/")
        best_match: tuple[int, str] | None = None  # (prefix_len, resolved_path)

        for plex_prefix, local_prefix in self._path_mappings:
            plex_norm = plex_prefix.replace("\\", "/").rstrip("/")
            if normalised.startswith(plex_norm + "/") or normalised == plex_norm:
                remainder = normalised[len(plex_norm):]
                resolved = str(Path(local_prefix) / remainder.lstrip("/"))
                prefix_len = len(plex_norm)
                if best_match is None or prefix_len > best_match[0]:
                    best_match = (prefix_len, resolved)

        if best_match:
            return best_match[1]
        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _to_local_path(uri: str) -> str | None:
        """Convert a file:// URI or bare path to a filesystem path string."""
        if not uri:
            return None
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            path_str = unquote(parsed.path or uri[7:])
            # Normalise Windows drive form: /C:/... → C:/...
            if path_str.startswith("/") and len(path_str) > 3 and path_str[2] == ":":
                path_str = path_str[1:]
            return path_str
        if uri.startswith("plex://"):
            return None
        return uri
