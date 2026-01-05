"""
Path utilities for resolving and mapping file paths.

This module provides utilities for working with file paths, including
path mapping between different systems (Plex, local filesystem, etc.).
"""


class PathMapper:
    """Utility class for mapping paths between different systems."""

    def __init__(self, mappings: list[tuple[str, str]]) -> None:
        """
        Initialize the path mapper with a list of mappings.

        Args:
            mappings: List of (source_prefix, target_prefix) tuples
        """
        # Sort mappings by prefix length (longest first) for proper matching
        self.mappings = sorted(mappings, key=lambda x: len(x[0]), reverse=True)

    def resolve_path(self, source_path: str) -> str:
        """
        Resolve a source path to a target path using the configured mappings.

        Args:
            source_path: The source path to resolve

        Returns:
            The resolved target path, or the original path if no mapping found
        """
        for source_prefix, target_prefix in self.mappings:
            if source_path.startswith(source_prefix):
                # Replace the source prefix with the target prefix
                target_path = source_path.replace(source_prefix, target_prefix, 1)
                return target_path

        # No mapping found, return original path
        return source_path

    def add_mapping(self, source_prefix: str, target_prefix: str) -> None:
        """
        Add a new path mapping.

        Args:
            source_prefix: The source path prefix
            target_prefix: The target path prefix
        """
        self.mappings.append((source_prefix, target_prefix))
        # Re-sort to maintain longest-first order
        self.mappings.sort(key=lambda x: len(x[0]), reverse=True)

    def remove_mapping(self, source_prefix: str) -> bool:
        """
        Remove a path mapping.

        Args:
            source_prefix: The source prefix to remove

        Returns:
            True if mapping was removed, False if not found
        """
        for i, (src, _) in enumerate(self.mappings):
            if src == source_prefix:
                del self.mappings[i]
                return True
        return False


def normalize_path(path: str) -> str:
    """
    Normalize a file path for consistent comparison.

    Args:
        path: The path to normalize

    Returns:
        Normalized path string
    """
    import os

    return os.path.normpath(path)


def is_media_file(file_path: str) -> bool:
    """
    Check if a file path points to a media file.

    Args:
        file_path: The file path to check

    Returns:
        True if the file is a media file, False otherwise
    """
    media_extensions = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".m4v",
        ".wmv",
        ".flv",
        ".webm",
        ".mp3",
        ".flac",
        ".aac",
        ".ogg",
        ".wav",
        ".m4a",
        ".wma",
    }

    import os

    _, ext = os.path.splitext(file_path.lower())
    return ext in media_extensions


def get_file_size(file_path: str) -> int | None:
    """
    Get the size of a file in bytes.

    Args:
        file_path: The file path to check

    Returns:
        File size in bytes, or None if file doesn't exist
    """
    import os

    try:
        return os.path.getsize(file_path)
    except OSError:
        return None


def get_file_hash(file_path: str, algorithm: str = "sha256") -> str | None:
    """
    Calculate the hash of a file.

    Args:
        file_path: The file path to hash
        algorithm: The hash algorithm to use ('md5', 'sha1', 'sha256')

    Returns:
        The file hash as a hex string, or None if file doesn't exist
    """
    import hashlib
    import os

    if not os.path.exists(file_path):
        return None

    hash_obj = hashlib.new(algorithm)

    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except OSError:
        return None
