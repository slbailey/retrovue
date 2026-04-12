"""
Template for creating new RetroVue renderers.

Copy this file to create a new renderer implementation.
Rename the file and class to match your renderer type.

This template shows how to implement renderers with configuration parameters -
specific values needed to configure the renderer (output settings, encoding options, etc.).

Renderers are modular output components responsible for consuming producer input
and generating output streams. Each renderer defines how content is rendered
and encoded — not where it comes from.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseRenderer,
    RendererConfig,
    RendererConfigurationError,
    RendererError,
    RendererStartupError,
    UpdateFieldSpec,
)


class YourRendererName(BaseRenderer):
    """
    Your renderer description here.

    This renderer [describe what it does and how it works].

    Configuration Parameters:
    - Describe what configuration parameters this renderer needs
    - Examples: output settings, encoding options, process settings
    """

    # Change these to your renderer type name
    name = "your-renderer-type"

    def __init__(self, **config: Any) -> None:
        """
        Initialize your renderer with configuration parameters.

        Args:
            **config: Configuration parameters (define these in get_config_schema)
                     Examples: output settings, encoding options, process settings
        """
        super().__init__(**config)

        # Store configuration parameters
        # Example:
        # self.output_port = config.get("output_port", 8080)  # Optional configuration parameter
        # self.output_format = config["output_format"]  # Required configuration parameter
        # self.encoding_preset = config.get("encoding_preset", "medium")  # Optional configuration parameter

    def start(self, input_url: str, context: dict[str, Any] | None = None) -> str:
        """
        Start rendering the input source and return a stream endpoint.

        This is the core method that starts the rendering process and returns
        an endpoint that can be used to access the output stream.

        Args:
            input_url: FFmpeg-compatible input source (from producer.get_input_url())
            context: Optional context dictionary containing runtime information
                    (e.g., channel_id, asset_id, segment metadata, timing information)

        Returns:
            Stream endpoint URL or identifier (e.g., 'http://localhost:8080/stream/123', 'pipe:1')

        Raises:
            RendererError: If rendering cannot be started
            RendererStartupError: If the rendering process fails to start
        """
        try:
            # TODO: Implement your rendering startup logic here

            # Example: Start FFmpeg process
            # self._start_ffmpeg_process(input_url)

            # Example: Start HTTP server
            # endpoint = self._start_http_server()

            # Example: Create output file
            # endpoint = self._create_output_file(input_url)

            # Replace with actual implementation
            raise NotImplementedError("start() must be implemented")

        except RendererError:
            raise
        except Exception as e:
            raise RendererError(f"Failed to start renderer: {str(e)}") from e

    def stop(self) -> bool:
        """
        Stop the rendering process and clean up resources.

        Returns:
            True if rendering stopped successfully, False otherwise

        Raises:
            RendererError: If rendering cannot be stopped
        """
        try:
            # TODO: Implement your rendering stop logic here

            # Example: Stop FFmpeg process
            # self._stop_ffmpeg_process()

            # Example: Stop HTTP server
            # self._stop_http_server()

            # Example: Clean up output file
            # self._cleanup_output_file()

            # Replace with actual implementation
            return True

        except Exception as e:
            raise RendererError(f"Failed to stop renderer: {str(e)}") from e

    def get_stream_endpoint(self) -> str | None:
        """
        Get the current stream endpoint.

        Returns:
            Stream endpoint URL or identifier, or None if not available
        """
        # TODO: Return the current stream endpoint
        # Example:
        # if self._running:
        #     return self._stream_endpoint
        # return None

        return None

    def is_running(self) -> bool:
        """
        Check if the renderer is currently running.

        Returns:
            True if renderer is running, False otherwise
        """
        # TODO: Return whether the renderer is running
        # Example:
        # return self._running

        return False

    @classmethod
    def get_config_schema(cls) -> RendererConfig:
        """
        Define the configuration schema for your renderer.

        Configuration parameters are specific values needed to operate:
        - Output Settings: Stream endpoints, output formats, quality settings
        - Encoding Options: Codec settings, bitrates, presets
        - Process Settings: Timeouts, retry counts, resource limits

        Returns:
            RendererConfig object defining required and optional configuration parameters
        """
        return RendererConfig(
            required_params=[
                # Define required configuration parameters here
                # Example:
                # {"name": "output_format", "description": "Output format (e.g., 'mpegts', 'hls', 'dash')"}
                # {"name": "output_url", "description": "Output URL or path"}
            ],
            optional_params=[
                # Define optional configuration parameters here
                # Example:
                # {"name": "output_port", "description": "Output port for HTTP streaming", "default": "8080"}
                # {"name": "encoding_preset", "description": "Encoding preset", "default": "medium"}
                # {"name": "timeout", "description": "Process timeout in seconds", "default": "30"}
            ],
            description="Brief description of what this renderer does and its configuration parameters",
        )

    def _validate_parameter_types(self) -> None:
        """
        Validate configuration parameter types and values.

        Override this method to add custom validation logic for configuration parameters.
        Examples:
        - Port number range validation
        - URL format validation
        - Timeout range validation
        - Codec preset validation

        Raise RendererConfigurationError for invalid configuration parameters.
        """
        # TODO: Add validation for your specific configuration parameters

        # Example validation for different parameter types:

        # Port number validation:
        # port = self._safe_get_config("output_port", 8080)
        # if not isinstance(port, int) or port < 1 or port > 65535:
        #     raise RendererConfigurationError("output_port must be an integer between 1 and 65535")

        # URL format validation:
        # output_url = self._safe_get_config("output_url")
        # if output_url and not output_url.startswith(("http://", "https://", "file://")):
        #     raise RendererConfigurationError("output_url must start with http://, https://, or file://")

        # Encoding preset validation:
        # preset = self._safe_get_config("encoding_preset", "medium")
        # valid_presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        # if preset not in valid_presets:
        #     raise RendererConfigurationError(f"encoding_preset must be one of {valid_presets}")

        pass

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Define the updatable configuration fields for your renderer.

        This method defines which configuration fields can be updated via the CLI,
        how they should appear as command-line flags, and their metadata (sensitivity,
        immutability, type).

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        # TODO: Define updatable fields for your renderer

        # Example:
        # return [
        #     UpdateFieldSpec(
        #         config_key="output_port",
        #         cli_flag="--output-port",
        #         help="Output port for HTTP streaming",
        #         field_type="int",
        #         is_sensitive=False,
        #         is_immutable=False,
        #     ),
        #     UpdateFieldSpec(
        #         config_key="encoding_preset",
        #         cli_flag="--encoding-preset",
        #         help="Encoding preset",
        #         field_type="string",
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
        - Each provided key is valid for this renderer
        - Type/format rules are enforced (e.g., port range valid, URL format valid)
        - Required relationships are maintained (if any)

        validate_partial_update(partial_config: dict) MUST:
        - ensure each provided key is valid for this renderer,
        - enforce type/format rules (e.g. port range valid, URL format valid),
        - enforce required relationships (if any),
        - raise a validation error with a human-readable message on failure.

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            RendererConfigurationError: If validation fails with a human-readable message
        """
        # TODO: Add validation for partial updates

        # Example:
        # if "output_port" in partial_config:
        #     port = partial_config["output_port"]
        #     if not isinstance(port, int) or port < 1 or port > 65535:
        #         raise RendererConfigurationError("output_port must be an integer between 1 and 65535")
        #
        # if "output_url" in partial_config:
        #     url = partial_config["output_url"]
        #     if not isinstance(url, str):
        #         raise RendererConfigurationError("output_url must be a string")
        #
        #     if not url.startswith(("http://", "https://", "file://")):
        #         raise RendererConfigurationError("output_url must start with http://, https://, or file://")

        pass

    def _get_examples(self) -> list[str]:
        """
        Get example usage strings for this renderer.

        Override this method to provide specific examples.

        Returns:
            List of example usage strings
        """
        # TODO: Provide specific examples for your renderer

        # Example:
        # return [
        #     f"retrovue renderer add --type {self.name} --name 'My Renderer' --output-port 8080",
        #     f"retrovue renderer add --type {self.name} --name 'Another Renderer' --output-port 8081 --encoding-preset fast",
        # ]

        return super()._get_examples()


# Example: HLS Renderer
class ExampleHLSRenderer(BaseRenderer):
    """
    Example HLS renderer.

    This is an example implementation showing how to create a renderer
    for HLS (HTTP Live Streaming) output.
    """

    name = "hls"

    def __init__(self, output_dir: str, segment_duration: int = 10, playlist_size: int = 5, **config: Any) -> None:
        """Initialize the HLS renderer."""
        super().__init__(output_dir=output_dir, segment_duration=segment_duration, playlist_size=playlist_size, **config)
        self.output_dir = output_dir
        self.segment_duration = segment_duration
        self.playlist_size = playlist_size
        self._running = False
        self._stream_endpoint = None

    def start(self, input_url: str, context: dict[str, Any] | None = None) -> str:
        """Start HLS rendering and return playlist URL."""
        # This is a simplified example - real implementation would:
        # 1. Create output directory
        # 2. Build FFmpeg command for HLS output
        # 3. Start FFmpeg process
        # 4. Return playlist URL

        from pathlib import Path

        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        playlist_path = output_path / "playlist.m3u8"
        self._stream_endpoint = f"http://localhost:8080/hls/{playlist_path.name}"
        self._running = True

        return self._stream_endpoint

    def stop(self) -> bool:
        """Stop HLS rendering."""
        self._running = False
        self._stream_endpoint = None
        return True

    def get_stream_endpoint(self) -> str | None:
        """Get the playlist URL."""
        return self._stream_endpoint if self._running else None

    def is_running(self) -> bool:
        """Check if renderer is running."""
        return self._running

    @classmethod
    def get_config_schema(cls) -> RendererConfig:
        """Return the configuration schema for HLS renderer."""
        return RendererConfig(
            required_params=[
                {"name": "output_dir", "description": "Output directory for HLS segments and playlist"}
            ],
            optional_params=[
                {
                    "name": "segment_duration",
                    "description": "Duration of each HLS segment in seconds",
                    "default": "10",
                },
                {
                    "name": "playlist_size",
                    "description": "Number of segments to keep in playlist",
                    "default": "5",
                },
            ],
            description="HLS renderer for HTTP Live Streaming output",
        )

    def _validate_parameter_types(self) -> None:
        """Validate configuration parameter types and values."""
        if not isinstance(self.output_dir, str):
            raise RendererConfigurationError("output_dir must be a string")

        if not self.output_dir.strip():
            raise RendererConfigurationError("output_dir cannot be empty")

        if not isinstance(self.segment_duration, int) or self.segment_duration <= 0:
            raise RendererConfigurationError("segment_duration must be a positive integer")

        if not isinstance(self.playlist_size, int) or self.playlist_size <= 0:
            raise RendererConfigurationError("playlist_size must be a positive integer")

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """Return updatable fields for HLS renderer."""
        return [
            UpdateFieldSpec(
                config_key="output_dir",
                cli_flag="--output-dir",
                help="Output directory for HLS segments and playlist",
                field_type="path",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="segment_duration",
                cli_flag="--segment-duration",
                help="Duration of each HLS segment in seconds",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="playlist_size",
                cli_flag="--playlist-size",
                help="Number of segments to keep in playlist",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """Validate partial configuration update for HLS renderer."""
        if "output_dir" in partial_config:
            output_dir = partial_config["output_dir"]
            if not isinstance(output_dir, str):
                raise RendererConfigurationError("output_dir must be a string")

            if not output_dir.strip():
                raise RendererConfigurationError("output_dir cannot be empty")

        if "segment_duration" in partial_config:
            duration = partial_config["segment_duration"]
            if not isinstance(duration, int) or duration <= 0:
                raise RendererConfigurationError("segment_duration must be a positive integer")

        if "playlist_size" in partial_config:
            size = partial_config["playlist_size"]
            if not isinstance(size, int) or size <= 0:
                raise RendererConfigurationError("playlist_size must be a positive integer")

    def _get_examples(self) -> list[str]:
        """Get example usage strings for HLS renderer."""
        return [
            "retrovue renderer add --type hls --name 'HLS Renderer' --output-dir /var/www/hls",
            "retrovue renderer add --type hls --name 'Custom HLS' --output-dir /var/www/hls --segment-duration 5 --playlist-size 10",
        ]



