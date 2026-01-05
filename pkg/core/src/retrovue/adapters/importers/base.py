"""
Base protocols and skeleton template for content importers.

This module defines the core interfaces that all importers must implement
and provides a complete skeleton template for creating new importers.

Importers are responsible for discovering content from various sources (Plex, filesystem, etc.).
They should be stateless and operate on simple data structures.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class DiscoveredItem:
    """
    Represents a discovered content item from an importer.

    This is the standard format that all importers return when discovering content.
    It contains the essential information needed to register an asset in the system.
    """

    path_uri: str
    """URI path to the content (e.g., 'file:///path/to/video.mkv', 'plex://server/library/item')"""

    provider_key: str | None = None
    """Provider-specific identifier (e.g., Plex rating key, TMDB ID)"""

    raw_labels: list[str] | None = None
    """Raw metadata labels extracted from the source"""

    last_modified: datetime | None = None
    """Last modification timestamp of the content"""

    size: int | None = None
    """File size in bytes"""

    hash_sha256: str | None = None
    """SHA-256 hash of the content"""

    # Optional structured editorial metadata extracted by the importer
    editorial: dict[str, Any] | None = None
    # Optional probed technical metadata (e.g., ffprobe results)
    probed: dict[str, Any] | None = None
    # Optional sidecar payload (already following RetroVue sidecar spec)
    sidecar: dict[str, Any] | None = None
    # Optional raw source payload (e.g., full Plex metadata document)
    source_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the discovered item after initialization."""
        if not self.path_uri:
            raise ValueError("path_uri is required")

        if self.size is not None and self.size < 0:
            raise ValueError("size must be non-negative")

    def to_ingest_payload(self, importer_name: str | None, asset_type: str | None) -> dict[str, Any]:
        """Build a handler-compatible ingest payload dict.

        Returns keys: importer_name, asset_type, source_uri, editorial, probed, sidecars.
        """
        return {
            "importer_name": importer_name,
            "asset_type": asset_type,
            "source_uri": self.path_uri,
            "editorial": self.editorial,
            "probed": self.probed,
            "sidecars": [self.sidecar] if self.sidecar else [],
            "source_payload": self.source_payload,
        }


class ImporterInterface(Protocol):
    """
    Contract for all importers.

    Rules:
    - Must be stateless / pure: discover() returns discovered items, but does not persist.
    - Must raise ImporterError (or subclass) instead of exiting the process.
    - Must declare configuration schema via get_config_schema() so the CLI and registry can reason about it.
    - Must validate configuration parameters (API keys, file paths, connection settings, etc.).
    - Must declare updatable fields via get_update_fields() for dynamic CLI flag generation.
    - Must validate partial updates via validate_partial_update() to ensure update safety.
    """

    name: str
    """Unique type identifier, e.g. 'plex', 'filesystem', 'jellyfin'"""

    @classmethod
    def get_config_schema(cls) -> ImporterConfig:
        """
        Return the configuration schema for this importer type.

        This method defines what configuration parameters the importer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to connect to sources:
        - API Credentials: API keys for external service authentication
        - File Paths: Paths to scan for local content
        - Connection Settings: URLs, ports, timeouts
        - Discovery Settings: Patterns, filters, options

        Returns:
            ImporterConfig object defining the configuration schema
        """
        ...

    @abstractmethod
    def discover(self) -> list[DiscoveredItem]:
        """
        Discover content items from the source.

        Returns:
            List of discovered content items

        Raises:
            ImporterError: If discovery fails
        """
        ...

    @abstractmethod
    def get_help(self) -> dict[str, Any]:
        """
        Get help information for this importer.

        Returns:
            Dictionary containing help information with keys:
            - description: Brief description of the importer
            - required_params: List of required parameter names
            - optional_params: List of optional parameter names with defaults
            - examples: List of example usage strings
        """
        ...

    @abstractmethod
    def list_asset_groups(self) -> list[dict[str, Any]]:
        """
        List the asset groups (collections, directories, etc.) available from this source.

        Returns:
            List of dictionaries containing:
            - id: Unique identifier for the asset group
            - name: Human-readable name
            - path: Source path/URI
            - enabled: Whether this group is currently enabled
            - asset_count: Number of assets in this group (if available)
        """
        ...

    def enable_asset_group(self, group_id: str) -> bool:
        """
        Enable an asset group for content discovery.

        Args:
            group_id: Unique identifier for the asset group

        Returns:
            True if successfully enabled, False otherwise
        """
        ...

    def disable_asset_group(self, group_id: str) -> bool:
        """
        Disable an asset group from content discovery.

        Args:
            group_id: Unique identifier for the asset group

        Returns:
            True if successfully disabled, False otherwise
        """
        ...

    def resolve_local_uri(
        self, item: DiscoveredItem | dict, *, collection: Any | None = None, path_mappings: list[tuple[str, str]] | None = None
    ) -> str:
        """
        Resolve a local file URI suitable for enrichment.

        Default behavior:
        - If item.path_uri is already file://, return it.
        - Else, attempt path-mapping substitution using provided path_mappings (plex_path -> local_path).
        - Fallback to the original path_uri if no mapping applies.
        """
        try:
            # Extract uri
            uri = None
            if isinstance(item, dict):
                uri = item.get("path_uri") or item.get("uri") or item.get("path")
            else:
                uri = getattr(item, "path_uri", None) or getattr(item, "uri", None)

            if isinstance(uri, str) and uri.startswith("file://"):
                return uri

            # Only attempt mapping when file-like path is present on the item
            raw_path = None
            if isinstance(item, dict):
                raw_path = item.get("path") or item.get("file_path")
            else:
                raw_path = getattr(item, "path", None)

            if isinstance(raw_path, str) and path_mappings:
                norm = raw_path.replace("\\", "/")
                best: tuple[str, str] | None = None
                for plex_p, local_p in path_mappings:
                    if norm.lower().startswith(plex_p.replace("\\", "/").lower()):
                        if best is None or len(plex_p) > len(best[0]):
                            best = (plex_p, local_p)
                if best is not None:
                    plex_p, local_p = best
                    suffix = norm[len(plex_p) :]
                    from pathlib import Path as _Path

                    mapped_path = str(_Path(local_p) / suffix.lstrip("/\\"))
                    try:
                        return _Path(mapped_path).resolve().as_uri()
                    except Exception:
                        mapped_norm = mapped_path.replace("\\", "/")
                        if not mapped_norm.startswith("/"):
                            mapped_norm = f"/{mapped_norm}"
                        return f"file://{mapped_norm}"

            # Fallback to original uri if present
            if isinstance(uri, str):
                return uri
            return ""
        except Exception:
            # Non-fatal; allow enrichment to attempt with original
            if isinstance(item, dict):
                return item.get("path_uri") or item.get("uri") or ""
            return getattr(item, "path_uri", None) or getattr(item, "uri", None) or ""

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for this importer.

        This method defines which configuration fields can be updated via the CLI,
        how they should appear as command-line flags, and their metadata (sensitivity,
        immutability, type).

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        ...

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate a partial configuration update.

        This method ensures that:
        - Each provided key is valid for this importer
        - Type/format rules are enforced (e.g., URL must look like a URL)
        - Required relationships are maintained (if any)

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ImporterConfigurationError: If validation fails with a human-readable message
        """
        ...


class ImporterError(Exception):
    """Base exception for importer-related errors."""

    pass


class ImporterNotFoundError(ImporterError):
    """Raised when a requested importer is not found in the registry."""

    pass


class ImporterConfigurationError(ImporterError):
    """Raised when an importer is not properly configured."""

    pass


class ImporterConnectionError(ImporterError):
    """Raised when an importer cannot connect to its source."""

    pass


@dataclass
class ImporterConfig:
    """
    Configuration schema for importer types.

    This defines the structure that importers use to declare
    their configuration requirements to the CLI and registry.

    Configuration parameters are specific values an importer needs to connect
    to its source (API keys, file paths, connection settings, etc.).
    """

    required_params: list[dict[str, str]]
    """List of required configuration parameters with name and description"""
    optional_params: list[dict[str, str]]
    """List of optional configuration parameters with name, description, and default value"""
    description: str
    """Human-readable description of the importer and its configuration parameters"""


@dataclass
class UpdateFieldSpec:
    """
    Specification for an updatable configuration field.

    Used by importers to declare which configuration fields can be updated
    via the CLI, how they should appear as flags, and their validation requirements.
    """

    config_key: str
    """The key name in the configuration dictionary (e.g., "base_url", "token")"""

    cli_flag: str
    """The CLI flag name (e.g., "--base-url", "--token")"""

    help: str
    """Human-readable description for help text"""

    field_type: str
    """Type identifier: "string", "json", "csv", "path", etc."""

    is_sensitive: bool = False
    """Whether this field contains sensitive data that should be redacted in output"""

    is_immutable: bool = False
    """Whether this field cannot be updated after source creation"""


class BaseImporter(ABC):
    """
    Abstract base class providing a complete skeleton for importer implementations.

    This class provides the foundation for creating new importers that comply
    with RetroVue's domain model and contract specifications.

    Importers use configuration parameters - specific values needed to connect
    to sources (API keys, file paths, connection settings, etc.).

    To create a new importer:

    1. Copy the template to a new file in adapters/importers/
    2. Rename the class to match your importer type
    3. Implement the abstract methods
    4. Define your configuration schema
    5. Register the importer type

    Example:

    ```python
    class PlexImporter(BaseImporter):
        name = "plex"

        def __init__(self, base_url: str, token: str) -> None:
            super().__init__(base_url=base_url, token=token)
            self.base_url = base_url
            self.token = token

        def discover(self) -> list[DiscoveredItem]:
            # Your discovery logic here
            pass

        @classmethod
        def get_config_schema(cls) -> ImporterConfig:
            return ImporterConfig(
                required_params=[
                    {"name": "base_url", "description": "Plex server base URL"},
                    {"name": "token", "description": "Plex authentication token"}
                ],
                optional_params=[],
                description="Plex Media Server content discovery"
            )
    ```
    """

    # Override these in your implementation
    name: str = "base-importer"

    def __init__(self, **config: Any) -> None:
        """
        Initialize the importer with configuration parameters.

        Args:
            **config: Configuration parameters specific to this importer type
                     (API keys, file paths, connection settings, etc.)
        """
        self.config = config
        self._validate_config()

    @abstractmethod
    def discover(self) -> list[DiscoveredItem]:
        """
        Discover content items from the source.

        This is the core method that performs the actual discovery.
        Implement this method to scan your source and return discovered items.

        Returns:
            List of DiscoveredItem objects representing found content

        Raises:
            ImporterError: If discovery fails
            ImporterConfigurationError: If importer is misconfigured
            ImporterConnectionError: If cannot connect to source
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> ImporterConfig:
        """
        Return the configuration schema for this importer type.

        This method defines what configuration parameters the importer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to connect to sources:
        - API Credentials: API keys for external service authentication
        - File Paths: Paths to scan for local content
        - Connection Settings: URLs, ports, timeouts
        - Discovery Settings: Patterns, filters, options

        Returns:
            ImporterConfig object defining the configuration schema
        """
        pass

    def _validate_config(self) -> None:
        """
        Validate the importer's configuration parameters.

        Override this method to add custom validation logic.
        Raise ImporterConfigurationError for invalid configuration parameters.

        Raises:
            ImporterConfigurationError: If configuration parameters are invalid
        """
        schema = self.get_config_schema()

        # Validate required configuration parameters
        for param in schema.required_params:
            param_name = param["name"]
            if param_name not in self.config:
                raise ImporterConfigurationError(
                    f"Required configuration parameter '{param_name}' is missing"
                )

        # Validate configuration parameter types and values
        self._validate_parameter_types()

    @abstractmethod
    def _validate_parameter_types(self) -> None:
        """
        Validate configuration parameter types and values.

        Override this method to add type-specific validation for configuration parameters.
        Examples:
        - API key format validation
        - File path existence checks
        - URL format validation
        - Connection timeout range validation
        """
        # Default implementation - can be overridden
        pass

    def _safe_get_config(self, key: str, default: Any = None) -> Any:
        """
        Safely get a configuration value with a default.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def get_help(self) -> dict[str, Any]:
        """
        Get help information for this importer.

        Returns:
            Dictionary containing help information
        """
        schema = self.get_config_schema()
        return {
            "description": schema.description,
            "required_params": schema.required_params,
            "optional_params": schema.optional_params,
            "examples": self._get_examples(),
            "cli_params": self._get_cli_params(),
        }

    def _get_examples(self) -> list[str]:
        """
        Get example usage strings for this importer.

        Override this method to provide specific examples.

        Returns:
            List of example usage strings
        """
        return [f"retrovue source add --type {self.name} --name 'My {self.name.title()} Source'"]

    def _get_cli_params(self) -> dict[str, str]:
        """
        Get CLI parameter descriptions for this importer.

        Override this method to provide specific CLI parameter descriptions.

        Returns:
            Dictionary mapping parameter names to descriptions
        """
        params = {}
        schema = self.get_config_schema()

        for param in schema.required_params + schema.optional_params:
            params[param["name"]] = param["description"]

        return params

    def list_asset_groups(self) -> list[dict[str, Any]]:
        """
        List the asset groups available from this source.

        Default implementation returns empty list.
        Override this method to provide asset group listing.

        Returns:
            List of asset group dictionaries
        """
        return []

    def enable_asset_group(self, group_id: str) -> bool:
        """
        Enable an asset group for content discovery.

        Default implementation always returns True.
        Override this method to provide asset group enabling.

        Args:
            group_id: Unique identifier for the asset group

        Returns:
            True if successfully enabled, False otherwise
        """
        return True

    def disable_asset_group(self, group_id: str) -> bool:
        """
        Disable an asset group from content discovery.

        Default implementation always returns True.
        Override this method to provide asset group disabling.

        Args:
            group_id: Unique identifier for the asset group

        Returns:
            True if successfully disabled, False otherwise
        """
        return True

    @classmethod
    @abstractmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for this importer.

        This method defines which configuration fields can be updated via the CLI,
        how they should appear as command-line flags, and their metadata (sensitivity,
        immutability, type).

        Required Importer Interface for Source Update:

        get_update_fields() MUST return all user-settable configuration fields for this importer, including:
        - the CLI flag name,
        - the underlying config key,
        - whether the field is sensitive,
        - whether the field is immutable,
        - and a human-readable description for help text.

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        pass

    @classmethod
    @abstractmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate a partial configuration update.

        This method ensures that:
        - Each provided key is valid for this importer
        - Type/format rules are enforced (e.g., URL must look like a URL, path exists)
        - Required relationships are maintained (if any)

        validate_partial_update(partial_config: dict) MUST:
        - ensure each provided key is valid for this importer,
        - enforce type/format rules (e.g. URL must look like a URL),
        - enforce required relationships (if any),
        - raise a validation error with a human-readable message on failure.

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ImporterConfigurationError: If validation fails with a human-readable message
        """
        pass

    def __str__(self) -> str:
        """String representation of the importer."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the importer."""
        config_str = json.dumps(self.config, sort_keys=True)
        return f"{self.__class__.__name__}(name='{self.name}', config={config_str})"


# Legacy Protocol for backward compatibility
class Importer(ImporterInterface):
    """
    Legacy Protocol for backward compatibility.

    This maintains the old Protocol interface while the new BaseImporter
    provides the concrete implementation pattern.
    """

    pass


# Registration helper function
def register_importer_type(importer_class: type) -> None:
    """
    Register an importer type with the RetroVue registry.

    This function should be called during application startup
    to register new importer types.

    Args:
        importer_class: The importer class to register

    Example:

    ```python
    # In your importer module
    from ..base import register_importer_type

    class MyImporter(BaseImporter):
        # ... implementation ...
        pass

    # Register the importer type
    register_importer_type(MyImporter)
    ```
    """
    # This would integrate with the actual registry system
    # For now, it's a placeholder for the registration pattern
    pass
