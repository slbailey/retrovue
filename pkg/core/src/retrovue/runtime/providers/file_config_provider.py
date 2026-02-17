"""
File-based channel configuration provider.

Loads channel configurations from a JSON file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import ChannelConfig, ChannelConfigProvider

_logger = logging.getLogger(__name__)


class FileChannelConfigProvider:
    """
    ChannelConfigProvider that loads configurations from a JSON file.

    Expected JSON format (schedule_source must be blockplan, e.g. "phase3"):
    {
      "channels": [
        {
          "channel_id": "cheers-24-7",
          "channel_id_int": 1,
          "name": "Cheers 24/7",
          "program_format": {...},
          "schedule_source": "phase3",
          "schedule_config": {"programs_dir": "...", "schedules_dir": "...", ...}
        }
      ]
    }
    """

    def __init__(self, config_path: Path | str):
        """
        Initialize the provider.

        Args:
            config_path: Path to the channels.json file
        """
        self._config_path = Path(config_path)
        self._configs: dict[str, ChannelConfig] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load configs from file if not already loaded."""
        if self._loaded:
            return

        if not self._config_path.exists():
            _logger.warning(
                "Channel config file not found: %s",
                self._config_path,
            )
            self._loaded = True
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            channels_data = data.get("channels", [])
            for channel_data in channels_data:
                try:
                    config = ChannelConfig.from_dict(channel_data)
                    self._configs[config.channel_id] = config
                    _logger.debug(
                        "Loaded channel config: %s (int_id=%d)",
                        config.channel_id,
                        config.channel_id_int,
                    )
                except (KeyError, ValueError, TypeError) as e:
                    _logger.warning(
                        "Skipping invalid channel config: %s (error: %s)",
                        channel_data.get("channel_id", "<unknown>"),
                        e,
                    )

            _logger.info(
                "Loaded %d channel configs from %s",
                len(self._configs),
                self._config_path,
            )

        except json.JSONDecodeError as e:
            _logger.error(
                "Failed to parse channel config file %s: %s",
                self._config_path,
                e,
            )
        except OSError as e:
            _logger.error(
                "Failed to read channel config file %s: %s",
                self._config_path,
                e,
            )

        self._loaded = True

    def reload(self) -> None:
        """Force reload of configs from file."""
        self._loaded = False
        self._configs.clear()
        self._ensure_loaded()

    def get_channel_config(self, channel_id: str) -> ChannelConfig | None:
        """
        Get configuration for a channel by ID.

        Args:
            channel_id: Human-readable channel ID

        Returns:
            ChannelConfig if found, None otherwise
        """
        self._ensure_loaded()
        return self._configs.get(channel_id)

    def list_channel_ids(self) -> list[str]:
        """
        List all available channel IDs.

        Returns:
            List of channel IDs
        """
        self._ensure_loaded()
        return list(self._configs.keys())



    def to_channels_list(self):
        """Return channel configs as list of dicts (compatible with channels.json format)."""
        self._ensure_loaded()
        result = []
        for config in self._configs.values():
            result.append({
                'channel_id': config.channel_id,
                'channel_id_int': config.channel_id_int,
                'name': config.name,
                'program_format': {
                    'video': {
                        'width': config.program_format.video_width,
                        'height': config.program_format.video_height,
                        'frame_rate': config.program_format.frame_rate,
                    },
                    'audio': {
                        'sample_rate': config.program_format.audio_sample_rate,
                        'channels': config.program_format.audio_channels,
                    },
                },
                'schedule_source': config.schedule_source,
                'schedule_config': config.schedule_config,
            })
        return result


__all__ = [
    "FileChannelConfigProvider",
]
