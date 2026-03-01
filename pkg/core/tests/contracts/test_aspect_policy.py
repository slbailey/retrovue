"""
INV-ASPECT-PRESERVE-001 — Aspect policy contract tests.

Validates:
- ProgramFormat.to_json() includes aspect_policy in video object
- ProgramFormat.from_dict() parses aspect_policy correctly
- Default aspect_policy is "preserve"
- YamlChannelConfigProvider reads aspect_policy from YAML
- YamlChannelConfigProvider defaults aspect_policy when absent
"""

import json
import tempfile
from pathlib import Path

import pytest

from retrovue.runtime.config import ProgramFormat
from retrovue.runtime.providers.yaml_channel_config_provider import (
    YamlChannelConfigProvider,
)


class TestProgramFormatAspectPolicy:
    """INV-ASPECT-PRESERVE-001: ProgramFormat aspect_policy field."""

    def test_default_aspect_policy(self):
        """Default aspect_policy MUST be 'preserve'."""
        pf = ProgramFormat(
            video_width=1280,
            video_height=720,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
        )
        assert pf.aspect_policy == "preserve"

    def test_to_json_includes_aspect_policy(self):
        """to_json() MUST include aspect_policy in the video object."""
        pf = ProgramFormat(
            video_width=1280,
            video_height=720,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
        )
        data = json.loads(pf.to_json())
        assert "aspect_policy" in data["video"]
        assert data["video"]["aspect_policy"] == "preserve"

    def test_to_json_includes_custom_aspect_policy(self):
        """to_json() MUST include non-default aspect_policy."""
        pf = ProgramFormat(
            video_width=1280,
            video_height=720,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
            aspect_policy="stretch",
        )
        data = json.loads(pf.to_json())
        assert data["video"]["aspect_policy"] == "stretch"

    def test_from_dict_reads_aspect_policy_nested(self):
        """from_dict() MUST parse aspect_policy from nested format."""
        data = {
            "video": {
                "width": 1280,
                "height": 720,
                "frame_rate": "30000/1001",
                "aspect_policy": "stretch",
            },
            "audio": {"sample_rate": 48000, "channels": 2},
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.aspect_policy == "stretch"

    def test_from_dict_defaults_aspect_policy_nested(self):
        """from_dict() MUST default aspect_policy to 'preserve' when absent."""
        data = {
            "video": {"width": 1280, "height": 720, "frame_rate": "30000/1001"},
            "audio": {"sample_rate": 48000, "channels": 2},
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.aspect_policy == "preserve"

    def test_from_dict_reads_aspect_policy_flat(self):
        """from_dict() MUST parse aspect_policy from flat format."""
        data = {
            "video_width": 1280,
            "video_height": 720,
            "frame_rate": "30000/1001",
            "audio_sample_rate": 48000,
            "audio_channels": 2,
            "aspect_policy": "stretch",
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.aspect_policy == "stretch"


class TestYamlProviderAspectPolicy:
    """INV-ASPECT-PRESERVE-001: YAML provider aspect_policy reading."""

    def test_yaml_provider_reads_aspect_policy(self, tmp_path: Path):
        """YAML with aspect_policy MUST produce correct ProgramFormat."""
        yaml_content = """\
channel: test-channel
channel_number: 99
name: Test Channel
format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001", aspect_policy: "stretch" }
  audio: { sample_rate: 48000, channels: 2 }
schedule_source: dsl
"""
        yaml_file = tmp_path / "test-channel.yaml"
        yaml_file.write_text(yaml_content)

        provider = YamlChannelConfigProvider(tmp_path)
        config = provider.get_channel_config("test-channel")
        assert config is not None
        assert config.program_format.aspect_policy == "stretch"

    def test_yaml_provider_default_aspect_policy(self, tmp_path: Path):
        """YAML without aspect_policy MUST default to 'preserve'."""
        yaml_content = """\
channel: test-channel
channel_number: 99
name: Test Channel
format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
schedule_source: dsl
"""
        yaml_file = tmp_path / "test-channel.yaml"
        yaml_file.write_text(yaml_content)

        provider = YamlChannelConfigProvider(tmp_path)
        config = provider.get_channel_config("test-channel")
        assert config is not None
        assert config.program_format.aspect_policy == "preserve"
