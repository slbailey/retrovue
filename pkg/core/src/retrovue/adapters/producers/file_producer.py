"""
File producer for local media files.

This producer provides FFmpeg-compatible file paths for local media files.
It's the simplest producer type, directly returning file paths as input specifiers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    BaseProducer,
    ProducerConfig,
    ProducerConfigurationError,
    ProducerInputError,
    UpdateFieldSpec,
)


class FileProducer(BaseProducer):
    """
    File producer for local media files.

    This producer returns FFmpeg-compatible file paths for local media files.
    It validates that the file exists and is readable before returning the path.
    """

    name = "file"

    def __init__(self, file_path: str, **config: Any) -> None:
        """
        Initialize the file producer.

        Args:
            file_path: Path to the media file
            **config: Additional configuration parameters
        """
        initial_config: dict[str, Any] = {"file_path": file_path}
        initial_config.update(config)
        super().__init__(**initial_config)
        self.file_path = self.config["file_path"]

    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """
        Get the file path as an FFmpeg-compatible input specifier.

        Args:
            context: Optional context dictionary (unused for file producer)

        Returns:
            Absolute file path as a string

        Raises:
            ProducerInputError: If file does not exist or is not readable
        """
        file_path = Path(self.file_path).resolve()

        if not file_path.exists():
            raise ProducerInputError(f"File does not exist: {file_path}")

        if not file_path.is_file():
            raise ProducerInputError(f"Path is not a file: {file_path}")

        # Return absolute path as string (FFmpeg-compatible)
        return str(file_path)

    @classmethod
    def get_config_schema(cls) -> ProducerConfig:
        """
        Return the configuration schema for file producer.

        Returns:
            ProducerConfig with required file_path parameter
        """
        return ProducerConfig(
            required_params=[
                {"name": "file_path", "description": "Path to the media file"}
            ],
            optional_params=[],
            description="File-based producer for local media files. Returns FFmpeg-compatible file paths.",
        )

    def _validate_parameter_types(self) -> None:
        """Validate that file_path is a non-empty string."""
        file_path = self._safe_get_config("file_path")
        if not isinstance(file_path, str):
            raise ProducerConfigurationError("file_path must be a string")

        if not file_path.strip():
            raise ProducerConfigurationError("file_path cannot be empty")

        path_obj = Path(file_path)
        if path_obj.exists() and not path_obj.is_file():
            raise ProducerConfigurationError(f"Path exists but is not a file: {path_obj}")

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return updatable fields for file producer.

        Returns:
            List of UpdateFieldSpec objects
        """
        return [
            UpdateFieldSpec(
                config_key="file_path",
                cli_flag="--file-path",
                help="Path to the media file",
                field_type="path",
                is_sensitive=False,
                is_immutable=False,
            )
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate partial configuration update for file producer.

        Args:
            partial_config: Dictionary containing fields to update

        Raises:
            ProducerConfigurationError: If validation fails
        """
        if "file_path" in partial_config:
            file_path = partial_config["file_path"]
            if not isinstance(file_path, str):
                raise ProducerConfigurationError("file_path must be a string")

            if not file_path.strip():
                raise ProducerConfigurationError("file_path cannot be empty")

            # Check if file exists (warn but don't fail if it doesn't exist yet)
            path = Path(file_path)
            if path.exists() and not path.is_file():
                raise ProducerConfigurationError(f"Path exists but is not a file: {path}")

    def _get_examples(self) -> list[str]:
        """Get example usage strings for file producer."""
        return [
            "retrovue producer add --type file --name 'Movie Producer' --file-path /media/movie.mp4",
            "retrovue producer add --type file --name 'Show Producer' --file-path /path/to/episode.mkv",
        ]

