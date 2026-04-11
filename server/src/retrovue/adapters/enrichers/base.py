"""
Base protocols and skeleton template for content enrichers.

This module defines the core interfaces that all enrichers must implement
and provides a complete skeleton template for creating new enrichers.

Enrichers are responsible for adding metadata to discovered content using
enrichment parameters - specific values needed to perform enrichment tasks
(e.g., API keys, file paths, timing values). They should be stateless and
operate on simple data structures.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from ..importers.base import DiscoveredItem


class Enricher(Protocol):
    """
    Contract for all enrichers.

    Rules:
    - Must be stateless / pure: enrich() returns a new item or the same item, but does not persist.
    - Must raise EnricherError (or subclass) instead of exiting the process.
    - Must declare enrichment parameter schema via get_config_schema() so the CLI and registry can reason about it.
    - Must validate enrichment parameters (API keys, file paths, timing values, etc.).
    """

    name: str
    """Unique type identifier, e.g. 'ffprobe', 'tvdb', 'watermark'"""

    scope: str
    """Enricher scope: 'ingest' or 'playout'"""

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        """
        Return the enrichment parameter schema for this enricher type.

        This method defines what enrichment parameters the enricher accepts,
        which are required vs optional, and the enricher's scope.

        Enrichment parameters are specific values needed to perform enrichment tasks:
        - API Credentials: API keys for external service authentication
        - File Paths: Paths to watermark images, templates, etc.
        - Timing Values: Timeouts, durations, delays
        - Configuration Values: Models, languages, patterns

        Returns:
            EnricherConfig object defining the enrichment parameter schema
        """
        ...

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with additional metadata.

        Args:
            discovered_item: The item to enrich

        Returns:
            The enriched item (may be the same object or a new one)

        Raises:
            EnricherError: If enrichment fails
        """
        ...


class EnricherError(Exception):
    """Base exception for enricher-related errors."""

    pass


class EnricherNotFoundError(EnricherError):
    """Raised when a requested enricher is not found in the registry."""

    pass


class EnricherConfigurationError(EnricherError):
    """Raised when an enricher is not properly configured."""

    pass


class EnricherTimeoutError(EnricherError):
    """Raised when an enricher operation times out."""

    pass


@dataclass
class EnricherConfig:
    """
    Enrichment parameter schema for enricher types.

    This defines the structure that enrichers use to declare
    their enrichment parameter requirements to the CLI and registry.

    Enrichment parameters are specific values an enricher needs to perform
    its enrichment tasks (API keys, file paths, timing values, etc.).
    """

    required_params: list[dict[str, str]]
    """List of required enrichment parameters with name and description"""
    optional_params: list[dict[str, str]]
    """List of optional enrichment parameters with name, description, and default value"""
    scope: str
    """Enricher scope: 'ingest' or 'playout'"""
    description: str
    """Human-readable description of the enricher and its enrichment parameters"""


class BaseEnricher(ABC):
    """
    Abstract base class providing a complete skeleton for enricher implementations.

    This class provides the foundation for creating new enrichers that comply
    with RetroVue's domain model and contract specifications.

    Enrichers use enrichment parameters - specific values needed to perform
    enrichment tasks (API keys, file paths, timing values, etc.).

    To create a new enricher:

    1. Copy this skeleton to a new file in adapters/enrichers/
    2. Rename the class to match your enricher type
    3. Implement the abstract methods
    4. Define your enrichment parameter schema
    5. Register the enricher type

    Example:

    ```python
    class TheTVDBEnricher(BaseEnricher):
        name = "tvdb"
        scope = "ingest"

        def __init__(self, api_key: str, language: str = "en-US") -> None:
            super().__init__(api_key=api_key, language=language)
            self.api_key = api_key
            self.language = language

        def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
            # Your enrichment logic here
            pass

        @classmethod
        def get_config_schema(cls) -> EnricherConfig:
            return EnricherConfig(
                required_params=[
                    {"name": "api_key", "description": "TheTVDB API key for authentication"}
                ],
                optional_params=[
                    {"name": "language", "description": "Language preference for metadata", "default": "en-US"}
                ],
                scope="ingest",
                description="Metadata enrichment using TheTVDB API"
            )
    ```
    """

    # Override these in your implementation
    name: str = "base-enricher"
    scope: str = "ingest"  # or "playout"

    def __init__(self, **config: Any) -> None:
        """
        Initialize the enricher with enrichment parameters.

        Args:
            **config: Enrichment parameters specific to this enricher type
                     (API keys, file paths, timing values, etc.)
        """
        self.config = config
        self._validate_config()

    @abstractmethod
    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with additional metadata.

        This is the core method that performs the actual enrichment.
        Implement this method to add your specific metadata or processing.

        Args:
            discovered_item: The item to enrich

        Returns:
            The enriched item (create a new DiscoveredItem with additional labels)

        Raises:
            EnricherError: If enrichment fails
            EnricherConfigurationError: If enricher is misconfigured
            EnricherTimeoutError: If operation times out
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> EnricherConfig:
        """
        Return the enrichment parameter schema for this enricher type.

        This method defines what enrichment parameters the enricher accepts,
        which are required vs optional, and the enricher's scope.

        Enrichment parameters are specific values needed to perform enrichment tasks:
        - API Credentials: API keys for external service authentication
        - File Paths: Paths to watermark images, templates, etc.
        - Timing Values: Timeouts, durations, delays
        - Configuration Values: Models, languages, patterns

        Returns:
            EnricherConfig object defining the enrichment parameter schema
        """
        pass

    def _validate_config(self) -> None:
        """
        Validate the enricher's enrichment parameters.

        Override this method to add custom validation logic.
        Raise EnricherConfigurationError for invalid enrichment parameters.

        Raises:
            EnricherConfigurationError: If enrichment parameters are invalid
        """
        schema = self.get_config_schema()

        # Validate required enrichment parameters
        for param in schema.required_params:
            param_name = param["name"]
            if param_name not in self.config:
                raise EnricherConfigurationError(
                    f"Required enrichment parameter '{param_name}' is missing"
                )

        # Validate enrichment parameter types and values
        self._validate_parameter_types()

    @abstractmethod
    def _validate_parameter_types(self) -> None:
        """
        Validate enrichment parameter types and values.

        Override this method to add type-specific validation for enrichment parameters.
        Examples:
        - API key format validation
        - File path existence checks
        - Timing value range validation
        - URL format validation
        """
        # Default implementation - can be overridden
        pass

    def _create_enriched_item(
        self, original_item: DiscoveredItem, additional_labels: list[str]
    ) -> DiscoveredItem:
        """
        Helper method to create an enriched DiscoveredItem.

        Args:
            original_item: The original discovered item
            additional_labels: New labels to add

        Returns:
            New DiscoveredItem with additional labels
        """
        # Combine original labels with new ones
        enriched_labels = (original_item.raw_labels or []) + additional_labels

        return DiscoveredItem(
            path_uri=original_item.path_uri,
            provider_key=original_item.provider_key,
            raw_labels=enriched_labels,
            last_modified=original_item.last_modified,
            size=original_item.size,
            hash_sha256=original_item.hash_sha256,
        )

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

    def __str__(self) -> str:
        """String representation of the enricher."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the enricher."""
        config_str = json.dumps(self.config, sort_keys=True)
        return f"{self.__class__.__name__}(name='{self.name}', config={config_str})"


# Example implementation showing how to use the skeleton
class ExampleEnricher(BaseEnricher):
    """
    Example enricher implementation showing best practices for enrichment parameters.

    This is a complete example of how to implement a new enricher
    using the BaseEnricher skeleton with proper enrichment parameter handling.
    """

    name = "example"
    scope = "ingest"

    def __init__(self, api_endpoint: str, api_key: str, timeout: int = 30) -> None:
        """
        Initialize the example enricher with enrichment parameters.

        Args:
            api_endpoint: URL of the external API (enrichment parameter)
            api_key: API key for authentication (enrichment parameter)
            timeout: Request timeout in seconds (enrichment parameter)
        """
        super().__init__(api_endpoint=api_endpoint, api_key=api_key, timeout=timeout)
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        self.timeout = timeout

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with external API data.

        Args:
            discovered_item: The item to enrich

        Returns:
            Enriched item with additional metadata

        Raises:
            EnricherError: If enrichment fails
        """
        try:
            # Example: Only process certain file types
            if not self._should_process_item(discovered_item):
                return discovered_item

            # Example: Extract metadata from external API
            metadata = self._fetch_metadata(discovered_item)

            # Example: Convert metadata to labels
            additional_labels = self._metadata_to_labels(metadata)

            # Return enriched item
            return self._create_enriched_item(discovered_item, additional_labels)

        except Exception as e:
            raise EnricherError(f"Failed to enrich item: {str(e)}") from e

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        """Return enrichment parameter schema for the example enricher."""
        return EnricherConfig(
            required_params=[
                {"name": "api_endpoint", "description": "URL of the external API endpoint"},
                {"name": "api_key", "description": "API key for authentication"},
            ],
            optional_params=[
                {"name": "timeout", "description": "Request timeout in seconds", "default": "30"}
            ],
            scope=cls.scope,
            description="Example enricher that fetches metadata from external API using enrichment parameters",
        )

    def _validate_parameter_types(self) -> None:
        """Validate enrichment parameter types for the example enricher."""
        # Validate timeout is a positive integer
        timeout = self._safe_get_config("timeout", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            raise EnricherConfigurationError(
                "Timeout enrichment parameter must be a positive integer"
            )

        # Validate API endpoint is a valid URL
        api_endpoint = self._safe_get_config("api_endpoint")
        if not api_endpoint or not api_endpoint.startswith(("http://", "https://")):
            raise EnricherConfigurationError(
                "API endpoint enrichment parameter must be a valid HTTP/HTTPS URL"
            )

        # Validate API key format (basic check)
        api_key = self._safe_get_config("api_key")
        if not api_key or len(api_key) < 10:
            raise EnricherConfigurationError(
                "API key enrichment parameter must be at least 10 characters long"
            )

    def _should_process_item(self, item: DiscoveredItem) -> bool:
        """Determine if this item should be processed."""
        # Example: Only process video files
        return item.path_uri.endswith((".mp4", ".mkv", ".avi"))

    def _fetch_metadata(self, item: DiscoveredItem) -> dict[str, Any]:
        """Fetch metadata from external API."""
        # Example implementation - replace with actual API call
        return {"title": "Example Title", "genre": "Action", "rating": 8.5}

    def _metadata_to_labels(self, metadata: dict[str, Any]) -> list[str]:
        """Convert metadata dictionary to label list."""
        labels = []
        for key, value in metadata.items():
            labels.append(f"{key}:{value}")
        return labels


# Registration helper function
def register_enricher_type(enricher_class: type) -> None:
    """
    Register an enricher type with the RetroVue registry.

    This function should be called during application startup
    to register new enricher types.

    Args:
        enricher_class: The enricher class to register

    Example:

    ```python
    # In your enricher module
    from ..base import register_enricher_type

    class MyEnricher(BaseEnricher):
        # ... implementation ...
        pass

    # Register the enricher type
    register_enricher_type(MyEnricher)
    ```
    """
    # This would integrate with the actual registry system
    # For now, it's a placeholder for the registration pattern
    pass
