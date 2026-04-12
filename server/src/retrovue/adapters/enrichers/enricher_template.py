"""
Template for creating new RetroVue enrichers.

Copy this file to create a new enricher implementation.
Rename the file and class to match your enricher type.

This template shows how to implement enrichers with enrichment parameters -
specific values needed to perform enrichment tasks (API keys, file paths, timing values, etc.).
"""

from __future__ import annotations

from typing import Any

from ..importers.base import DiscoveredItem
from .base import BaseEnricher, EnricherConfig, EnricherError


class YourEnricherName(BaseEnricher):
    """
    Your enricher description here.

    This enricher [describe what it does and how it works].

    Enrichment Parameters:
    - Describe what enrichment parameters this enricher needs
    - Examples: API keys, file paths, timing values, configuration settings
    """

    # Change these to your enricher type name and scope
    name = "your-enricher-type"
    scope = "ingest"  # or "playout"

    def __init__(self, **config: Any) -> None:
        """
        Initialize your enricher with enrichment parameters.

        Args:
            **config: Enrichment parameters (define these in get_config_schema)
                     Examples: API keys, file paths, timing values, etc.
        """
        super().__init__(**config)

        # Store enrichment parameters
        # Example:
        # self.api_key = config["api_key"]  # Required enrichment parameter
        # self.timeout = config.get("timeout", 30)  # Optional enrichment parameter
        # self.file_path = config["file_path"]  # File path enrichment parameter

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with your specific metadata.

        This is the core method that performs the actual enrichment.

        Args:
            discovered_item: The item to enrich

        Returns:
            The enriched item with additional labels

        Raises:
            EnricherError: If enrichment fails
        """
        try:
            # TODO: Implement your enrichment logic here

            # Example: Check if item should be processed
            if not self._should_process_item(discovered_item):
                return discovered_item

            # Example: Extract metadata
            metadata = self._extract_metadata(discovered_item)

            # Example: Convert metadata to labels
            additional_labels = self._metadata_to_labels(metadata)

            # Build new item preserving importer-provided metadata.
            # Enrichers must add to metadata, not overwrite importer/editorial.
            # Use a deep merge if you read from an external API.
            return DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=(discovered_item.raw_labels or []) + additional_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256,
                editorial=getattr(discovered_item, "editorial", None),
                sidecar=getattr(discovered_item, "sidecar", None),
                source_payload=getattr(discovered_item, "source_payload", None),
                # Optionally include probed if this enricher produced technical data
                probed=None,
            )

        except Exception as e:
            raise EnricherError(f"Failed to enrich item: {str(e)}") from e

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        """
        Define the enrichment parameter schema for your enricher.

        Enrichment parameters are specific values needed to perform enrichment tasks:
        - API Credentials: API keys for external service authentication
        - File Paths: Paths to watermark images, templates, etc.
        - Timing Values: Timeouts, durations, delays
        - Configuration Values: Models, languages, patterns

        Returns:
            EnricherConfig object defining required and optional enrichment parameters
        """
        return EnricherConfig(
            required_params=[
                # Define required enrichment parameters here
                # Example:
                # {"name": "api_key", "description": "API key for external service authentication"}
                # {"name": "file_path", "description": "Path to watermark image file"}
            ],
            optional_params=[
                # Define optional enrichment parameters here
                # Example:
                # {"name": "timeout", "description": "Request timeout in seconds", "default": "30"}
                # {"name": "language", "description": "Language preference for metadata", "default": "en-US"}
            ],
            scope=cls.scope,  # Uses the class attribute defined above
            description="Brief description of what this enricher does and its enrichment parameters",
        )

    def _validate_parameter_types(self) -> None:
        """
        Validate enrichment parameter types and values.

        Override this method to add custom validation logic for enrichment parameters.
        Examples:
        - API key format validation
        - File path existence checks
        - Timing value range validation
        - URL format validation

        Raise EnricherConfigurationError for invalid enrichment parameters.
        """
        # TODO: Add validation for your specific enrichment parameters

        # Example validation for different parameter types:

        # API key validation:
        # api_key = self._safe_get_config("api_key")
        # if not api_key or len(api_key) < 10:
        #     raise EnricherConfigurationError("API key enrichment parameter must be at least 10 characters long")

        # File path validation:
        # file_path = self._safe_get_config("file_path")
        # if file_path and not Path(file_path).exists():
        #     raise EnricherConfigurationError(f"File path enrichment parameter '{file_path}' does not exist")

        # Timing value validation:
        # timeout = self._safe_get_config("timeout", 30)
        # if not isinstance(timeout, int) or timeout <= 0:
        #     raise EnricherConfigurationError("Timeout enrichment parameter must be a positive integer")

        # URL validation:
        # api_endpoint = self._safe_get_config("api_endpoint")
        # if api_endpoint and not api_endpoint.startswith(("http://", "https://")):
        #     raise EnricherConfigurationError("API endpoint enrichment parameter must be a valid HTTP/HTTPS URL")

        pass

    def _should_process_item(self, item: DiscoveredItem) -> bool:
        """
        Determine if this item should be processed by your enricher.

        Args:
            item: The discovered item to check

        Returns:
            True if the item should be processed, False otherwise
        """
        # TODO: Implement your filtering logic

        # Example: Only process certain file types
        # return item.path_uri.endswith(('.mp4', '.mkv', '.avi'))

        # Example: Only process file:// URIs
        # return item.path_uri.startswith("file://")

        return True  # Process all items by default

    def _extract_metadata(self, item: DiscoveredItem) -> dict[str, Any]:
        """
        Extract metadata from the discovered item.

        Args:
            item: The discovered item to extract metadata from

        Returns:
            Dictionary containing extracted metadata
        """
        # TODO: Implement your metadata extraction logic

        # Example: Extract from file path
        # file_path = Path(item.path_uri[7:])  # Remove "file://" prefix

        # Example: Extract from external API
        # response = requests.get(f"{self.api_endpoint}/metadata",
        #                        params={"id": item.provider_key},
        #                        headers={"Authorization": f"Bearer {self.api_key}"},
        #                        timeout=self.timeout)
        # return response.json()

        # Example: Extract from database
        # with get_db_session() as session:
        #     result = session.query(Metadata).filter_by(key=item.provider_key).first()
        #     return result.to_dict() if result else {}

        return {}  # Return empty dict by default

    def _metadata_to_labels(self, metadata: dict[str, Any]) -> list[str]:
        """
        Convert metadata dictionary to label list.

        Args:
            metadata: Dictionary containing extracted metadata

        Returns:
            List of labels in "key:value" format
        """
        labels: list[str] = []

        # TODO: Implement your label conversion logic

        # Example: Convert all metadata to labels
        # for key, value in metadata.items():
        #     # Normalize key names
        #     normalized_key = key.lower().replace(" ", "_")
        #     labels.append(f"{normalized_key}:{value}")

        return labels


# TODO: Register your enricher type
# from .base import register_enricher_type
# register_enricher_type(YourEnricherName)
# -----------------------------------------------------------------------------
# Example: Minimal enricher demonstrating merge rules
# -----------------------------------------------------------------------------

class ExampleEnricher(BaseEnricher):
    """Template for enrichers.

    RULES:
    - Do NOT overwrite importer/editorial fields.
    - If you add technical/media data, put it under `probed`.
    - If you add bolt-on JSON, use `sidecar`.
    """

    name = "example"
    scope = "ingest"

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        try:
            # pretend we fetched some extra data
            extra_editorial = {
                "tagline": "A classic.",
            }
            extra_probed = {
                "duration_ms": 1234,
            }

            # merge editorial (shallow is fine here, real enrichers can deep-merge)
            base_editorial = discovered_item.editorial or {}
            merged_editorial = {**base_editorial, **extra_editorial}

            # merge probed (same idea)
            base_probed = discovered_item.probed or {}
            merged_probed = {**base_probed, **extra_probed}

            return DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=(discovered_item.raw_labels or []),
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256,
                editorial=merged_editorial,
                sidecar=discovered_item.sidecar,
                source_payload=discovered_item.source_payload,
                probed=merged_probed,
            )
        except Exception as exc:
            raise EnricherError(str(exc)) from exc



# =============================================================================
# EXAMPLES OF DIFFERENT ENRICHMENT PARAMETER TYPES
# =============================================================================


# Example 1: API-based enricher (requires API key)
class ExampleAPIEnricher(BaseEnricher):
    """
    Example API-based enricher showing API key enrichment parameters.

    This enricher fetches metadata from external APIs and requires
    API credentials as enrichment parameters.
    """

    name = "example-api"
    scope = "ingest"

    def __init__(self, api_key: str, api_endpoint: str, timeout: int = 30) -> None:
        super().__init__(api_key=api_key, api_endpoint=api_endpoint, timeout=timeout)
        self.api_key = api_key
        self.api_endpoint = api_endpoint
        self.timeout = timeout

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Implementation would use self.api_key, self.api_endpoint, self.timeout
        return discovered_item

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        return EnricherConfig(
            required_params=[
                {"name": "api_key", "description": "API key for external service authentication"},
                {"name": "api_endpoint", "description": "URL of the external API endpoint"},
            ],
            optional_params=[
                {"name": "timeout", "description": "Request timeout in seconds", "default": "30"}
            ],
            scope="ingest",
            description="API-based metadata enrichment using external service",
        )


# Example 2: File-based enricher (requires file path)
class ExampleFileEnricher(BaseEnricher):
    """
    Example file-based enricher showing file path enrichment parameters.

    This enricher processes files (watermarks, templates, etc.) and requires
    file paths as enrichment parameters.
    """

    name = "example-file"
    scope = "playout"

    def __init__(
        self, overlay_path: str, position: str = "top-right", opacity: float = 0.8
    ) -> None:
        super().__init__(overlay_path=overlay_path, position=position, opacity=opacity)
        self.overlay_path = overlay_path
        self.position = position
        self.opacity = opacity

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Implementation would use self.overlay_path, self.position, self.opacity
        return discovered_item

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        return EnricherConfig(
            required_params=[{"name": "overlay_path", "description": "Path to overlay image file"}],
            optional_params=[
                {"name": "position", "description": "Overlay position", "default": "top-right"},
                {"name": "opacity", "description": "Overlay opacity (0.0-1.0)", "default": "0.8"},
            ],
            scope="playout",
            description="File-based overlay enrichment for playout",
        )


# Example 3: No-parameter enricher (uses system defaults)
class ExampleSystemEnricher(BaseEnricher):
    """
    Example system enricher showing no enrichment parameters needed.

    This enricher uses system defaults and doesn't require any
    enrichment parameters.
    """

    name = "example-system"
    scope = "ingest"

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        # No enrichment parameters needed - uses system defaults

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Implementation uses system defaults (e.g., system FFmpeg)
        return discovered_item

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        return EnricherConfig(
            required_params=[
                # No required enrichment parameters
            ],
            optional_params=[
                # No optional enrichment parameters
            ],
            scope="ingest",
            description="System-based enrichment using default tools (no parameters needed)",
        )
