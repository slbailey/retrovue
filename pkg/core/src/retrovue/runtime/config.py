"""
Channel configuration data structures and protocols.

Defines ProgramFormat and ChannelConfig for channel configuration,
and ChannelConfigProvider protocol for accessing channel configs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProgramFormat:
    """
    Technical format specification for a channel's output.

    Matches the program_format_json contract in AIR:
    pkg/air/docs/contracts/architecture/PlayoutInstanceAndProgramFormatContract.md
    """
    video_width: int
    video_height: int
    frame_rate: str  # "30/1", "30000/1001", etc.
    audio_sample_rate: int
    audio_channels: int

    @property
    def frame_rate_num(self) -> int:
        """Frame rate numerator (INV-FRAME-003)."""
        try:
            parts = self.frame_rate.split("/")
            return int(parts[0])
        except (ValueError, IndexError):
            return 30  # Default to 30fps

    @property
    def frame_rate_den(self) -> int:
        """Frame rate denominator (INV-FRAME-003)."""
        try:
            parts = self.frame_rate.split("/")
            return int(parts[1]) if len(parts) > 1 else 1
        except (ValueError, IndexError):
            return 1  # Default denominator

    def to_json(self) -> str:
        """Serialize to JSON string for AIR gRPC."""
        return json.dumps({
            "video": {
                "width": self.video_width,
                "height": self.video_height,
                "frame_rate": self.frame_rate,
            },
            "audio": {
                "sample_rate": self.audio_sample_rate,
                "channels": self.audio_channels,
            },
        })

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgramFormat:
        """
        Deserialize from dict (e.g. loaded from JSON).

        Accepts either flat format or nested video/audio format:

        Flat:
            {"video_width": 1920, "video_height": 1080, ...}

        Nested:
            {"video": {"width": 1920, "height": 1080, "frame_rate": "30/1"},
             "audio": {"sample_rate": 48000, "channels": 2}}
        """
        if "video" in data and "audio" in data:
            # Nested format
            video = data["video"]
            audio = data["audio"]
            return cls(
                video_width=video["width"],
                video_height=video["height"],
                frame_rate=video["frame_rate"],
                audio_sample_rate=audio["sample_rate"],
                audio_channels=audio["channels"],
            )
        else:
            # Flat format
            return cls(
                video_width=data["video_width"],
                video_height=data["video_height"],
                frame_rate=data["frame_rate"],
                audio_sample_rate=data["audio_sample_rate"],
                audio_channels=data["audio_channels"],
            )


# Default program format: 1080p30, 48kHz stereo
DEFAULT_PROGRAM_FORMAT = ProgramFormat(
    video_width=1920,
    video_height=1080,
    frame_rate="30/1",
    audio_sample_rate=48000,
    audio_channels=2,
)


@dataclass(frozen=True)
class ChannelConfig:
    """
    Configuration for a single channel.

    Combines:
    - Human-readable ID (channel_id) for URLs and logs
    - Integer ID (channel_id_int) for AIR gRPC
    - Display name
    - Technical program format
    - Schedule source configuration
    """
    channel_id: str           # Human ID ("mock", "retro1")
    channel_id_int: int       # AIR gRPC ID (1, 2, 3...)
    name: str
    program_format: ProgramFormat
    schedule_source: str      # "mock", "file", "grid"
    schedule_config: dict[str, Any] = field(default_factory=dict)
    blockplan_only: bool = False  # When True, only BlockPlanProducer is permitted

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChannelConfig:
        """Deserialize from dict (e.g. loaded from JSON)."""
        program_format_data = data.get("program_format", {})
        return cls(
            channel_id=data["channel_id"],
            channel_id_int=data["channel_id_int"],
            name=data["name"],
            program_format=ProgramFormat.from_dict(program_format_data) if program_format_data else DEFAULT_PROGRAM_FORMAT,
            schedule_source=data.get("schedule_source", "mock"),
            schedule_config=data.get("schedule_config", {}),
            blockplan_only=data.get("blockplan_only", False),
        )


class ChannelConfigProvider(Protocol):
    """Protocol for providing channel configuration."""

    def get_channel_config(self, channel_id: str) -> ChannelConfig | None:
        """
        Get configuration for a channel by ID.

        Args:
            channel_id: Human-readable channel ID

        Returns:
            ChannelConfig if found, None otherwise
        """
        ...

    def list_channel_ids(self) -> list[str]:
        """
        List all available channel IDs.

        Returns:
            List of channel IDs
        """
        ...


class InlineChannelConfigProvider:
    """
    Simple in-memory channel config provider.

    Useful for testing or when configs are constructed programmatically.
    """

    def __init__(self, configs: list[ChannelConfig] | None = None):
        self._configs: dict[str, ChannelConfig] = {}
        if configs:
            for config in configs:
                self._configs[config.channel_id] = config

    def add_config(self, config: ChannelConfig) -> None:
        """Add or replace a channel config."""
        self._configs[config.channel_id] = config

    def get_channel_config(self, channel_id: str) -> ChannelConfig | None:
        """Get configuration for a channel by ID."""
        return self._configs.get(channel_id)

    def list_channel_ids(self) -> list[str]:
        """List all available channel IDs."""
        return list(self._configs.keys())


# Default mock channel config (backwards compatibility)
MOCK_CHANNEL_CONFIG = ChannelConfig(
    channel_id="mock",
    channel_id_int=1,
    name="Mock Channel",
    program_format=DEFAULT_PROGRAM_FORMAT,
    schedule_source="mock",
    schedule_config={},
)


@dataclass
class RuntimeConfig:
    """
    Global runtime configuration for RetroVue.

    Loaded from config/retrovue.json or fallback defaults.
    Uses absolute paths to /opt/retrovue/config/ by default.
    """
    program_director_port: int = 8000
    channel_manager_port: int = 9000
    channels_config: str = "/opt/retrovue/config/channels.json"
    schedules_dir: str = "/opt/retrovue/config/schedules"

    @classmethod
    def load(cls, path: str | None = None) -> "RuntimeConfig":
        """
        Load configuration from JSON file, or return defaults if not found.

        Search order:
        1. Explicit path (if provided)
        2. config/retrovue.json (relative to cwd)
        3. /opt/retrovue/config/retrovue.json

        Args:
            path: Optional explicit path to config file

        Returns:
            RuntimeConfig instance (defaults if no file found)
        """
        from pathlib import Path

        # Default paths (absolute)
        default_channels = "/opt/retrovue/config/channels.json"
        default_schedules = "/opt/retrovue/config/schedules"

        candidates = [
            Path(path) if path else None,
            Path("config/retrovue.json"),
            Path("/opt/retrovue/config/retrovue.json"),
        ]

        for candidate in candidates:
            if candidate and candidate.exists():
                try:
                    data = json.loads(candidate.read_text())
                    return cls(
                        program_director_port=data.get("program_director_port", 8000),
                        channel_manager_port=data.get("channel_manager_port", 9000),
                        channels_config=data.get("channels_config", default_channels),
                        schedules_dir=data.get("schedules_dir", default_schedules),
                    )
                except (json.JSONDecodeError, OSError):
                    # Fall through to defaults on error
                    pass

        return cls()  # Return defaults

    def get_channels_config_path(self) -> "Path":
        """Get resolved Path to channels config file."""
        from pathlib import Path
        return Path(self.channels_config)

    def get_schedules_dir_path(self) -> "Path":
        """Get resolved Path to schedules directory."""
        from pathlib import Path
        return Path(self.schedules_dir)


__all__ = [
    "ProgramFormat",
    "ChannelConfig",
    "ChannelConfigProvider",
    "InlineChannelConfigProvider",
    "RuntimeConfig",
    "DEFAULT_PROGRAM_FORMAT",
    "MOCK_CHANNEL_CONFIG",
]
