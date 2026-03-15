"""
Container discovery: discover locators from a collection without writing to the catalog.

Implements the discovery step of ContainerDiscoveryContract (docs/contracts/core/ContainerDiscoveryContract_v0.1.md):
discover locators as a distinct step before compare and reconcile. This module does not perform path
resolution, enrichment, or any database writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..infra.canonical import canonical_key_for
from ..infra.exceptions import IngestError

__all__ = ["DiscoveredLocator", "Fingerprint", "discover_locators"]


@dataclass(frozen=True)
class Fingerprint:
    """Optional fingerprint for a discovered item (size, mtime)."""

    size: int | None = None
    mtime: float | None = None


@dataclass
class DiscoveredLocator:
    """
    Locator-like record for one discovered item; no catalog write.

    Aligns with ContainerDiscoveryContract: (source_id, container_id, locator) identity.
    source_id and container_id may be UUID or str (e.g. test fakes use string ids).
    """

    source_id: uuid.UUID | str
    container_id: uuid.UUID | str
    locator: str
    fingerprint: Fingerprint | None = None


def _get_uri(item: Any) -> str | None:
    if isinstance(item, dict):
        return (
            item.get("path_uri")
            or item.get("uri")
            or item.get("path")
            or item.get("external_id")
        )
    return getattr(item, "path_uri", None)


def _get_size(item: Any) -> int | None:
    if isinstance(item, dict):
        v = item.get("size")
        return int(v) if v is not None else None
    v = getattr(item, "size", None)
    return int(v) if v is not None else None


def _get_last_modified(item: Any) -> float | None:
    if isinstance(item, dict):
        v = item.get("last_modified")
    else:
        v = getattr(item, "last_modified", None)
    if v is None:
        return None
    if hasattr(v, "timestamp"):
        return v.timestamp()
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def discover_locators(
    container: Any,
    importer: Any,
    *,
    title: str | None = None,
    season: int | None = None,
    episode: int | None = None,
) -> list[tuple[DiscoveredLocator, Any]]:
    """
    Discover locators for a collection from the importer; no DB writes.

    Calls importer.discover() or importer.discover_scoped(title, season, episode) when scope
    is provided and the importer supports it. For each returned item, builds a DiscoveredLocator
    (source_id, container_id, locator, optional fingerprint) and returns (DiscoveredLocator, raw_item)
    pairs so the caller can drive the ingest loop from this list without a second discover call.

    Args:
        container: Container with source_id and uuid.
        importer: Importer with discover() or discover_scoped(); must be stateless.
        title: Optional scope (title).
        season: Optional scope (season).
        episode: Optional scope (episode).

    Returns:
        List of (DiscoveredLocator, raw_item). locator is derived via canonical_key_for;
        fingerprint from item size and last_modified when present.

    Raises:
        IngestError: If canonical key cannot be derived for an item (e.g. missing path_uri).
    """
    source_id = getattr(container, "source_id", None)
    container_id = getattr(container, "uuid", None)
    if source_id is None or container_id is None:
        raise ValueError("container must have source_id and uuid")
    provider = getattr(importer, "name", None)

    if (title is not None or season is not None or episode is not None) and hasattr(
        importer, "discover_scoped"
    ):
        try:
            discovered_items = importer.discover_scoped(
                title=title, season=season, episode=episode
            )
        except Exception:
            discovered_items = importer.discover()
    else:
        discovered_items = importer.discover()

    result: list[tuple[DiscoveredLocator, Any]] = []
    for item in discovered_items or []:
        try:
            locator = canonical_key_for(item, container=container, provider=provider)
        except IngestError:
            raise
        size = _get_size(item)
        mtime = _get_last_modified(item)
        fp = Fingerprint(size=size, mtime=mtime) if (size is not None or mtime is not None) else None
        rec = DiscoveredLocator(
            source_id=source_id,
            container_id=container_id,
            locator=locator,
            fingerprint=fp,
        )
        result.append((rec, item))
    return result
