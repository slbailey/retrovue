"""
Unit tests for channel configuration data structures.

Tests ProgramFormat, ChannelConfig, and providers.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from retrovue.runtime.config import (
    ProgramFormat,
    ChannelConfig,
    InlineChannelConfigProvider,
    DEFAULT_PROGRAM_FORMAT,
    MOCK_CHANNEL_CONFIG,
)
from retrovue.runtime.providers import FileChannelConfigProvider


class TestProgramFormat:
    """Tests for ProgramFormat dataclass."""

    def test_to_json_produces_valid_json(self):
        """to_json() returns valid JSON matching AIR contract format."""
        pf = ProgramFormat(
            video_width=1920,
            video_height=1080,
            frame_rate="30/1",
            audio_sample_rate=48000,
            audio_channels=2,
        )
        result = pf.to_json()
        parsed = json.loads(result)

        assert parsed["video"]["width"] == 1920
        assert parsed["video"]["height"] == 1080
        assert parsed["video"]["frame_rate"] == "30/1"
        assert parsed["audio"]["sample_rate"] == 48000
        assert parsed["audio"]["channels"] == 2

    def test_from_dict_nested_format(self):
        """from_dict() parses nested video/audio format."""
        data = {
            "video": {"width": 1280, "height": 720, "frame_rate": "30000/1001"},
            "audio": {"sample_rate": 44100, "channels": 1},
        }
        pf = ProgramFormat.from_dict(data)

        assert pf.video_width == 1280
        assert pf.video_height == 720
        assert pf.frame_rate == "30000/1001"
        assert pf.audio_sample_rate == 44100
        assert pf.audio_channels == 1

    def test_from_dict_flat_format(self):
        """from_dict() parses flat format."""
        data = {
            "video_width": 3840,
            "video_height": 2160,
            "frame_rate": "60/1",
            "audio_sample_rate": 96000,
            "audio_channels": 6,
        }
        pf = ProgramFormat.from_dict(data)

        assert pf.video_width == 3840
        assert pf.video_height == 2160
        assert pf.frame_rate == "60/1"
        assert pf.audio_sample_rate == 96000
        assert pf.audio_channels == 6

    def test_frozen_immutable(self):
        """ProgramFormat is frozen/immutable."""
        pf = DEFAULT_PROGRAM_FORMAT
        with pytest.raises(AttributeError):
            pf.video_width = 1280  # type: ignore


class TestChannelConfig:
    """Tests for ChannelConfig dataclass."""

    def test_from_dict_full(self):
        """from_dict() parses complete channel config."""
        data = {
            "channel_id": "retro1",
            "channel_id_int": 5,
            "name": "Retro Channel 1",
            "program_format": {
                "video": {"width": 1920, "height": 1080, "frame_rate": "30/1"},
                "audio": {"sample_rate": 48000, "channels": 2},
            },
            "schedule_source": "file",
            "schedule_config": {"path": "/schedules/retro1.json"},
        }
        cc = ChannelConfig.from_dict(data)

        assert cc.channel_id == "retro1"
        assert cc.channel_id_int == 5
        assert cc.name == "Retro Channel 1"
        assert cc.program_format.video_width == 1920
        assert cc.schedule_source == "file"
        assert cc.schedule_config["path"] == "/schedules/retro1.json"

    def test_from_dict_defaults(self):
        """from_dict() uses defaults for optional fields."""
        data = {
            "channel_id": "test",
            "channel_id_int": 99,
            "name": "Test Channel",
        }
        cc = ChannelConfig.from_dict(data)

        assert cc.schedule_source == "mock"
        assert cc.schedule_config == {}
        # Default program format
        assert cc.program_format == DEFAULT_PROGRAM_FORMAT

    def test_frozen_immutable(self):
        """ChannelConfig is frozen/immutable."""
        cc = MOCK_CHANNEL_CONFIG
        with pytest.raises(AttributeError):
            cc.channel_id = "other"  # type: ignore


class TestInlineChannelConfigProvider:
    """Tests for InlineChannelConfigProvider."""

    def test_empty_provider(self):
        """Empty provider returns None and empty list."""
        provider = InlineChannelConfigProvider()
        assert provider.get_channel_config("mock") is None
        assert provider.list_channel_ids() == []

    def test_with_initial_configs(self):
        """Provider initialized with configs."""
        configs = [MOCK_CHANNEL_CONFIG]
        provider = InlineChannelConfigProvider(configs)

        assert provider.get_channel_config("mock") is MOCK_CHANNEL_CONFIG
        assert provider.list_channel_ids() == ["mock"]

    def test_add_config(self):
        """add_config() adds new configs."""
        provider = InlineChannelConfigProvider()
        provider.add_config(MOCK_CHANNEL_CONFIG)

        assert provider.get_channel_config("mock") is MOCK_CHANNEL_CONFIG
        assert "mock" in provider.list_channel_ids()


class TestFileChannelConfigProvider:
    """Tests for FileChannelConfigProvider."""

    def test_load_valid_file(self):
        """FileChannelConfigProvider loads valid JSON file."""
        content = json.dumps({
            "channels": [
                {
                    "channel_id": "test",
                    "channel_id_int": 10,
                    "name": "Test Channel",
                    "program_format": {
                        "video": {"width": 1920, "height": 1080, "frame_rate": "30/1"},
                        "audio": {"sample_rate": 48000, "channels": 2},
                    },
                    "schedule_source": "mock",
                    "schedule_config": {},
                }
            ]
        })

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            provider = FileChannelConfigProvider(path)
            config = provider.get_channel_config("test")

            assert config is not None
            assert config.channel_id == "test"
            assert config.channel_id_int == 10
            assert config.name == "Test Channel"
            assert "test" in provider.list_channel_ids()
        finally:
            path.unlink()

    def test_missing_file(self):
        """FileChannelConfigProvider handles missing file gracefully."""
        provider = FileChannelConfigProvider(Path("/nonexistent/channels.json"))

        assert provider.get_channel_config("mock") is None
        assert provider.list_channel_ids() == []

    def test_reload(self):
        """reload() re-reads from file."""
        content1 = json.dumps({
            "channels": [
                {"channel_id": "ch1", "channel_id_int": 1, "name": "Channel 1"}
            ]
        })
        content2 = json.dumps({
            "channels": [
                {"channel_id": "ch2", "channel_id_int": 2, "name": "Channel 2"}
            ]
        })

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(content1)
            f.flush()
            path = Path(f.name)

        try:
            provider = FileChannelConfigProvider(path)
            assert "ch1" in provider.list_channel_ids()
            assert "ch2" not in provider.list_channel_ids()

            # Update file
            with open(path, "w") as f:
                f.write(content2)

            # Reload
            provider.reload()
            assert "ch1" not in provider.list_channel_ids()
            assert "ch2" in provider.list_channel_ids()
        finally:
            path.unlink()
