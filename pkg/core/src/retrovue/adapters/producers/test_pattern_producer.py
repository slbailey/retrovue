"""
Test pattern producer for generating synthetic test patterns.

This producer generates FFmpeg lavfi (libavfilter) input specifiers for various
test patterns like color bars, test cards, and solid colors.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseProducer,
    ProducerConfig,
    ProducerConfigurationError,
    UpdateFieldSpec,
)

# Supported test pattern types
PATTERN_TYPES = {
    "color-bars": "video=smptebars=size={size}:rate={rate}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "smpte-bars": "video=smptebars=size={size}:rate={rate}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "testsrc": "video=testsrc=size={size}:rate={rate}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "color-red": "video=color=c=red:size={size}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "color-green": "video=color=c=green:size={size}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "color-blue": "video=color=c=blue:size={size}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "color-black": "video=color=c=black:size={size}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
    "color-white": "video=color=c=white:size={size}{duration_clause}|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}",
}


class TestPatternProducer(BaseProducer):
    """
    Test pattern producer for synthetic test patterns.

    This producer generates FFmpeg lavfi input specifiers for various test patterns.
    Useful for test signals, standby screens, or fallback content.
    """

    name = "test-pattern"

    def __init__(
        self,
        pattern_type: str = "color-bars",
        width: int = 1920,
        height: int = 1080,
        duration: int | None = None,
        frame_rate: int = 30,
        audio_sample_rate: int = 48000,
        **config: Any,
    ) -> None:
        """
        Initialize the test pattern producer.

        Args:
            pattern_type: Type of test pattern (color-bars, smpte-bars, color-red, etc.)
            width: Width of the pattern in pixels (default: 1920)
            height: Height of the pattern in pixels (default: 1080)
            duration: Duration in seconds (default: None for infinite)
            **config: Additional configuration parameters
        """
        initial_config: dict[str, Any] = {
            "pattern_type": pattern_type,
            "width": width,
            "height": height,
            "duration": duration,
            "frame_rate": frame_rate,
            "audio_sample_rate": audio_sample_rate,
        }
        initial_config.update(config)

        super().__init__(**initial_config)

        # Cache validated configuration on the instance
        self.pattern_type = self.config["pattern_type"]
        self.width = self.config["width"]
        self.height = self.config["height"]
        self.duration = self.config.get("duration")
        self.frame_rate = self.config.get("frame_rate", 30)
        self.audio_sample_rate = self.config.get("audio_sample_rate", 48000)

    def get_input_url(self, context: dict[str, Any] | None = None) -> str:
        """
        Get the FFmpeg lavfi input specifier for the test pattern.

        Args:
            context: Optional context dictionary (unused for test pattern producer)

        Returns:
            FFmpeg lavfi input specifier string
        """
        size = f"{self.width}x{self.height}"
        rate = self.frame_rate
        audio_rate = self.audio_sample_rate
        duration_clause = ""
        if self.duration is not None:
            duration_clause = f":duration={self.duration}"

        # Handle predefined patterns
        if self.pattern_type in PATTERN_TYPES:
            base_pattern = PATTERN_TYPES[self.pattern_type]
            spec = base_pattern.format(
                size=size,
                rate=rate,
                audio_rate=audio_rate,
                duration_clause=duration_clause,
            )
            return f"lavfi:{spec}"

        # Handle custom color patterns (format: "color-<color_name>")
        if self.pattern_type.startswith("color-"):
            color = self.pattern_type.replace("color-", "")
            return (
                f"lavfi:video=color=c={color}:size={size}{duration_clause}"
                f"|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}"
            )

        return (
            f"lavfi:video=smptebars=size={size}:rate={rate}{duration_clause}"
            f"|audio=sine=frequency=1000:sample_rate={audio_rate}{duration_clause}"
        )

    @classmethod
    def get_config_schema(cls) -> ProducerConfig:
        """
        Return the configuration schema for test pattern producer.

        Returns:
            ProducerConfig with pattern configuration parameters
        """
        return ProducerConfig(
            required_params=[],
            optional_params=[
                {
                    "name": "pattern_type",
                    "description": "Type of test pattern (color-bars, smpte-bars, color-red, etc.)",
                    "default": "color-bars",
                },
                {"name": "width", "description": "Width of the pattern in pixels", "default": "1920"},
                {"name": "height", "description": "Height of the pattern in pixels", "default": "1080"},
                {
                    "name": "duration",
                    "description": "Duration in seconds (None for infinite)",
                    "default": "None",
                },
                {
                    "name": "frame_rate",
                    "description": "Frame rate for dynamic patterns (frames per second)",
                    "default": "30",
                },
                {
                    "name": "audio_sample_rate",
                    "description": "Audio sample rate for generated tone",
                    "default": "48000",
                },
            ],
            description="Test pattern producer for synthetic test patterns. Generates FFmpeg lavfi input specifiers.",
        )

    def _validate_parameter_types(self) -> None:
        """Validate configuration parameter types and values."""
        pattern_type = self._safe_get_config("pattern_type")
        if not isinstance(pattern_type, str):
            raise ProducerConfigurationError("pattern_type must be a string")

        width = self._safe_get_config("width")
        if not isinstance(width, int) or width <= 0:
            raise ProducerConfigurationError("width must be a positive integer")

        height = self._safe_get_config("height")
        if not isinstance(height, int) or height <= 0:
            raise ProducerConfigurationError("height must be a positive integer")

        duration = self._safe_get_config("duration")
        if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
            raise ProducerConfigurationError("duration must be a positive number or None")

        frame_rate = self._safe_get_config("frame_rate", 30)
        if not isinstance(frame_rate, int) or frame_rate <= 0:
            raise ProducerConfigurationError("frame_rate must be a positive integer")

        audio_sample_rate = self._safe_get_config("audio_sample_rate", 48000)
        if not isinstance(audio_sample_rate, int) or audio_sample_rate <= 0:
            raise ProducerConfigurationError("audio_sample_rate must be a positive integer")

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return updatable fields for test pattern producer.

        Returns:
            List of UpdateFieldSpec objects
        """
        return [
            UpdateFieldSpec(
                config_key="pattern_type",
                cli_flag="--pattern-type",
                help="Type of test pattern (color-bars, smpte-bars, color-red, etc.)",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="width",
                cli_flag="--width",
                help="Width of the pattern in pixels",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="height",
                cli_flag="--height",
                help="Height of the pattern in pixels",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="duration",
                cli_flag="--duration",
                help="Duration in seconds (None for infinite)",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="frame_rate",
                cli_flag="--frame-rate",
                help="Frame rate for dynamic patterns (frames per second)",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="audio_sample_rate",
                cli_flag="--audio-sample-rate",
                help="Audio sample rate for generated tone",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate partial configuration update for test pattern producer.

        Args:
            partial_config: Dictionary containing fields to update

        Raises:
            ProducerConfigurationError: If validation fails
        """
        if "pattern_type" in partial_config:
            if not isinstance(partial_config["pattern_type"], str):
                raise ProducerConfigurationError("pattern_type must be a string")

        if "width" in partial_config:
            width = partial_config["width"]
            if not isinstance(width, int) or width <= 0:
                raise ProducerConfigurationError("width must be a positive integer")

        if "height" in partial_config:
            height = partial_config["height"]
            if not isinstance(height, int) or height <= 0:
                raise ProducerConfigurationError("height must be a positive integer")

        if "duration" in partial_config:
            duration = partial_config["duration"]
            if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
                raise ProducerConfigurationError("duration must be a positive number or None")

        if "frame_rate" in partial_config:
            frame_rate = partial_config["frame_rate"]
            if not isinstance(frame_rate, int) or frame_rate <= 0:
                raise ProducerConfigurationError("frame_rate must be a positive integer")

        if "audio_sample_rate" in partial_config:
            audio_sample_rate = partial_config["audio_sample_rate"]
            if not isinstance(audio_sample_rate, int) or audio_sample_rate <= 0:
                raise ProducerConfigurationError("audio_sample_rate must be a positive integer")

    def _get_examples(self) -> list[str]:
        """Get example usage strings for test pattern producer."""
        return [
            "retrovue producer add --type test-pattern --name 'Color Bars' --pattern-type color-bars --frame-rate 30 --audio-sample-rate 48000",
            "retrovue producer add --type test-pattern --name 'SMPTE Bars' --pattern-type smpte-bars --width 1920 --height 1080 --frame-rate 60 --audio-sample-rate 48000",
            "retrovue producer add --type test-pattern --name 'Black Screen' --pattern-type color-black --duration 60 --audio-sample-rate 44100",
        ]

