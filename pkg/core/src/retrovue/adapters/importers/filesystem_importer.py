"""
Filesystem importer for discovering content from local file systems.

This importer scans local directories for media files and returns them as discovered items.
It supports glob patterns and can extract basic metadata from file system attributes.
It also supports directory-based tag inference for interstitial content classification.
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


# Default inference rules for interstitial content classification.
# Maps directory name patterns (case-insensitive) to canonical tags.
DEFAULT_INFERENCE_RULES: dict[str, list[dict[str, Any]]] = {
    "type_rules": [
        {"match": ["commercials", "commercial", "ads"], "tag": "commercial"},
        {"match": ["station id", "station ids", "ident", "idents"], "tag": "station_id"},
        {"match": ["stinger", "stingers"], "tag": "stinger"},
        {"match": ["bumper", "bumpers"], "tag": "bumper"},
        {"match": ["promo", "promos", "trailer", "trailers", "movie trailers"], "tag": "promo"},
        {"match": ["psa", "psas", "public service"], "tag": "psa"},
        {"match": ["filler"], "tag": "filler"},
        {"match": ["special programming", "specials"], "tag": "promo"},
    ],
    "category_rules": [
        {"match": ["restaurant", "restaurants", "fast food"], "tag": "restaurant"},
        {"match": ["auto", "auto manufacturers", "cars", "car dealers", "car care"], "tag": "auto"},
        {"match": ["food", "sodas", "drinks"], "tag": "food"},
        {"match": ["insurance"], "tag": "insurance"},
        {"match": ["retail", "box stores"], "tag": "retail"},
        {"match": ["travel"], "tag": "travel"},
        {"match": ["products"], "tag": "products"},
        {"match": ["clothes", "clothing"], "tag": "clothing"},
        {"match": ["credit cards", "credit card"], "tag": "finance"},
        {"match": ["infomercials", "infomercial"], "tag": "infomercial"},
        {"match": ["local"], "tag": "local"},
        {"match": ["show adverts", "show advert"], "tag": "show_promo"},
        {"match": ["station adverts", "station advert", "network ads", "network ad"], "tag": "station_promo"},
        {"match": ["dvds", "dvd", "vhsdvd", "vhs dvd", "vhs/dvd"], "tag": "home_video"},
        {"match": ["odd", "misc", "miscellaneous"], "tag": "misc"},
        {"match": ["adult", "adult content"], "tag": "adult"},
        {"match": ["toys", "kids toys"], "tag": "toys"},
        {"match": ["video games", "games", "gaming"], "tag": "tech"},
        {"match": ["music"], "tag": "entertainment"},
        {"match": ["health", "women", "kitchen", "businesses"], "tag": "misc"},
        {"match": ["mtv"], "tag": "music_channel"},
        {"match": ["tnt"], "tag": "tnt_channel"},
    ],
}


class FilesystemImporter(BaseImporter):
    """
    Filesystem importer for discovering content from local file systems.

    This importer scans specified directories for media files and returns them
    as discovered items with file:// URIs and basic metadata.

    Supports directory-based tag inference for interstitial content classification
    via the ``inference_rules`` configuration option.
    """

    name = "filesystem"

    def __init__(
        self,
        source_name: str,
        root_paths: list[str] | None = None,
        glob_patterns: list[str] | None = None,
        include_hidden: bool = False,
        calculate_hash: bool = False,
        inference_rules: dict[str, list[dict[str, Any]]] | None = None,
        tag_from_path_segments: bool = False,
    ):
        """
        Initialize the filesystem importer.

        Args:
            source_name: Human-readable name for this filesystem source
            root_paths: List of root directories to scan (default: current directory)
            glob_patterns: List of glob patterns to match (default: common video extensions)
            include_hidden: Whether to include hidden files and directories
            calculate_hash: Deprecated; full-file hashing is not performed during ingest
            inference_rules: Optional dict with ``type_rules`` and ``category_rules`` lists,
                             each containing ``{"match": [...], "tag": "..."}`` entries.
                             If omitted, ``DEFAULT_INFERENCE_RULES`` are used.
            tag_from_path_segments: When True, every directory component between the
                configured root and the file's parent (inclusive) is emitted as a
                normalized ``tag:{component}`` label. Interstitial inference is skipped.
                See: INV-INGEST-PATH-SEGMENT-TAG-001.
        """
        super().__init__(
            source_name=source_name,
            root_paths=root_paths,
            glob_patterns=glob_patterns,
            include_hidden=include_hidden,
            calculate_hash=calculate_hash,
            inference_rules=inference_rules,
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
        self.inference_rules: dict[str, list[dict[str, Any]]] = (
            inference_rules if inference_rules is not None else DEFAULT_INFERENCE_RULES
        )
        self.tag_from_path_segments: bool = tag_from_path_segments

    # ------------------------------------------------------------------
    # Collection discovery
    # ------------------------------------------------------------------

    def list_collections(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Enumerate immediate subdirectories of each root path as collections.

        B-11: For filesystem sources, collection discovery enumerates
        the immediate subdirectories of the source base path and returns
        one collection per subdirectory. Discovery does not recurse beyond
        the first level. Files at the top level are ignored.

        Each returned dict contains:

        - ``external_id``: stable hash derived from the subdirectory's resolved path
        - ``name``: the subdirectory basename
        - ``type``: ``"directory"``
        - ``locations``: single-element list with the subdirectory path

        Args:
            source_config: Unused for filesystem sources; kept for API parity.

        Returns:
            List of collection descriptors, one per subdirectory.
        """
        collections: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for root_path in self.root_paths:
            root = Path(root_path).resolve()
            if not root.exists() or not root.is_dir():
                continue

            for child in sorted(root.iterdir()):
                # Skip non-directories (files, special entries)
                if not child.is_dir():
                    continue
                # Skip hidden directories unless include_hidden is set
                if not self.include_hidden and child.name.startswith("."):
                    continue

                # Build a stable external_id from the resolved path
                resolved = str(child.resolve())
                external_id = hashlib.sha256(resolved.encode()).hexdigest()[:16]

                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)

                collections.append({
                    "external_id": external_id,
                    "name": child.name,
                    "type": "directory",
                    "locations": [str(child)],
                })

        return collections

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tag inference
    # ------------------------------------------------------------------

    def _infer_tags_from_path_segments(self, file_path: Path) -> list[str]:
        """Emit each directory component between root and file parent as ``tag:{component}``.

        INV-INGEST-PATH-SEGMENT-TAG-001: every dir component between the configured
        root_path and the file's immediate parent (inclusive, root excluded) MUST be
        returned as a normalized ``tag:`` label. The root itself and the file name are
        NOT included.

        Args:
            file_path: Absolute path to the discovered file.

        Returns:
            List of ``"tag:{normalized_name}"`` strings, deepest directory first.
        """
        resolved_roots = {Path(r).resolve() for r in self.root_paths}
        segments: list[str] = []
        current = file_path.resolve().parent
        while True:
            if current in resolved_roots or current == current.parent:
                break  # stop at root boundary — root itself is NOT a tag
            segments.append(current.name)
            current = current.parent
        # Normalize each segment: strip, lowercase (single-space collapse handled by strip)
        return [f"tag:{seg.strip().lower()}" for seg in segments]

    def _infer_tags_from_path(self, file_path: Path) -> dict[str, Any]:
        """
        Walk directory ancestors of *file_path* and apply ``inference_rules``
        to infer interstitial type and category tags.

        The algorithm:
        1. Collect all ancestor directory names (case-normalised) between any
           configured root_path and the file's parent (inclusive of the file's
           parent, exclusive of anything above the highest matching root).
        2. For each directory name, check ``type_rules`` first-match wins.
        3. For each directory name, check ``category_rules`` first-match wins.
        4. Default ``interstitial_type`` to ``"filler"`` when no rule matches.

        Returns:
            dict with keys ``interstitial_type`` (str), ``interstitial_category``
            (str | None), and ``inferred_labels`` (list[str]).
        """
        type_rules = self.inference_rules.get("type_rules", [])
        category_rules = self.inference_rules.get("category_rules", [])

        # Resolve root paths for boundary detection
        resolved_roots = {Path(r).resolve() for r in self.root_paths}

        # Collect directory names from file parent up to (but not including)
        # the first matching root.  We stop walking when we hit a root path.
        dir_names: list[str] = []
        current = file_path.resolve().parent
        while True:
            dir_names.append(current.name)
            if current in resolved_roots or current == current.parent:
                break
            current = current.parent

        # Normalise for case-insensitive matching
        dir_names_lower = [d.lower() for d in dir_names]

        inferred_type: str | None = None
        inferred_category: str | None = None
        inferred_labels: list[str] = []

        # Build a fast lookup: pattern → tag for each rule set
        def _build_lookup(rules: list[dict[str, Any]]) -> dict[str, str]:
            lookup: dict[str, str] = {}
            for rule in rules:
                for pattern in rule["match"]:
                    lookup[pattern.lower()] = rule["tag"]
            return lookup

        type_lookup = _build_lookup(type_rules)
        category_lookup = _build_lookup(category_rules)

        # Iterate directories from deepest (most specific) to shallowest so that
        # a subdirectory like "PSAs" takes priority over its ancestor "Commercials".
        for dir_name in dir_names_lower:
            if inferred_type is None and dir_name in type_lookup:
                inferred_type = type_lookup[dir_name]
            if inferred_category is None and dir_name in category_lookup:
                inferred_category = category_lookup[dir_name]
            if inferred_type is not None and inferred_category is not None:
                break

        if inferred_type:
            inferred_labels.append(f"interstitial_type:{inferred_type}")
        if inferred_category:
            inferred_labels.append(f"interstitial_category:{inferred_category}")

        return {
            "interstitial_type": inferred_type or "filler",
            "interstitial_category": inferred_category,
            "inferred_labels": inferred_labels,
        }

    # ------------------------------------------------------------------
    # Config schema / update fields
    # ------------------------------------------------------------------

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
                {
                    "name": "inference_rules",
                    "description": (
                        "Dict with 'type_rules' and 'category_rules' for directory-based "
                        "interstitial tag inference. Defaults to built-in rules."
                    ),
                    "default": "DEFAULT_INFERENCE_RULES",
                },
                {
                    "name": "tag_from_path_segments",
                    "description": (
                        "When true, every directory component between the root path and "
                        "the file's parent is emitted as a normalized tag. "
                        "Interstitial inference is skipped. "
                        "See: INV-INGEST-PATH-SEGMENT-TAG-001."
                    ),
                    "default": "false",
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
            UpdateFieldSpec(
                config_key="inference_rules",
                cli_flag="--inference-rules",
                help="JSON dict with type_rules/category_rules for directory-based tag inference",
                field_type="json",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="tag_from_path_segments",
                cli_flag="--tag-from-path-segments",
                help="Emit each directory component between root and file parent as a tag",
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

        if "inference_rules" in partial_config:
            rules = partial_config["inference_rules"]
            if not isinstance(rules, dict):
                raise ImporterConfigurationError("inference_rules must be a dict")
            for key in ("type_rules", "category_rules"):
                if key in rules and not isinstance(rules[key], list):
                    raise ImporterConfigurationError(f"inference_rules['{key}'] must be a list")

        if "tag_from_path_segments" in partial_config:
            val = partial_config["tag_from_path_segments"]
            if not isinstance(val, bool):
                raise ImporterConfigurationError("tag_from_path_segments must be a boolean")

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

        Applies directory-based inference rules to populate
        ``editorial["interstitial_type"]`` and ``editorial["interstitial_category"]``
        from the file's ancestor directory names.

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

            if self.tag_from_path_segments:
                # INV-INGEST-PATH-SEGMENT-TAG-001: emit each dir component as tag:{name}.
                # Interstitial inference is intentionally skipped in this mode.
                segment_tags = self._infer_tags_from_path_segments(file_path)
                raw_labels = (raw_labels or []) + segment_tags
                editorial: dict[str, Any] = {
                    "title": file_path.stem,
                    "size": size,
                    "modified": last_modified.isoformat(),
                }
            else:
                # Apply directory-based interstitial inference rules (existing behaviour).
                inferred = self._infer_tags_from_path(file_path)
                raw_labels = (raw_labels or []) + inferred["inferred_labels"]
                editorial = {
                    "title": file_path.stem,
                    "size": size,
                    "modified": last_modified.isoformat(),
                    "interstitial_type": inferred["interstitial_type"],
                }
                if inferred["interstitial_category"] is not None:
                    editorial["interstitial_category"] = inferred["interstitial_category"]

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
