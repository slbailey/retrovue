"""
Base protocols and skeleton template for content renderers.

This module defines the core interfaces that all renderers must implement
and provides a complete skeleton template for creating new renderers.

Renderers are modular output components responsible for consuming producer input
and generating output streams. Each renderer defines how content is rendered
and encoded — not where it comes from.

Renderers are designed to be output-driven, meaning they represent any method
of generating output streams from input sources. Examples include FFmpeg-based
MPEG-TS streaming, HLS output, DASH output, or custom encoding pipelines.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


class RendererInterface(Protocol):
    """
    Contract for all renderers.

    Rules:
    - Must manage output generation from input sources.
    - Must raise RendererError (or subclass) instead of exiting the process.
    - Must declare configuration schema via get_config_schema() so the CLI and registry can reason about it.
    - Must validate configuration parameters (output settings, encoding options, etc.).
    - Must declare updatable fields via get_update_fields() for dynamic CLI flag generation.
    - Must validate partial updates via validate_partial_update() to ensure update safety.
    """

    name: str
    """Unique type identifier, e.g. 'ffmpeg-ts', 'hls', 'dash', 'custom'"""

    @classmethod
    def get_config_schema(cls) -> RendererConfig:
        """
        Return the configuration schema for this renderer type.

        This method defines what configuration parameters the renderer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to configure the renderer:
        - Output Settings: Stream endpoints, output formats, quality settings
        - Encoding Options: Codec settings, bitrates, presets
        - Process Settings: Timeouts, retry counts, resource limits

        Returns:
            RendererConfig object defining the configuration schema
        """
        ...

    @abstractmethod
    def start(self, input_url: str | None = None, context: dict[str, Any] | None = None) -> str:
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
        """
        ...

    @abstractmethod
    def stop(self) -> bool:
        """
        Stop the rendering process and clean up resources.

        Returns:
            True if rendering stopped successfully, False otherwise

        Raises:
            RendererError: If rendering cannot be stopped
        """
        ...

    @abstractmethod
    def get_stream_endpoint(self) -> str | None:
        """
        Get the current stream endpoint.

        Returns:
            Stream endpoint URL or identifier, or None if not available
        """
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """
        Check if the renderer is currently running.

        Returns:
            True if renderer is running, False otherwise
        """
        ...

    @abstractmethod
    def switch_source(self, source: Any, context: dict[str, Any] | None = None) -> str:
        """
        Switch the renderer to a new input source.

        Args:
            source: Either an FFmpeg-compatible input string or an object with
                    a ``get_input_url`` method (e.g., a producer instance).
            context: Optional context dictionary containing runtime information.

        Returns:
            Stream endpoint URL or identifier for the newly started stream.

        Raises:
            RendererError: If the renderer cannot switch sources.
        """
        ...

    @abstractmethod
    def get_help(self) -> dict[str, Any]:
        """
        Get help information for this renderer.

        Returns:
            Dictionary containing help information with keys:
            - description: Brief description of the renderer
            - required_params: List of required parameter names
            - optional_params: List of optional parameter names with defaults
            - examples: List of example usage strings
        """
        ...

    def health(self) -> dict[str, Any]:
        """
        Get health status of the renderer.

        Returns:
            Dictionary containing health status information
        """
        return {"status": "unknown", "running": self.is_running()}


class RendererError(Exception):
    """Base exception for renderer-related errors."""

    pass


class RendererNotFoundError(RendererError):
    """Raised when a requested renderer is not found in the registry."""

    pass


class RendererConfigurationError(RendererError):
    """Raised when a renderer is not properly configured."""

    pass


class RendererStartupError(RendererError):
    """Raised when a renderer cannot start rendering."""

    pass


@dataclass
class RendererConfig:
    """
    Configuration schema for renderer types.

    This defines the structure that renderers use to declare
    their configuration requirements to the CLI and registry.

    Configuration parameters are specific values a renderer needs to operate
    (output settings, encoding options, process settings, etc.).
    """

    required_params: list[dict[str, str]]
    """List of required configuration parameters with name and description"""
    optional_params: list[dict[str, str]]
    """List of optional configuration parameters with name, description, and default value"""
    description: str
    """Human-readable description of the renderer and its configuration parameters"""


@dataclass
class UpdateFieldSpec:
    """
    Specification for an updatable configuration field.

    Used by renderers to declare which configuration fields can be updated
    via the CLI, how they should appear as flags, and their validation requirements.
    """

    config_key: str
    """The key name in the configuration dictionary (e.g., "output_url", "video_preset")"""

    cli_flag: str
    """The CLI flag name (e.g., "--output-url", "--video-preset")"""

    help: str
    """Human-readable description for help text"""

    field_type: str
    """Type identifier: "string", "int", "bool", "path", etc."""

    is_sensitive: bool = False
    """Whether this field contains sensitive data that should be redacted in output"""

    is_immutable: bool = False
    """Whether this field cannot be updated after renderer creation"""


class BaseRenderer(ABC):
    """
    Abstract base class providing a complete skeleton for renderer implementations.

    This class provides the foundation for creating new renderers that comply
    with RetroVue's domain model and contract specifications.

    Renderers use configuration parameters - specific values needed to operate
    (output settings, encoding options, process settings, etc.).

    To create a new renderer:

    1. Copy the template to a new file in adapters/renderers/
    2. Rename the class to match your renderer type
    3. Implement the abstract methods
    4. Define your configuration schema
    5. Register the renderer in src/retrovue/adapters/registry.py

    Example:

    ```python
    class FFmpegTSRenderer(BaseRenderer):
        name = "ffmpeg-ts"

        def __init__(self, output_port: int = 8080, **config: Any) -> None:
            super().__init__(output_port=output_port, **config)
            self.output_port = output_port

        def start(self, input_url: str, context: dict[str, Any] | None = None) -> str:
            # Start FFmpeg process and return stream endpoint
            pass

        @classmethod
        def get_config_schema(cls) -> RendererConfig:
            return RendererConfig(
                required_params=[],
                optional_params=[
                    {"name": "output_port", "description": "Output port for stream", "default": "8080"}
                ],
                description="FFmpeg-based MPEG-TS renderer"
            )
    ```
    """

    # Override these in your implementation
    name: str = "base-renderer"

    def __init__(self, **config: Any) -> None:
        """
        Initialize the renderer with configuration parameters.

        Args:
            **config: Configuration parameters specific to this renderer type
                     (output settings, encoding options, process settings, etc.)
        """
        self.config = config
        self._last_input_url: str | None = None
        self._validate_config()

    @abstractmethod
    def start(self, input_url: str, context: dict[str, Any] | None = None) -> str:
        """
        Start rendering the input source and return a stream endpoint.

        Args:
            input_url: FFmpeg-compatible input source (from producer.get_input_url()).
                If omitted, the renderer SHOULD reuse the most recent input supplied
                via ``start`` or ``switch_source``.
            context: Optional context dictionary containing runtime information

        Returns:
            Stream endpoint URL or identifier

        Raises:
            RendererError: If rendering cannot be started
            RendererStartupError: If the rendering process fails to start
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """
        Stop the rendering process and clean up resources.

        Returns:
            True if rendering stopped successfully, False otherwise

        Raises:
            RendererError: If rendering cannot be stopped
        """
        pass

    @abstractmethod
    def get_stream_endpoint(self) -> str | None:
        """
        Get the current stream endpoint.

        Returns:
            Stream endpoint URL or identifier, or None if not available
        """
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """
        Check if the renderer is currently running.

        Returns:
            True if renderer is running, False otherwise
        """
        pass

    def switch_source(self, source: Any, context: dict[str, Any] | None = None) -> str:
        """
        Switch the renderer to a new input source.

        By default, this will stop the renderer if it is currently running and
        then start it again using the provided source. Subclasses may override
        this method if they can perform a seamless source switch without a full
        restart.

        Args:
            source: Either an FFmpeg-compatible input string or an object with a
                    ``get_input_url`` method (e.g., a producer instance).
            context: Optional context dictionary containing runtime information.

        Returns:
            Stream endpoint URL or identifier for the newly started stream.

        Raises:
            RendererError: If the renderer cannot switch sources.
        """

        # Resolve the input URL from the provided source
        input_url: str
        if isinstance(source, str):
            input_url = source
        elif hasattr(source, "get_input_url") and callable(getattr(source, "get_input_url")):
            input_url = source.get_input_url()  # type: ignore[assignment]
        else:
            raise RendererError(
                "switch_source expects an input URL string or an object with a 'get_input_url' method"
            )

        self._last_input_url = input_url

        if self.is_running():
            stopped = self.stop()
            if not stopped:
                raise RendererError("Failed to stop renderer before switching source")

        return self.start(input_url, context=context)

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> RendererConfig:
        """
        Return the configuration schema for this renderer type.

        This method defines what configuration parameters the renderer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to operate:
        - Output Settings: Stream endpoints, output formats, quality settings
        - Encoding Options: Codec settings, bitrates, presets
        - Process Settings: Timeouts, retry counts, resource limits

        Returns:
            RendererConfig object defining the configuration schema
        """
        pass

    def _validate_config(self) -> None:
        """
        Validate the renderer's configuration parameters.

        Override this method to add custom validation logic.
        Raise RendererConfigurationError for invalid configuration parameters.

        Raises:
            RendererConfigurationError: If configuration parameters are invalid
        """
        schema = self.get_config_schema()

        # Validate required configuration parameters
        for param in schema.required_params:
            param_name = param["name"]
            if param_name not in self.config:
                raise RendererConfigurationError(
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
        - Port number range validation
        - URL format validation
        - Timeout range validation
        - Codec preset validation
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
        Get help information for this renderer.

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
        Get example usage strings for this renderer.

        Override this method to provide specific examples.

        Returns:
            List of example usage strings
        """
        return [f"retrovue renderer add --type {self.name} --name 'My {self.name.title()} Renderer'"]

    def _get_cli_params(self) -> dict[str, str]:
        """
        Get CLI parameter descriptions for this renderer.

        Override this method to provide specific CLI parameter descriptions.

        Returns:
            Dictionary mapping parameter names to descriptions
        """
        params = {}
        schema = self.get_config_schema()

        for param in schema.required_params + schema.optional_params:
            params[param["name"]] = param["description"]

        return params

    def health(self) -> dict[str, Any]:
        """
        Get health status of the renderer.

        Returns:
            Dictionary containing health status information
        """
        return {"status": "unknown", "running": self.is_running()}

    @classmethod
    @abstractmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for this renderer.

        This method defines which configuration fields can be updated via the CLI,
        how they should appear as command-line flags, and their metadata (sensitivity,
        immutability, type).

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
        - Each provided key is valid for this renderer
        - Type/format rules are enforced (e.g., port range valid, URL format valid)
        - Required relationships are maintained (if any)

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            RendererConfigurationError: If validation fails with a human-readable message
        """
        pass

    def __str__(self) -> str:
        """String representation of the renderer."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the renderer."""
        config_str = json.dumps(self.config, sort_keys=True)
        return f"{self.__class__.__name__}(name='{self.name}', config={config_str})"


# Legacy Protocol for backward compatibility
class Renderer(RendererInterface):
    """
    Legacy Protocol for backward compatibility.

    This maintains the Protocol interface while the new BaseRenderer
    provides the concrete implementation pattern.
    """

    pass


# Registration helper function
def register_renderer_type(renderer_class: type) -> None:
    """
    Register a renderer type with the RetroVue registry.

    This function should be called during application startup
    to register new renderer types.

    Args:
        renderer_class: The renderer class to register

    Example:

    ```python
    # In your renderer module
    from ..base import register_renderer_type

    class MyRenderer(BaseRenderer):
        # ... implementation ...
        pass

    # Register the renderer type
    register_renderer_type(MyRenderer)
    ```
    """
    # This would integrate with the actual registry system
    # For now, it's a placeholder for the registration pattern
    pass

