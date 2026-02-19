"""
YAML-based auto-discovery channel configuration provider.

Scans a directory for *.yaml files (skipping _ prefixed partials)
and builds ChannelConfig objects from each file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from ..config import ChannelConfig, ProgramFormat

_logger = logging.getLogger(__name__)


class _IncludeLoader(yaml.SafeLoader):
    """YAML loader with !include tag support."""
    pass


def _make_include_constructor(base_dir: Path):
    """Create an !include constructor that resolves relative to base_dir."""

    def _include(loader: yaml.Loader, node: yaml.Node) -> Any:
        value = loader.construct_scalar(node)
        # Support "file.yaml" or "file.yaml:key.path"
        if ":" in value and not value.startswith("/"):
            # Could be file:key or /abs/path  
            parts = value.split(":", 1)
            file_part, key_path = parts
        else:
            file_part = value
            key_path = None

        file_path = base_dir / file_part
        if not file_path.exists():
            _logger.warning("Include file not found: %s", file_path)
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if key_path:
            for key in key_path.split("."):
                if isinstance(data, dict):
                    data = data.get(key)
                else:
                    _logger.warning("Cannot traverse key '%s' in %s", key, file_part)
                    return None

        return data

    return _include


def _load_yaml_with_includes(file_path: Path) -> dict[str, Any]:
    """Load a YAML file with !include tag support."""
    base_dir = file_path.parent

    # Create a fresh loader class each time to avoid cross-contamination
    loader_cls = type("IncludeLoader", (yaml.SafeLoader,), {})
    loader_cls.add_constructor("!include", _make_include_constructor(base_dir))

    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=loader_cls) or {}


def _titleize(slug: str) -> str:
    """Convert 'nightmare-theater' to 'Nightmare Theater'."""
    return slug.replace("-", " ").replace("_", " ").title()


class YamlChannelConfigProvider:
    """
    ChannelConfigProvider that auto-discovers channel configs from YAML files.

    Scans a directory for *.yaml files (skipping _ prefixed partials),
    parses each and builds ChannelConfig objects.
    """

    def __init__(self, config_dir: Path | str):
        self._config_dir = Path(config_dir)
        self._configs: dict[str, ChannelConfig] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()

    def _load(self) -> None:
        self._configs.clear()

        if not self._config_dir.is_dir():
            _logger.warning("Channel config directory not found: %s", self._config_dir)
            self._loaded = True
            return

        yaml_files = sorted(self._config_dir.glob("*.yaml"))
        for yaml_file in yaml_files:
            if yaml_file.name.startswith("_"):
                continue
            try:
                self._load_channel_file(yaml_file)
            except Exception as e:
                _logger.warning(
                    "Skipping invalid channel config %s: %s", yaml_file.name, e
                )

        _logger.info(
            "Loaded %d channel configs from %s",
            len(self._configs),
            self._config_dir,
        )
        self._loaded = True

    def _load_channel_file(self, yaml_file: Path) -> None:
        data = _load_yaml_with_includes(yaml_file)

        channel_id = data.get("channel")
        if not channel_id:
            raise ValueError(f"Missing 'channel' field in {yaml_file.name}")

        channel_number = data.get("channel_number")
        if channel_number is None:
            raise ValueError(f"Missing 'channel_number' field in {yaml_file.name}")

        name = data.get("name", _titleize(channel_id))

        # Build ProgramFormat from format section (with defaults)
        fmt = data.get("format", {})
        video = fmt.get("video", {})
        audio = fmt.get("audio", {})

        program_format = ProgramFormat(
            video_width=video.get("width", 1280),
            video_height=video.get("height", 720),
            frame_rate=video.get("frame_rate", "30/1"),
            audio_sample_rate=audio.get("sample_rate", 48000),
            audio_channels=audio.get("channels", 2),
        )

        # Build filler config
        filler = data.get("filler", {})
        if not isinstance(filler, dict):
            filler = {}
        filler_path = filler.get("path", "/opt/retrovue/assets/filler.mp4")
        filler_duration_ms = filler.get("duration_ms", 3650000)

        grid_minutes = fmt.get("grid_minutes", data.get("grid_minutes", 30))

        # Channel timezone for broadcast day computation (used by PlaylogHorizonDaemon)
        channel_tz = data.get("timezone", "UTC")

        schedule_config = {
            "dsl_path": str(yaml_file),
            "filler_path": filler_path,
            "filler_duration_ms": filler_duration_ms,
            "grid_minutes": grid_minutes,
            "channel_tz": channel_tz,
        }

        config = ChannelConfig(
            channel_id=channel_id,
            channel_id_int=int(channel_number),
            name=name,
            program_format=program_format,
            schedule_source="dsl",
            schedule_config=schedule_config,
        )

        self._configs[channel_id] = config
        _logger.debug(
            "Loaded channel config: %s (int_id=%d) from %s",
            config.channel_id,
            config.channel_id_int,
            yaml_file.name,
        )

    def reload(self) -> None:
        """Force reload of configs from directory."""
        self._loaded = False
        self._load()

    def get_channel_config(self, channel_id: str) -> ChannelConfig | None:
        self._ensure_loaded()
        return self._configs.get(channel_id)

    def list_channel_ids(self) -> list[str]:
        self._ensure_loaded()
        return list(self._configs.keys())

    def to_channels_list(self) -> list[dict[str, Any]]:
        """Return channel configs as list of dicts (compatible with channels.json format)."""
        self._ensure_loaded()
        result = []
        for config in self._configs.values():
            result.append({
                "channel_id": config.channel_id,
                "channel_id_int": config.channel_id_int,
                "name": config.name,
                "program_format": {
                    "video": {
                        "width": config.program_format.video_width,
                        "height": config.program_format.video_height,
                        "frame_rate": config.program_format.frame_rate,
                    },
                    "audio": {
                        "sample_rate": config.program_format.audio_sample_rate,
                        "channels": config.program_format.audio_channels,
                    },
                },
                "schedule_source": config.schedule_source,
                "schedule_config": config.schedule_config,
            })
        return result


__all__ = [
    "YamlChannelConfigProvider",
]
