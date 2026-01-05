"""
Shared types and enums for Retrovue.

This module contains common types and enums that are used across
the domain, API, CLI, and other layers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class TitleKind(str, Enum):
    """Types of titles in the system."""

    MOVIE = "movie"
    SHOW = "show"


class EntityType(str, Enum):
    """Types of entities that can have provider references."""

    TITLE = "title"
    EPISODE = "episode"
    ASSET = "asset"


class Provider(str, Enum):
    """Supported content providers."""

    PLEX = "plex"
    JELLYFIN = "jellyfin"
    FILESYSTEM = "filesystem"
    MANUAL = "manual"


class MarkerKind(str, Enum):
    """Types of markers that can be placed on assets."""

    CHAPTER = "chapter"
    AVAIL = "avail"
    BUMPER = "bumper"
    INTRO = "intro"
    OUTRO = "outro"


class ReviewStatus(str, Enum):
    """Status of items in the review queue."""

    PENDING = "pending"
    RESOLVED = "resolved"


class PackageType(str, Enum):
    """Types of packages for scheduling."""

    BLOCK = "block"
    MOVIE = "movie"
    SPECIAL = "special"
    BUMPER = "bumper"
    CUSTOM = "custom"


class AssetType(str, Enum):
    """Types of assets that can be included in packages."""

    EPISODE = "episode"
    MOVIE = "movie"
    BUMPER = "bumper"
    COMMERCIAL = "commercial"
    INTRO = "intro"
    OUTRO = "outro"
    CREDITS = "credits"


# Type aliases for common data structures
ExternalIds = dict[str, Any]
RawProviderData = dict[str, Any]
MarkerPayload = dict[str, Any]
