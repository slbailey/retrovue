"""
Canonical key derivation for Asset identity.

This module provides a consistent, deterministic canonical-key system used by all ingest paths.
Canonical keys and hashes are derived for Asset identity across filesystem, Plex, and other importers.
"""

import hashlib
import re
from urllib.parse import urlparse


def canonical_key_for(item, collection=None, provider: str | None = None) -> str:
    """
    Build a canonical key string for an ingest item.

    Rules:
      • Prefer external_id (provider_key) if present.
      • Else build from path_uri/uri/path with provider prefix.
      • Normalize slashes, lowercase host/path, remove drive letters.
      • Include collection.uuid or external_id if provided.
      • Handle various path formats: filesystem (/, C:\\), smb://, etc.

    Args:
        item: DiscoveredItem, dict, or object with path_uri, provider_key, uri, path, external_id attributes
        collection: Optional Collection object with uuid or external_id
        provider: Optional provider name (e.g., 'plex', 'filesystem') for prefixing

    Returns:
        Canonical key string

    Raises:
        IngestError: If canonical key cannot be derived from the item
    """
    from .exceptions import IngestError

    # Extract identifier from item
    identifier = None

    # Try DiscoveredItem-like object (provider_key first)
    if hasattr(item, "provider_key") and item.provider_key:
        identifier = item.provider_key
    elif hasattr(item, "external_id") and item.external_id:
        identifier = item.external_id
    # Try dict-like
    elif isinstance(item, dict):
        identifier = (
            item.get("provider_key")
            or item.get("external_id")
            or item.get("path")
            or item.get("uri")
        )
    # Fallback to path_uri
    if not identifier:
        if hasattr(item, "path_uri"):
            identifier = item.path_uri
        elif isinstance(item, dict) and "path_uri" in item:
            identifier = item["path_uri"]

    if not identifier:
        raise IngestError(
            "Cannot derive canonical key from item: missing provider_key/external_id/path/uri"
        )

    # Start building canonical key
    parts = []

    # Add provider prefix if available
    if provider:
        parts.append(provider.lower())

    # Add collection identifier if provided
    if collection:
        if hasattr(collection, "uuid"):
            parts.append(f"collection:{collection.uuid}")
        elif hasattr(collection, "external_id") and collection.external_id:
            parts.append(f"collection:{collection.external_id}")
        elif hasattr(collection, "name") and collection.name:
            parts.append(f"collection:{collection.name.lower()}")

    # Normalize identifier based on its format
    normalized_id = _normalize_identifier(identifier)

    # If identifier starts with a scheme (uri://), keep it as-is for normalized ID
    if "://" in normalized_id:
        parts.append(normalized_id)
    else:
        # For relative or absolute paths, add to parts
        parts.append(normalized_id)

    # Join parts with colon
    canonical_key = ":".join(parts)

    return canonical_key


def canonical_hash(key: str) -> str:
    """
    Generate SHA-256 hash of canonical key.

    Args:
        key: Canonical key string

    Returns:
        Hexadecimal hash string (64 characters)
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _normalize_identifier(identifier: str) -> str:
    """
    Normalize various identifier formats to a consistent representation.

    Handles:
    - Windows paths: C:\\path\\to\\file.mkv -> /c/path/to/file.mkv
    - POSIX paths: /mnt/data/file.mkv -> /mnt/data/file.mkv
    - UNC paths: \\\\server\\share\\file.mkv -> //SERVER/share/file.mkv
    - URIs: file:///path/to/file.mkv, smb://server/share/file.mkv
    - Network paths: smb://, nfs://

    Args:
        identifier: Raw identifier string

    Returns:
        Normalized identifier string
    """
    if not identifier:
        return ""

    # Handle URIs with schemes
    if "://" in identifier:
        parsed = urlparse(identifier)
        scheme = parsed.scheme.lower()

        if scheme in ("file", "smb", "nfs", "http", "https"):
            # Normalize host
            host = parsed.hostname or ""
            if host:
                host = host.lower()
            else:
                # file:// paths on Windows might have //// prefix
                if identifier.startswith("file:////"):
                    # UNC path like file:////server/share
                    path = identifier[8:]  # Remove file:////
                    return _normalize_posix_path(path)
                elif identifier.startswith("file:///"):
                    # Absolute path like file:///C:/path
                    path = identifier[8:]  # Remove file:///
                    return _normalize_posix_path(path)
                elif identifier.startswith("file://"):
                    # Relative or absolute path like file://path
                    path = identifier[7:]  # Remove file://
                    return _normalize_posix_path(path)

            # Normalize path
            path = parsed.path or ""
            path = _normalize_posix_path(path)

            # Reconstruct URI
            if host:
                return f"{scheme}://{host}{path}"
            else:
                return f"{scheme}://{path}"
        else:
            # Other schemes - lowercase scheme and host
            host = parsed.hostname or ""
            if host:
                host = host.lower()
                return f"{scheme}://{host}{parsed.path}"
            else:
                return identifier.lower()

    # Handle Windows paths (C:\, D:\, etc.)
    if re.match(r"^[A-Za-z]:[/\\]", identifier):
        # Convert Windows path to POSIX-like: C:\path -> /c/path
        drive_letter = identifier[0].lower()
        path = identifier[3:]  # Remove C:\ or C:/
        normalized = _normalize_posix_path(path)
        # Ensure leading slash in normalized path
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return f"/{drive_letter}{normalized}"

    # Handle UNC paths (\\server\\share\\path)
    if identifier.startswith("\\\\"):
        # Keep UNC format but normalize path
        path = identifier[2:]  # Remove leading \\
        # Normalize backslashes to forward slashes
        path = path.replace("\\", "/")
        # Don't lowercase the server name in UNC paths - split first before normalizing
        parts = path.split("/", 2)
        server_part = parts[0]
        share_part = parts[1] if len(parts) > 1 else ""
        rest = parts[2] if len(parts) > 2 else ""
        if share_part and rest:
            rest_normalized = _normalize_posix_path(rest)
            return f"//{server_part}/{share_part}/{rest_normalized}"
        elif share_part:
            return f"//{server_part}/{share_part}"
        else:
            return f"//{server_part}"

    # Handle relative and absolute POSIX paths
    return _normalize_posix_path(identifier)


def _normalize_posix_path(path: str) -> str:
    """
    Normalize POSIX-style paths.

    - Convert backslashes to forward slashes
    - Remove trailing slashes
    - Collapse multiple slashes to single slash
    - Lowercase the entire path

    Args:
        path: Path string

    Returns:
        Normalized path string
    """
    if not path:
        return ""

    # Convert backslashes to forward slashes
    path = path.replace("\\", "/")

    # Collapse multiple slashes (except at the beginning for absolute paths)
    path = re.sub(r"/+", "/", path)

    # Remove trailing slash (except for root)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    # Lowercase
    path = path.lower()

    return path
