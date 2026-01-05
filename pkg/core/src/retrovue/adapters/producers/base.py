"""
Base protocols and skeleton template for content producers.

This module defines the core interfaces that all producers must implement
and provides a complete skeleton template for creating new producers.

Producers are modular source components responsible for supplying playable media to a Renderer.
Each producer defines where content comes from — not how it's rendered or encoded.

Producers are designed to be input-driven, meaning they represent any source of audiovisual
material that can be fed into the playout pipeline. Examples include local files, test patterns,
synthetic feeds, network streams, or dynamically generated sequences.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


class ProducerInterface(Protocol):
    """
    Contract for all producers.

    Rules:
    - Must be stateless / pure: get_input_url() returns FFmpeg-compatible input strings, but does not persist.
    - Must raise ProducerError (or subclass) instead of exiting the process.
    - Must declare configuration schema via get_config_schema() so the CLI and registry can reason about it.
    - Must validate configuration parameters (file paths, connection settings, etc.).
    - Must declare updatable fields via get_update_fields() for dynamic CLI flag generation.
    - Must validate partial updates via validate_partial_update() to ensure update safety.
    """

    name: str
    """Unique type identifier, e.g. 'file', 'test-pattern', 'synthetic', 'network-stream'"""

    @classmethod
    def get_config_schema(cls) -> ProducerConfig:
        """
        Return the configuration schema for this producer type.

        This method defines what configuration parameters the producer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to configure the producer:
        - File Paths: Paths to media files
        - Connection Settings: URLs, ports, timeouts for network streams
        - Generation Settings: Parameters for synthetic/test pattern generation
        - Input Settings: Options for input source configuration

        Returns:
            ProducerConfig object defining the configuration schema
        """
        ...

    @abstractmethod
    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """
        Get an FFmpeg-compatible input specifier for this producer.

        This is the core method that returns the input source string that FFmpeg can consume.
        The returned string must be a valid FFmpeg input specifier (e.g., file path, lavfi: source, etc.).

        Args:
            context: Optional context dictionary containing runtime information
                    (e.g., asset_id, segment metadata, timing information)
                    that may influence input selection

        Returns:
            FFmpeg-compatible input string (e.g., '/path/to/file.mp4', 'lavfi:color=c=black:size=1920x1080:duration=10')

        Raises:
            ProducerError: If input URL cannot be generated
        """
        ...

    @abstractmethod
    def get_help(self) -> dict[str, Any]:
        """
        Get help information for this producer.

        Returns:
            Dictionary containing help information with keys:
            - description: Brief description of the producer
            - required_params: List of required parameter names
            - optional_params: List of optional parameter names with defaults
            - examples: List of example usage strings
        """
        ...

    def prepare(self, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Optional preparation hook called before get_input_url().

        This method can be used for:
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
        return None

    def cleanup(self, context: dict[str, Any] | None = None) -> None:
        """
        Optional cleanup hook called after input is no longer needed.

        This method can be used for:
        - Resource cleanup
        - Cache invalidation
        - Connection teardown

        Args:
            context: Optional context dictionary containing runtime information
        """
        pass

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for this producer.

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
        - Each provided key is valid for this producer
        - Type/format rules are enforced (e.g., file path exists, URL format valid)
        - Required relationships are maintained (if any)

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ProducerConfigurationError: If validation fails with a human-readable message
        """
        ...


class ProducerError(Exception):
    """Base exception for producer-related errors."""

    pass


class ProducerNotFoundError(ProducerError):
    """Raised when a requested producer is not found in the registry."""

    pass


class ProducerConfigurationError(ProducerError):
    """Raised when a producer is not properly configured."""

    pass


class ProducerInputError(ProducerError):
    """Raised when a producer cannot generate a valid input URL."""

    pass


@dataclass
class ProducerConfig:
    """
    Configuration schema for producer types.

    This defines the structure that producers use to declare
    their configuration requirements to the CLI and registry.

    Configuration parameters are specific values a producer needs to operate
    (file paths, connection settings, generation parameters, etc.).
    """

    required_params: list[dict[str, str]]
    """List of required configuration parameters with name and description"""
    optional_params: list[dict[str, str]]
    """List of optional configuration parameters with name, description, and default value"""
    description: str
    """Human-readable description of the producer and its configuration parameters"""


@dataclass
class UpdateFieldSpec:
    """
    Specification for an updatable configuration field.

    Used by producers to declare which configuration fields can be updated
    via the CLI, how they should appear as flags, and their validation requirements.
    """

    config_key: str
    """The key name in the configuration dictionary (e.g., "file_path", "pattern_type")"""

    cli_flag: str
    """The CLI flag name (e.g., "--file-path", "--pattern-type")"""

    help: str
    """Human-readable description for help text"""

    field_type: str
    """Type identifier: "string", "path", "int", "bool", etc."""

    is_sensitive: bool = False
    """Whether this field contains sensitive data that should be redacted in output"""

    is_immutable: bool = False
    """Whether this field cannot be updated after producer creation"""


class BaseProducer(ABC):
    """
    Abstract base class providing a complete skeleton for producer implementations.

    This class provides the foundation for creating new producers that comply
    with RetroVue's domain model and contract specifications.

    Producers use configuration parameters - specific values needed to operate
    (file paths, connection settings, generation parameters, etc.).

    To create a new producer:

    1. Copy the template to a new file in adapters/producers/
    2. Rename the class to match your producer type
    3. Implement the abstract methods
    4. Define your configuration schema
    5. Register the producer type

    Example:

    ```python
    class FileProducer(BaseProducer):
        name = "file"

        def __init__(self, file_path: str) -> None:
            super().__init__(file_path=file_path)
            self.file_path = file_path

        def get_input_url(self, context: dict[str, Any] | None = None) -> str:
            # Return FFmpeg-compatible file path
            return self.file_path

        @classmethod
        def get_config_schema(cls) -> ProducerConfig:
            return ProducerConfig(
                required_params=[
                    {"name": "file_path", "description": "Path to media file"}
                ],
                optional_params=[],
                description="File-based producer for local media files"
            )
    ```
    """

    # Override these in your implementation
    name: str = "base-producer"

    def __init__(self, **config: Any) -> None:
        """
        Initialize the producer with configuration parameters.

        Args:
            **config: Configuration parameters specific to this producer type
                     (file paths, connection settings, generation parameters, etc.)
        """
        self.config = config
        self._validate_config()

    @abstractmethod
    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """
        Get an FFmpeg-compatible input specifier for this producer.

        This is the core method that returns the input source string that FFmpeg can consume.
        The returned string must be a valid FFmpeg input specifier.

        Args:
            context: Optional context dictionary containing runtime information
                    (e.g., asset_id, segment metadata, timing information)

        Returns:
            FFmpeg-compatible input string

        Raises:
            ProducerError: If input URL cannot be generated
            ProducerInputError: If the input source is unavailable or invalid
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> ProducerConfig:
        """
        Return the configuration schema for this producer type.

        This method defines what configuration parameters the producer accepts,
        which are required vs optional.

        Configuration parameters are specific values needed to operate:
        - File Paths: Paths to media files
        - Connection Settings: URLs, ports, timeouts for network streams
        - Generation Settings: Parameters for synthetic/test pattern generation

        Returns:
            ProducerConfig object defining the configuration schema
        """
        pass

    def _validate_config(self) -> None:
        """
        Validate the producer's configuration parameters.

        Override this method to add custom validation logic.
        Raise ProducerConfigurationError for invalid configuration parameters.

        Raises:
            ProducerConfigurationError: If configuration parameters are invalid
        """
        schema = self.get_config_schema()

        # Validate required configuration parameters
        for param in schema.required_params:
            param_name = param["name"]
            if param_name not in self.config:
                raise ProducerConfigurationError(
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
        - File path existence checks
        - URL format validation
        - Connection timeout range validation
        - Pattern type validation
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
        Get help information for this producer.

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
        Get example usage strings for this producer.

        Override this method to provide specific examples.

        Returns:
            List of example usage strings
        """
        return [f"retrovue producer add --type {self.name} --name 'My {self.name.title()} Producer'"]

    def _get_cli_params(self) -> dict[str, str]:
        """
        Get CLI parameter descriptions for this producer.

        Override this method to provide specific CLI parameter descriptions.

        Returns:
            Dictionary mapping parameter names to descriptions
        """
        params = {}
        schema = self.get_config_schema()

        for param in schema.required_params + schema.optional_params:
            params[param["name"]] = param["description"]

        return params

    def prepare(self, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Optional preparation hook called before get_input_url().

        Default implementation returns None. Override to add preparation logic.

        Args:
            context: Optional context dictionary containing runtime information

        Returns:
            Optional metadata dictionary with preparation results, or None

        Raises:
            ProducerError: If preparation fails
        """
        return None

    def cleanup(self, context: dict[str, Any] | None = None) -> None:
        """
        Optional cleanup hook called after input is no longer needed.

        Default implementation does nothing. Override to add cleanup logic.

        Args:
            context: Optional context dictionary containing runtime information
        """
        pass

    @classmethod
    @abstractmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for this producer.

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
        - Each provided key is valid for this producer
        - Type/format rules are enforced (e.g., file path exists, URL format valid)
        - Required relationships are maintained (if any)

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ProducerConfigurationError: If validation fails with a human-readable message
        """
        pass

    def __str__(self) -> str:
        """String representation of the producer."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the producer."""
        config_str = json.dumps(self.config, sort_keys=True)
        return f"{self.__class__.__name__}(name='{self.name}', config={config_str})"


# Legacy Protocol for backward compatibility
class Producer(ProducerInterface):
    """
    Legacy Protocol for backward compatibility.

    This maintains the Protocol interface while the new BaseProducer
    provides the concrete implementation pattern.
    """

    pass


# Registration helper function
def register_producer_type(producer_class: type) -> None:
    """
    Register a producer type with the RetroVue registry.

    This function should be called during application startup
    to register new producer types.

    Args:
        producer_class: The producer class to register

    Example:

    ```python
    # In your producer module
    from ..base import register_producer_type

    class MyProducer(BaseProducer):
        # ... implementation ...
        pass

    # Register the producer type
    register_producer_type(MyProducer)
    ```
    """
    # This would integrate with the actual registry system
    # For now, it's a placeholder for the registration pattern
    pass



