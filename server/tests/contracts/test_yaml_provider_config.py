"""
Contract tests for YamlChannelConfigProvider config integration.

Validates:
- Provider requires resolved_config (no hardcoded defaults)
- Legacy 'channel:' key emits deprecation warning
- Legacy 'channel_number:' key emits deprecation warning
- Legacy 'format.grid_minutes' emits deprecation warning
- ProgramFormat defaults come from resolved_config, not hardcoded
- Filler defaults come from resolved_config, not hardcoded
- channel_type / timezone fallbacks come from resolved_config
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG, make_test_config
from retrovue.runtime.providers.yaml_channel_config_provider import (
    YamlChannelConfigProvider,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_channel(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Config requirement
# ---------------------------------------------------------------------------

class TestConfigRequired:

    def test_none_config_raises(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="resolved_config is required"):
            YamlChannelConfigProvider(tmp_path, resolved_config=None)

    def test_explicit_config_accepted(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        assert p.list_channel_ids() == ["ch"]


# ---------------------------------------------------------------------------
# H1: channel → channel_id migration
# ---------------------------------------------------------------------------

class TestChannelIdMigration:

    def test_legacy_channel_key_emits_warning(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
            p.list_channel_ids()
        dep = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert any("channel_id" in str(d.message) for d in dep)

    def test_new_channel_id_key_no_warning(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel_id: ch\nnumber: 1\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
            p.list_channel_ids()
        dep = [x for x in w if issubclass(x.category, DeprecationWarning) and "channel_id" in str(x.message)]
        assert len(dep) == 0

    def test_channel_id_key_loads_correctly(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel_id: my-ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        assert p.get_channel_config("my-ch") is not None


# ---------------------------------------------------------------------------
# Legacy channel_number warning
# ---------------------------------------------------------------------------

class TestChannelNumberMigration:

    def test_legacy_channel_number_emits_warning(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel: ch\nchannel_number: 1\n")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
            p.list_channel_ids()
        dep = [x for x in w if issubclass(x.category, DeprecationWarning) and "channel_number" in str(x.message)]
        assert len(dep) == 1


# ---------------------------------------------------------------------------
# H2: grid_minutes migration
# ---------------------------------------------------------------------------

class TestGridMinutesMigration:

    def test_format_grid_minutes_emits_warning(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", (
            "channel: ch\nnumber: 1\n"
            "format:\n  grid_minutes: 15\n  video: {width: 1280, height: 720}\n"
        ))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
            cfg = p.get_channel_config("ch")
        dep = [x for x in w if issubclass(x.category, DeprecationWarning) and "grid_minutes" in str(x.message)]
        assert len(dep) == 1
        assert cfg.schedule_config["grid_minutes"] == 15

    def test_no_grid_minutes_uses_scheduling_default(self, tmp_path: Path):
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        # Default channel_type is "network" → template is "network_television" → 30
        assert cfg.schedule_config["grid_minutes"] == 30


# ---------------------------------------------------------------------------
# Defaults come from resolved_config, not hardcoded
# ---------------------------------------------------------------------------

class TestDefaultsFromConfig:

    def test_program_format_width_from_config(self, tmp_path: Path):
        """When format.video.width is omitted, default comes from config."""
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        # TEST_RESOLVED_CONFIG has default_program_format.width = 1920
        assert cfg.program_format.video_width == 1920

    def test_program_format_width_override(self, tmp_path: Path):
        """When format.video.width is provided, it overrides config."""
        _write_channel(tmp_path, "ch", (
            "channel: ch\nnumber: 1\n"
            "format:\n  video: {width: 640, height: 480}\n"
        ))
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        assert cfg.program_format.video_width == 640

    def test_custom_config_changes_default(self, tmp_path: Path):
        """A custom resolved_config with different width flows through."""
        custom = make_test_config(channel={
            **dict(TEST_RESOLVED_CONFIG["channel"]),
            "default_program_format": {
                "width": 720,
                "height": 576,
                "frame_rate": "25/1",
                "sample_rate": 48000,
                "audio_channels": 2,
                "aspect_policy": "preserve",
            },
        })
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=custom)
        cfg = p.get_channel_config("ch")
        assert cfg.program_format.video_width == 720
        assert cfg.program_format.video_height == 576

    def test_filler_defaults_from_config(self, tmp_path: Path):
        """Filler path/duration come from resolved_config when absent from YAML."""
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        assert cfg.schedule_config["filler_path"] == "/opt/retrovue/assets/filler.mp4"
        assert cfg.schedule_config["filler_duration_ms"] == 3650000

    def test_filler_override_from_yaml(self, tmp_path: Path):
        """Explicit filler in YAML overrides config defaults."""
        _write_channel(tmp_path, "ch", (
            "channel: ch\nnumber: 1\n"
            "filler:\n  path: /custom/filler.mp4\n  duration_ms: 5000\n"
        ))
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        assert cfg.schedule_config["filler_path"] == "/custom/filler.mp4"
        assert cfg.schedule_config["filler_duration_ms"] == 5000

    def test_schedule_config_overrides_dsl_path(self, tmp_path: Path):
        """Top-level schedule_config.dsl_path overrides the default (this YAML file)."""
        _write_channel(tmp_path, "ch", (
            "channel_id: ch\nnumber: 1\n"
            "schedule_config:\n"
            "  dsl_path: /opt/retrovue/config/channels/network.yaml\n"
        ))
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        assert cfg.schedule_config["dsl_path"] == "/opt/retrovue/config/channels/network.yaml"

    def test_timezone_fallback_from_config(self, tmp_path: Path):
        """timezone comes from scheduling.default_timezone when absent."""
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        # TEST_RESOLVED_CONFIG has scheduling.default_timezone = "UTC"
        assert cfg.schedule_config["channel_tz"] == "UTC"

    def test_channel_type_fallback_from_config(self, tmp_path: Path):
        """channel_type comes from scheduling.default_channel_type when absent."""
        _write_channel(tmp_path, "ch", "channel: ch\nnumber: 1\n")
        p = YamlChannelConfigProvider(tmp_path, resolved_config=TEST_RESOLVED_CONFIG)
        cfg = p.get_channel_config("ch")
        assert cfg.schedule_config["channel_type"] == "network"
