"""
YAML-based auto-discovery channel configuration provider.

Scans a directory for *.yaml files (skipping _ prefixed partials)
and builds ChannelConfig objects from each file.

All fallback values come from resolved_config — this provider
defines NO defaults of its own.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import yaml

from retrovue.infra.exceptions import ConfigurationError
from ..config import ChannelConfig, ProgramFormat

_logger = logging.getLogger(__name__)


class _IncludeLoader(yaml.SafeLoader):
    """YAML loader with !include tag support."""
    pass


def _make_include_constructor(base_dir: Path):
    """Create an !include constructor that resolves relative to base_dir."""

    def _include(loader: yaml.Loader, node: yaml.Node) -> Any:
        value = loader.construct_scalar(node)
        if ":" in value and not value.startswith("/"):
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

    All default values come from resolved_config — this class defines none.
    """

    def __init__(
        self,
        config_dir: Path | str,
        resolved_config: Any = None,
    ):
        if resolved_config is None:
            raise RuntimeError(
                "resolved_config is required for YamlChannelConfigProvider — "
                "fallback defaults are no longer supported"
            )
        self._config_dir = Path(config_dir)
        self._resolved_config = resolved_config
        self._configs: dict[str, ChannelConfig] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()

    def _load(self) -> None:
        self._configs.clear()
        self._seen_numbers: set[int] = set()

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
            except ConfigurationError:
                raise
            except Exception as e:
                _logger.warning(
                    "Skipping invalid channel config %s: %s", yaml_file.name, e
                )

        # Channel number domain invariant
        numbers = [c.number for c in self._configs.values()]
        if len(numbers) != len(set(numbers)):
            raise ConfigurationError("Channel numbers must be unique")
        for n in numbers:
            if not isinstance(n, int):
                raise ConfigurationError(f"Channel number must be integer: {n}")
            if n <= 0:
                raise ConfigurationError(f"Channel number must be positive: {n}")

        _logger.info(
            "Loaded %d channel configs from %s",
            len(self._configs),
            self._config_dir,
        )
        self._loaded = True

    def _load_channel_file(self, yaml_file: Path) -> None:
        data = _load_yaml_with_includes(yaml_file)

        # --- H1: channel → channel_id migration ---
        channel_id = data.get("channel_id")
        if channel_id is None:
            channel_id = data.get("channel")
            if channel_id is not None:
                warnings.warn(
                    f"DEPRECATED: {yaml_file.name} uses 'channel:' — "
                    f"rename to 'channel_id:' to avoid collision with "
                    f"the governed 'channel' config domain.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        if not channel_id:
            raise ValueError(f"Missing 'channel_id' (or 'channel') field in {yaml_file.name}")

        # --- number (preferred) or channel_number (backward compat) ---
        raw_number = data.get("number")
        if raw_number is None:
            raw_number = data.get("channel_number")
            if raw_number is not None:
                warnings.warn(
                    f"DEPRECATED: {yaml_file.name} uses 'channel_number:' — "
                    f"rename to 'number:'.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        if raw_number is None:
            raise ConfigurationError(
                f"Missing 'number' (or 'channel_number') field in {yaml_file.name}. "
                "Channel number is required for Plex GuideNumber and must be a positive integer."
            )
        if not isinstance(raw_number, int):
            raise ConfigurationError(
                f"Channel number must be an integer in {yaml_file.name}, got {type(raw_number).__name__}"
            )
        if raw_number < 1:
            raise ConfigurationError(
                f"Channel number must be positive in {yaml_file.name}, got {raw_number}"
            )
        channel_number = raw_number

        if channel_id in self._configs:
            raise ConfigurationError(
                f"Duplicate channel id detected: {channel_id!r} (in {yaml_file.name})"
            )
        if hasattr(self, "_seen_numbers") and channel_number in self._seen_numbers:
            raise ConfigurationError(
                f"Duplicate channel number detected: {channel_number}"
            )

        # --- Defaults from resolved config ---
        _ch_cfg = self._resolved_config["channel"]
        _sched_cfg = self._resolved_config["scheduling"]
        _pf_defaults = _ch_cfg["default_program_format"]
        _filler_defaults = _ch_cfg["filler"]

        # --- Name ---
        name = data.get("name", _titleize(channel_id))

        # --- ProgramFormat from format section (fallbacks from resolved config) ---
        fmt = data.get("format", {})
        video = fmt.get("video", {})
        audio = fmt.get("audio", {})

        program_format = ProgramFormat(
            video_width=video.get("width", _pf_defaults["width"]),
            video_height=video.get("height", _pf_defaults["height"]),
            frame_rate=video.get("frame_rate", _pf_defaults["frame_rate"]),
            audio_sample_rate=audio.get("sample_rate", _pf_defaults["sample_rate"]),
            audio_channels=audio.get("channels", _pf_defaults["audio_channels"]),
            aspect_policy=video.get("aspect_policy", _pf_defaults["aspect_policy"]),
            video_bitrate=_ch_cfg["encoding"]["video_bitrate_bps"],
        )

        # --- Filler config (fallbacks from resolved config) ---
        filler = data.get("filler", {})
        if not isinstance(filler, dict):
            filler = {}
        filler_path = filler.get("path", _filler_defaults["path"])
        filler_duration_ms = filler.get("duration_ms", _filler_defaults["duration_ms"])

        # --- H2: grid_minutes migration ---
        grid_minutes: int | None = None

        # Legacy: format.grid_minutes
        if "grid_minutes" in fmt:
            warnings.warn(
                f"DEPRECATED: {yaml_file.name} has 'format.grid_minutes' — "
                f"grid geometry is a scheduling concern. Move to top-level "
                f"'grid_minutes:' or use a 'scheduling:' override.",
                DeprecationWarning,
                stacklevel=2,
            )
            grid_minutes = fmt["grid_minutes"]

        # Legacy: top-level grid_minutes
        if grid_minutes is None and "grid_minutes" in data:
            grid_minutes = data["grid_minutes"]

        # Fallback: derive from channel_type + scheduling config
        if grid_minutes is None:
            channel_type = data.get("channel_type", _sched_cfg["default_channel_type"])
            template = _sched_cfg["default_template"]
            if channel_type in ("premium", "movie"):
                template = "premium_movie"
            _grid_map = _sched_cfg["grid_minutes"]
            grid_minutes = _grid_map.get(template, _grid_map["network_television"])

        # --- channel_type and timezone (fallbacks from resolved config) ---
        channel_tz = data.get("timezone", _sched_cfg["default_timezone"])
        channel_type = data.get("channel_type", _sched_cfg["default_channel_type"])

        schedule_config = {
            "dsl_path": str(yaml_file),
            "filler_path": filler_path,
            "filler_duration_ms": filler_duration_ms,
            "grid_minutes": grid_minutes,
            "channel_tz": channel_tz,
            "channel_type": channel_type,
        }

        config = ChannelConfig(
            channel_id=channel_id,
            number=channel_number,
            channel_id_int=channel_number,
            name=name,
            program_format=program_format,
            schedule_source="dsl",
            schedule_config=schedule_config,
        )

        self._seen_numbers.add(channel_number)
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
        """Return channel configs as list of dicts (includes number for Plex/XMLTV)."""
        self._ensure_loaded()
        result = []
        for config in self._configs.values():
            result.append({
                "channel_id": config.channel_id,
                "number": config.number,
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
