"""
Template for creating new RetroVue producers.

Copy this file to create a new producer implementation.
Rename the file and class to match your producer type.

This template shows how to implement producers with configuration parameters -
specific values needed to configure the producer (file paths, connection settings, etc.).

Producers are modular source components responsible for supplying playable media to a Renderer.
Each producer defines where content comes from — not how it's rendered or encoded.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseProducer,
    ProducerConfig,
    ProducerConfigurationError,
    ProducerError,
    ProducerInputError,
    UpdateFieldSpec,
)


class YourProducerName(BaseProducer):
    """
    Your producer description here.

    This producer [describe what it does and how it works].

    Configuration Parameters:
    - Describe what configuration parameters this producer needs
    - Examples: file paths, connection settings, generation parameters
    """

    # Change these to your producer type name
    name = "your-producer-type"

    def __init__(self, **config: Any) -> None:
        """
        Initialize your producer with configuration parameters.

        Args:
            **config: Configuration parameters (define these in get_config_schema)
                     Examples: file paths, connection settings, generation parameters
        """
        super().__init__(**config)

        # Store configuration parameters
        # Example:
        # self.file_path = config["file_path"]  # Required configuration parameter
        # self.timeout = config.get("timeout", 30)  # Optional configuration parameter
        # self.base_url = config["base_url"]  # Connection settings

    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """
        Get an FFmpeg-compatible input specifier for this producer.

        This is the core method that returns the input source string that FFmpeg can consume.
        The returned string must be a valid FFmpeg input specifier.

        Args:
            context: Optional context dictionary containing runtime information
                    (e.g., asset_id, segment metadata, timing information)
                    that may influence input selection

        Returns:
            FFmpeg-compatible input string (e.g., '/path/to/file.mp4', 'lavfi:color=c=black:size=1920x1080:duration=10')

        Raises:
            ProducerError: If input URL cannot be generated
            ProducerInputError: If the input source is unavailable or invalid
        """
        try:
            # TODO: Implement your input URL generation logic here

            # Example: File-based producer
            # file_path = Path(self.file_path).resolve()
            # if not file_path.exists():
            #     raise ProducerInputError(f"File does not exist: {file_path}")
            # return str(file_path)

            # Example: Network stream producer
            # stream_url = self._build_stream_url(context)
            # if not self._validate_stream_url(stream_url):
            #     raise ProducerInputError(f"Invalid stream URL: {stream_url}")
            # return stream_url

            # Example: Synthetic/test pattern producer
            # pattern = self._generate_pattern(context)
            # return f"lavfi:{pattern}"

            # Replace with actual implementation
            raise NotImplementedError("get_input_url() must be implemented")

        except ProducerError:
            raise
        except Exception as e:
            raise ProducerError(f"Failed to generate input URL: {str(e)}") from e

    @classmethod
    def get_config_schema(cls) -> ProducerConfig:
        """
        Define the configuration schema for your producer.

        Configuration parameters are specific values needed to operate:
        - File Paths: Paths to media files
        - Connection Settings: URLs, ports, timeouts for network streams
        - Generation Settings: Parameters for synthetic/test pattern generation

        Returns:
            ProducerConfig object defining required and optional configuration parameters
        """
        return ProducerConfig(
            required_params=[
                # Define required configuration parameters here
                # Example:
                # {"name": "file_path", "description": "Path to media file"}
                # {"name": "base_url", "description": "Base URL of the stream source"}
            ],
            optional_params=[
                # Define optional configuration parameters here
                # Example:
                # {"name": "timeout", "description": "Connection timeout in seconds", "default": "30"}
                # {"name": "retry_count", "description": "Number of retry attempts", "default": "3"}
            ],
            description="Brief description of what this producer does and its configuration parameters",
        )

    def _validate_parameter_types(self) -> None:
        """
        Validate configuration parameter types and values.

        Override this method to add custom validation logic for configuration parameters.
        Examples:
        - File path existence checks
        - URL format validation
        - Connection timeout range validation
        - Pattern type validation

        Raise ProducerConfigurationError for invalid configuration parameters.
        """
        # TODO: Add validation for your specific configuration parameters

        # Example validation for different parameter types:

        # File path validation:
        # file_path = self._safe_get_config("file_path")
        # if file_path:
        #     from pathlib import Path
        #     path = Path(file_path)
        #     if not path.exists():
        #         raise ProducerConfigurationError(f"File path does not exist: {file_path}")

        # URL validation:
        # base_url = self._safe_get_config("base_url")
        # if base_url and not base_url.startswith(("http://", "https://")):
        #     raise ProducerConfigurationError(f"Invalid URL format: {base_url}")

        # Integer range validation:
        # timeout = self._safe_get_config("timeout", 30)
        # if not isinstance(timeout, int) or timeout <= 0:
        #     raise ProducerConfigurationError("timeout must be a positive integer")

        pass

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Define the updatable configuration fields for your producer.

        This method defines which configuration fields can be updated via the CLI,
        how they should appear as command-line flags, and their metadata (sensitivity,
        immutability, type).

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        # TODO: Define updatable fields for your producer

        # Example:
        # return [
        #     UpdateFieldSpec(
        #         config_key="file_path",
        #         cli_flag="--file-path",
        #         help="Path to the media file",
        #         field_type="path",
        #         is_sensitive=False,
        #         is_immutable=False,
        #     ),
        #     UpdateFieldSpec(
        #         config_key="timeout",
        #         cli_flag="--timeout",
        #         help="Connection timeout in seconds",
        #         field_type="int",
        #         is_sensitive=False,
        #         is_immutable=False,
        #     ),
        # ]

        return []

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate a partial configuration update.

        This method ensures that:
        - Each provided key is valid for this producer
        - Type/format rules are enforced (e.g., file path exists, URL format valid)
        - Required relationships are maintained (if any)

        validate_partial_update(partial_config: dict) MUST:
        - ensure each provided key is valid for this producer,
        - enforce type/format rules (e.g. file path exists, URL format valid),
        - enforce required relationships (if any),
        - raise a validation error with a human-readable message on failure.

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ProducerConfigurationError: If validation fails with a human-readable message
        """
        # TODO: Add validation for partial updates

        # Example:
        # if "file_path" in partial_config:
        #     file_path = partial_config["file_path"]
        #     if not isinstance(file_path, str):
        #         raise ProducerConfigurationError("file_path must be a string")
        #
        #     from pathlib import Path
        #     path = Path(file_path)
        #     if path.exists() and not path.is_file():
        #         raise ProducerConfigurationError(f"Path exists but is not a file: {path}")

        pass

    def prepare(self, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Optional preparation hook called before get_input_url().

        Override this method to add preparation logic such as:
        - Validation that the input source is available
        - Pre-roll setup or resource allocation
        - Caching or optimization

        Args:
            context: Optional context dictionary containing runtime information

        Returns:
            Optional metadata dictionary with preparation results, or None

        Raises:
            ProducerError: If preparation fails
        """
        # TODO: Implement preparation logic if needed

        # Example:
        # if not self._validate_source_availability():
        #     raise ProducerError("Source is not available")
        #
        # # Perform any pre-roll setup
        # self._pre_roll_setup(context)
        #
        # return {"prepared": True, "source_ready": True}

        return None

    def cleanup(self, context: dict[str, Any] | None = None) -> None:
        """
        Optional cleanup hook called after input is no longer needed.

        Override this method to add cleanup logic such as:
        - Resource cleanup
        - Cache invalidation
        - Connection teardown

        Args:
            context: Optional context dictionary containing runtime information
        """
        # TODO: Implement cleanup logic if needed

        # Example:
        # self._close_connections()
        # self._invalidate_cache()

        pass

    def _get_examples(self) -> list[str]:
        """
        Get example usage strings for this producer.

        Override this method to provide specific examples.

        Returns:
            List of example usage strings
        """
        # TODO: Provide specific examples for your producer

        # Example:
        # return [
        #     f"retrovue producer add --type {self.name} --name 'My Producer' --file-path /path/to/file.mp4",
        #     f"retrovue producer add --type {self.name} --name 'Another Producer' --file-path /path/to/another.mp4 --timeout 60",
        # ]

        return super()._get_examples()


# Example: Network Stream Producer
class ExampleNetworkStreamProducer(BaseProducer):
    """
    Example network stream producer.

    This is an example implementation showing how to create a producer
    for network stream sources (e.g., RTMP, HLS, HTTP streams).
    """

    name = "network-stream"

    def __init__(self, stream_url: str, timeout: int = 30, retry_count: int = 3, **config: Any) -> None:
        """Initialize the network stream producer."""
        super().__init__(stream_url=stream_url, timeout=timeout, retry_count=retry_count, **config)
        self.stream_url = stream_url
        self.timeout = timeout
        self.retry_count = retry_count

    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """Get the network stream URL as an FFmpeg input specifier."""
        # FFmpeg can directly consume network stream URLs
        return self.stream_url

    @classmethod
    def get_config_schema(cls) -> ProducerConfig:
        """Return the configuration schema for network stream producer."""
        return ProducerConfig(
            required_params=[{"name": "stream_url", "description": "URL of the network stream"}],
            optional_params=[
                {"name": "timeout", "description": "Connection timeout in seconds", "default": "30"},
                {"name": "retry_count", "description": "Number of retry attempts", "default": "3"},
            ],
            description="Network stream producer for RTMP, HLS, HTTP streams, etc.",
        )

    def _validate_parameter_types(self) -> None:
        """Validate configuration parameter types and values."""
        if not isinstance(self.stream_url, str):
            raise ProducerConfigurationError("stream_url must be a string")

        if not self.stream_url.strip():
            raise ProducerConfigurationError("stream_url cannot be empty")

        # Validate URL format
        if not self.stream_url.startswith(("http://", "https://", "rtmp://", "rtsp://", "udp://")):
            raise ProducerConfigurationError(
                f"Invalid stream URL format: {self.stream_url}. Must start with http://, https://, rtmp://, rtsp://, or udp://"
            )

        if not isinstance(self.timeout, int) or self.timeout <= 0:
            raise ProducerConfigurationError("timeout must be a positive integer")

        if not isinstance(self.retry_count, int) or self.retry_count < 0:
            raise ProducerConfigurationError("retry_count must be a non-negative integer")

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """Return updatable fields for network stream producer."""
        return [
            UpdateFieldSpec(
                config_key="stream_url",
                cli_flag="--stream-url",
                help="URL of the network stream",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="timeout",
                cli_flag="--timeout",
                help="Connection timeout in seconds",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="retry_count",
                cli_flag="--retry-count",
                help="Number of retry attempts",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """Validate partial configuration update for network stream producer."""
        if "stream_url" in partial_config:
            stream_url = partial_config["stream_url"]
            if not isinstance(stream_url, str):
                raise ProducerConfigurationError("stream_url must be a string")

            if not stream_url.strip():
                raise ProducerConfigurationError("stream_url cannot be empty")

            if not stream_url.startswith(("http://", "https://", "rtmp://", "rtsp://", "udp://")):
                raise ProducerConfigurationError(
                    f"Invalid stream URL format: {stream_url}. Must start with http://, https://, rtmp://, rtsp://, or udp://"
                )

        if "timeout" in partial_config:
            timeout = partial_config["timeout"]
            if not isinstance(timeout, int) or timeout <= 0:
                raise ProducerConfigurationError("timeout must be a positive integer")

        if "retry_count" in partial_config:
            retry_count = partial_config["retry_count"]
            if not isinstance(retry_count, int) or retry_count < 0:
                raise ProducerConfigurationError("retry_count must be a non-negative integer")

    def _get_examples(self) -> list[str]:
        """Get example usage strings for network stream producer."""
        return [
            "retrovue producer add --type network-stream --name 'Live Stream' --stream-url http://example.com/stream.m3u8",
            "retrovue producer add --type network-stream --name 'RTMP Stream' --stream-url rtmp://example.com/live/stream --timeout 60",
        ]



