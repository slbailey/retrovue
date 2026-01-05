from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Source


def discover_collections(db: Session, *, source_id: str) -> list[dict[str, Any]]:
    """
    Discover collections from a Source. Single operation; no persistence.
    """
    # Try by UUID first (only if it's a valid UUID)
    source = None
    try:
        uuid.UUID(source_id)
        source = db.query(Source).filter(Source.id == source_id).first()
    except ValueError:
        pass

    # Try by external_id if not found by UUID
    if not source:
        source = db.query(Source).filter(Source.external_id == source_id).first()

    # Try by name if not found by external_id
    if not source:
        source = db.query(Source).filter(Source.name == source_id).first()

    if not source:
        raise ValueError(f"Source not found: {source_id}")

    # Get the importer for this source type
    from ..adapters.registry import get_importer

    # Build importer configuration from source
    importer_config: dict[str, object] = {}
    if source.type == "plex":
        config = source.config or {}
        servers = config.get("servers", [])
        if not servers:
            raise ValueError(f"No Plex servers configured for source '{source.name}'")
        server = servers[0]
        importer_config["base_url"] = server.get("base_url")
        importer_config["token"] = server.get("token")
        if not importer_config["base_url"] or not importer_config["token"]:
            raise ValueError(f"Plex server configuration incomplete for source '{source.name}'")
    elif source.type == "filesystem":
        config = source.config or {}
        importer_config["source_name"] = source.name
        importer_config["root_paths"] = config.get("root_paths", [])
    else:
        raise ValueError(f"Unsupported source type '{source.type}'")

    # Create importer instance
    importer = get_importer(source.type, **importer_config)

    # Discover collections using the importer
    collections = importer.list_collections({})

    return collections


__all__ = ["discover_collections"]


