"""
Filesystem importer for discovering content from local file systems.

This importer scans local directories for media files and returns them as discovered items.
It supports glob patterns and can extract basic metadata from file system attributes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import (
    BaseImporter,
    DiscoveredItem,
    ImporterConfig,
    ImporterConfigurationError,
    ImporterError,
    UpdateFieldSpec,
)

if TYPE_CHECKING:
    from ...domain.entities import Collection


class FilesystemImporter(BaseImporter):
    """
    Filesystem importer for discovering content from local file systems.

    This importer scans specified directories for media files and returns them
    as discovered items with file:// URIs and basic metadata.
    """

    name = "filesystem"

    def __init__(
        self,
        source_name: str,
        root_paths: list[str] | None = None,
        glob_patterns: list[str] | None = None,
        include_hidden: bool = False,
        calculate_hash: bool = False,
    ):
        """
        Initialize the filesystem importer.

        Args:
            source_name: Human-readable name for this filesystem source
            root_paths: List of root directories to scan (default: current directory)
            glob_patterns: List of glob patterns to match (default: common video extensions)
            include_hidden: Whether to include hidden files and directories
            calculate_hash: Deprecated; full-file hashing is not performed during ingest
        """
        super().__init__(
            source_name=source_name,
            root_paths=root_paths,
            glob_patterns=glob_patterns,
            include_hidden=include_hidden,
            calculate_hash=calculate_hash,
        )

        self.source_name = source_name
        self.root_paths = root_paths or ["."]
        self.glob_patterns = glob_patterns or [
            "**/*.mp4",
            "**/*.mkv",
            "**/*.avi",
            "**/*.mov",
            "**/*.wmv",
            "**/*.flv",
            "**/*.webm",
            "**/*.m4v",
            "**/*.3gp",
            "**/*.ogv",
        ]
        self.include_hidden = include_hidden
        self.calculate_hash = calculate_hash

    def discover(self) -> list[DiscoveredItem]:
        """
        Discover media files from the configured file system paths.

        Returns:
            List of discovered media files

        Raises:
            ImporterError: If discovery fails
        """
        try:
            discovered_items = []

            for root_path in self.root_paths:
                root = Path(root_path).resolve()

                if not root.exists():
                    raise ImporterError(f"Root path does not exist: {root}")

                if not root.is_dir():
                    raise ImporterError(f"Root path is not a directory: {root}")

                for pattern in self.glob_patterns:
                    for file_path in root.glob(pattern):
                        if self._should_include_file(file_path):
                            item = self._create_discovered_item(file_path)
                            if item:
                                discovered_items.append(item)

            return discovered_items

        except Exception as e:
            raise ImporterError(f"Failed to discover files: {str(e)}") from e

    # Contract hook used by collection ingest to validate ingestibility before discovery
    def validate_ingestible(self, collection: Collection) -> bool:
        """
        Return True if at least one configured root path exists and is a directory.
        File reachability and mapping preservation are validated elsewhere.
        """
        from pathlib import Path

        for root_path in self.root_paths:
            p = Path(root_path)
            if p.exists() and p.is_dir():
                return True
        return False

    @classmethod
    def get_config_schema(cls) -> ImporterConfig:
        """
        Return the configuration schema for the filesystem importer.

        Returns:
            ImporterConfig object defining the configuration schema
        """
        return ImporterConfig(
            required_params=[
                {
                    "name": "source_name",
                    "description": "Human-readable name for this filesystem source",
                },
                {"name": "root_paths", "description": "List of root directories to scan"},
            ],
            optional_params=[
                {
                    "name": "glob_patterns",
                    "description": "List of glob patterns to match files",
                    "default": "Common video extensions",
                },
                {
                    "name": "include_hidden",
                    "description": "Whether to include hidden files and directories",
                    "default": "false",
                },
                {
                    "name": "calculate_hash",
                    "description": "Whether to calculate SHA-256 hash of files",
                    "default": "true",
                },
            ],
            description="Scan local filesystem directories for media files and discover content",
        )

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for the filesystem importer.

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        return [
            UpdateFieldSpec(
                config_key="root_paths",
                cli_flag="--root-paths",
                help="List of root directories to scan (comma-separated or JSON array)",
                field_type="json",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="glob_patterns",
                cli_flag="--glob-patterns",
                help="List of glob patterns to match files (comma-separated or JSON array)",
                field_type="json",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="include_hidden",
                cli_flag="--include-hidden",
                help="Whether to include hidden files and directories",
                field_type="boolean",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="calculate_hash",
                cli_flag="--calculate-hash",
                help="Whether to calculate SHA-256 hash of files",
                field_type="boolean",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate a partial configuration update for the filesystem importer.

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ImporterConfigurationError: If validation fails
        """
        if "root_paths" in partial_config:
            root_paths = partial_config["root_paths"]
            if not isinstance(root_paths, list):
                raise ImporterConfigurationError("root_paths must be a list")
            if not root_paths:
                raise ImporterConfigurationError("root_paths cannot be empty")
            for path in root_paths:
                if not isinstance(path, str):
                    raise ImporterConfigurationError("All root_paths must be strings")

        if "glob_patterns" in partial_config:
            glob_patterns = partial_config["glob_patterns"]
            if not isinstance(glob_patterns, list):
                raise ImporterConfigurationError("glob_patterns must be a list")
            for pattern in glob_patterns:
                if not isinstance(pattern, str):
                    raise ImporterConfigurationError("All glob_patterns must be strings")

        if "include_hidden" in partial_config:
            include_hidden = partial_config["include_hidden"]
            if not isinstance(include_hidden, bool):
                raise ImporterConfigurationError("include_hidden must be a boolean")

        if "calculate_hash" in partial_config:
            calculate_hash = partial_config["calculate_hash"]
            if not isinstance(calculate_hash, bool):
                raise ImporterConfigurationError("calculate_hash must be a boolean")

    def _validate_parameter_types(self) -> None:
        """
        Validate configuration parameter types and values.

        Raises:
            ImporterConfigurationError: If configuration parameters are invalid
        """
        # Validate source_name
        source_name = self._safe_get_config("source_name")
        if not source_name or not isinstance(source_name, str):
            raise ImporterConfigurationError(
                "source_name configuration parameter must be a non-empty string"
            )

        # Validate root_paths
        root_paths = self._safe_get_config("root_paths")
        if not root_paths or not isinstance(root_paths, list):
            raise ImporterConfigurationError(
                "root_paths configuration parameter must be a non-empty list"
            )

        for path in root_paths:
            if not isinstance(path, str):
                raise ImporterConfigurationError("All root_paths must be strings")

        # Validate glob_patterns if provided
        glob_patterns = self._safe_get_config("glob_patterns")
        if glob_patterns is not None:
            if not isinstance(glob_patterns, list):
                raise ImporterConfigurationError(
                    "glob_patterns configuration parameter must be a list"
                )
            for pattern in glob_patterns:
                if not isinstance(pattern, str):
                    raise ImporterConfigurationError("All glob_patterns must be strings")

        # Validate include_hidden
        include_hidden = self._safe_get_config("include_hidden", False)
        if not isinstance(include_hidden, bool):
            raise ImporterConfigurationError(
                "include_hidden configuration parameter must be a boolean"
            )

        # Validate calculate_hash
        calculate_hash = self._safe_get_config("calculate_hash", True)
        if not isinstance(calculate_hash, bool):
            raise ImporterConfigurationError(
                "calculate_hash configuration parameter must be a boolean"
            )

    def _get_examples(self) -> list[str]:
        """
        Get example usage strings for the filesystem importer.

        Returns:
            List of example usage strings
        """
        return [
            'retrovue source add --type filesystem --name "My Media Library" --base-path "/media/movies"',
            'retrovue source add --type filesystem --name "Commercials" --base-path "T:\\Commercials"',
            'retrovue source add --type filesystem --name "Media Library" --base-path "/media" --enrichers "ffprobe"',
        ]

    def _get_cli_params(self) -> dict[str, str]:
        """
        Get CLI parameter descriptions for the filesystem importer.

        Returns:
            Dictionary mapping parameter names to descriptions
        """
        return {
            "name": "Friendly name for the filesystem source",
            "base_path": "Base filesystem path to scan",
        }

    def list_asset_groups(self) -> list[dict[str, Any]]:
        """
        List the asset groups (directories) available from this filesystem source.

        Returns:
            List of dictionaries containing directory information
        """
        try:
            asset_groups = []

            for root_path in self.root_paths:
                root = Path(root_path).resolve()

                if not root.exists() or not root.is_dir():
                    continue

                # For filesystem, each root path is an asset group
                # Count files in this directory
                file_count = 0
                for pattern in self.glob_patterns:
                    try:
                        file_count += len(
                            [f for f in root.glob(pattern) if self._should_include_file(f)]
                        )
                    except Exception:
                        continue

                asset_groups.append(
                    {
                        "id": str(root),
                        "name": root.name,
                        "path": str(root),
                        "enabled": True,  # Default to enabled, actual state managed by database
                        "asset_count": file_count,
                        "type": "directory",
                    }
                )

            return asset_groups

        except Exception as e:
            raise ImporterError(f"Failed to list asset groups: {str(e)}") from e

    def enable_asset_group(self, group_id: str) -> bool:
        """
        Enable an asset group (directory) for content discovery.

        Args:
            group_id: Directory path

        Returns:
            True if successfully enabled, False otherwise
        """
        try:
            # For filesystem, we just verify the directory exists
            path = Path(group_id)
            return path.exists() and path.is_dir()

        except Exception as e:
            print(f"Failed to enable asset group {group_id}: {e}")
            return False

    def disable_asset_group(self, group_id: str) -> bool:
        """
        Disable an asset group (directory) from content discovery.

        Args:
            group_id: Directory path

        Returns:
            True if successfully disabled, False otherwise
        """
        # For filesystem, disabling is handled at the database level
        # This method just confirms the operation
        return True

    def resolve_local_uri(
        self,
        item: DiscoveredItem | dict,
        *,
        collection: Any | None = None,
        path_mappings: list[tuple[str, str]] | None = None,
    ) -> str:
        """
        Filesystem items already reference local files. Return a file:// URI.

        - If item.path_uri is file://, return as-is.
        - Else if a plain path string is present, convert to file://.
        - Otherwise, return empty string.
        """
        try:
            def _to_file_uri_preserve(path_str: str) -> str:
                p = path_str.replace("\\", "/")
                if p.startswith("//"):
                    return f"file:{p}"
                if len(p) >= 2 and p[1] == ":":
                    if not p.startswith("/"):
                        p = "/" + p
                    return f"file://{p}"
                if not p.startswith("/"):
                    p = "/" + p
                return f"file://{p}"

            uri = None
            if isinstance(item, dict):
                uri = item.get("path_uri") or item.get("uri") or item.get("path")
            else:
                uri = getattr(item, "path_uri", None) or getattr(item, "uri", None)

            if isinstance(uri, str) and uri.startswith("file://"):
                # Convert to native path for downstream tools
                t = uri[len("file://") :]
                if t.startswith("/") and len(t) > 2 and t[2] == ":":
                    t = t[1:]
                return t

            # Treat as local path
            path_val = None
            if isinstance(item, dict):
                path_val = item.get("path")
            else:
                path_val = getattr(item, "path", None)
            if isinstance(path_val, str) and path_val:
                return path_val
            return ""
        except Exception:
            return ""

    def _should_include_file(self, file_path: Path) -> bool:
        """
        Determine if a file should be included in discovery.

        Args:
            file_path: Path to the file

        Returns:
            True if the file should be included
        """
        # Skip hidden files if not including them
        if not self.include_hidden and any(part.startswith(".") for part in file_path.parts):
            return False

        # Skip directories
        if file_path.is_dir():
            return False

        # Skip if file doesn't exist (broken symlinks, etc.)
        if not file_path.exists():
            return False

        # Skip if not a file
        if not file_path.is_file():
            return False

        return True

    def _create_discovered_item(self, file_path: Path) -> DiscoveredItem | None:
        """
        Create a DiscoveredItem from a file path.

        Args:
            file_path: Path to the file

        Returns:
            DiscoveredItem or None if creation fails
        """
        try:
            # Get file stats
            stat = file_path.stat()
            size = stat.st_size
            last_modified = datetime.fromtimestamp(stat.st_mtime)

            # Create file URI
            path_uri = f"file://{file_path.as_posix()}"

            # Calculate hash if requested
            hash_sha256 = None
            if self.calculate_hash:
                hash_sha256 = self._calculate_file_hash(file_path)

            # Extract basic labels from filename
            raw_labels = self._extract_filename_labels(file_path.name)

            # Build basic editorial from filename and fs attributes
            editorial: dict[str, Any] = {
                "title": file_path.stem,
                "size": size,
                "modified": last_modified.isoformat(),
            }
            # Try loading a JSON/YAML sidecar adjacent to the file
            sidecar: dict[str, Any] | None = None
            try:
                for ext in (".retrovue.json", ".json", ".yaml", ".yml"):
                    candidate = file_path.with_suffix(file_path.suffix + ext) if ext.startswith(".") else None
                    if candidate and candidate.exists():
                        if candidate.suffix.lower() in (".json", ".retrovue.json"):
                            import json as _json
                            with candidate.open("r", encoding="utf-8") as fp:
                                sidecar = _json.load(fp)
                        elif candidate.suffix.lower() in (".yaml", ".yml"):
                            import yaml as _yaml  # type: ignore[import-untyped]
                            with candidate.open("r", encoding="utf-8") as fp:
                                sidecar = _yaml.safe_load(fp)
                        break
            except Exception:
                sidecar = None

            return DiscoveredItem(
                path_uri=path_uri,
                provider_key=str(file_path),  # Use file path as provider key
                raw_labels=raw_labels,
                last_modified=last_modified,
                size=size,
                hash_sha256=hash_sha256,
                editorial=editorial,
                sidecar=sidecar,
            )

        except Exception as e:
            # Log error but continue with other files
            print(f"Warning: Failed to process file {file_path}: {e}")
            return None

    def _calculate_file_hash(self, file_path: Path) -> str:
        """
        Calculate SHA-256 hash of a file.

        Args:
            file_path: Path to the file

        Returns:
            SHA-256 hash as hex string
        """
        hash_sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_sha256.update(chunk)

        return hash_sha256.hexdigest()

    def _extract_filename_labels(self, filename: str) -> list[str]:
        """
        Extract structured labels from filename using pattern recognition.

        Args:
            filename: Name of the file

        Returns:
            List of extracted labels
        """
        # Remove extension
        name_without_ext = Path(filename).stem

        # Initialize labels list
        labels = []

        # Pattern 1: Show.Name.S02E05.*
        # Matches: Breaking.Bad.S02E05.720p.mkv
        tv_pattern1 = re.compile(r"^(.+?)\.S(\d{1,2})E(\d{1,2})(?:\.|$)", re.IGNORECASE)
        match = tv_pattern1.match(name_without_ext)
        if match:
            labels.append(f"title:{match.group(1).replace('.', ' ').strip()}")
            labels.append(f"season:{int(match.group(2))}")
            labels.append(f"episode:{int(match.group(3))}")
            labels.append("type:tv")
            return labels

        # Pattern 2: Show Name - S2E5 - Episode Title.*
        # Matches: Breaking Bad - S2E5 - Phoenix.mkv
        tv_pattern2 = re.compile(
            r"^(.+?)\s*-\s*S(\d{1,2})E(\d{1,2})\s*-\s*(.+?)(?:\s*-\s*|$)", re.IGNORECASE
        )
        match = tv_pattern2.match(name_without_ext)
        if match:
            labels.append(f"title:{match.group(1).strip()}")
            labels.append(f"season:{int(match.group(2))}")
            labels.append(f"episode:{int(match.group(3))}")
            labels.append(f"episode_title:{match.group(4).strip()}")
            labels.append("type:tv")
            return labels

        # Pattern 3: Movie.Name.1987.*
        # Matches: The.Matrix.1999.1080p.mkv
        movie_pattern = re.compile(r"^(.+?)\.(\d{4})\.", re.IGNORECASE)
        match = movie_pattern.match(name_without_ext)
        if match:
            labels.append(f"title:{match.group(1).replace('.', ' ').strip()}")
            labels.append(f"year:{int(match.group(2))}")
            labels.append("type:movie")
            return labels

        # Pattern 4: Show Name (Year) - S01E01.*
        # Matches: Breaking Bad (2008) - S01E01.mkv
        tv_pattern3 = re.compile(r"^(.+?)\s*\((\d{4})\)\s*-\s*S(\d{1,2})E(\d{1,2})", re.IGNORECASE)
        match = tv_pattern3.match(name_without_ext)
        if match:
            labels.append(f"title:{match.group(1).strip()}")
            labels.append(f"year:{int(match.group(2))}")
            labels.append(f"season:{int(match.group(3))}")
            labels.append(f"episode:{int(match.group(4))}")
            labels.append("type:tv")
            return labels

        # Pattern 5: Movie Name (Year).*
        # Matches: The Matrix (1999).mkv
        movie_pattern2 = re.compile(r"^(.+?)\s*\((\d{4})\)", re.IGNORECASE)
        match = movie_pattern2.match(name_without_ext)
        if match:
            labels.append(f"title:{match.group(1).strip()}")
            labels.append(f"year:{int(match.group(2))}")
            labels.append("type:movie")
            return labels

        # Fallback: Extract any year from the filename
        year_match = re.search(r"\b(19|20)\d{2}\b", name_without_ext)
        if year_match:
            labels.append(f"year:{int(year_match.group())}")

        # Extract title from the beginning (before any year or episode info)
        title_part = re.split(
            r"\s*[\(\[].*?[\)\]]\s*|\s*-\s*S\d+E\d+|\s*\.\d{4}\.", name_without_ext
        )[0]
        if title_part and title_part.strip():
            labels.append(f"title:{title_part.replace('.', ' ').replace('_', ' ').strip()}")

        return labels


# Note: FilesystemImporter should be registered manually when needed
# to avoid circular import issues
