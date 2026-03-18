"""
Contract tests: Per-Channel Video Bitrate

Contract: pkg/air/docs/contracts/semantics/PlayoutInstanceAndProgramFormatContract.md §5.3
Invariant: video_bitrate flows from channel config through ProgramFormat JSON to AIR encoding layer.

Rules:
- Default bitrate is 8000000 when not specified.
- Custom bitrate is respected when set in ProgramFormat.
- video_bitrate is in the "encoding" section of the JSON, NOT in ProgramFormat proper.
"""

import json
import pytest

from retrovue.runtime.config import ProgramFormat, ChannelConfig, DEFAULT_PROGRAM_FORMAT


class TestProgramFormatVideoBitrate:
    """ProgramFormat video_bitrate encoding hint."""

    def test_default_bitrate_when_not_specified(self):
        """Default video_bitrate is 8000000 when not explicitly set."""
        pf = ProgramFormat(
            video_width=1920,
            video_height=1080,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
        )
        assert pf.video_bitrate == 8_000_000

    def test_custom_bitrate_respected(self):
        """Custom video_bitrate is preserved."""
        pf = ProgramFormat(
            video_width=1920,
            video_height=1080,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
            video_bitrate=5_000_000,
        )
        assert pf.video_bitrate == 5_000_000

    def test_bitrate_in_encoding_section_of_json(self):
        """video_bitrate appears in 'encoding' section, not in 'video' or 'audio'."""
        pf = ProgramFormat(
            video_width=1920,
            video_height=1080,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
            video_bitrate=6_000_000,
        )
        data = json.loads(pf.to_json())
        # Must be in encoding section
        assert data["encoding"]["video_bitrate"] == 6_000_000
        # Must NOT be in video section
        assert "video_bitrate" not in data["video"]
        assert "bitrate" not in data["video"]

    def test_default_bitrate_in_json_when_not_specified(self):
        """Default bitrate still appears in encoding section of JSON."""
        pf = DEFAULT_PROGRAM_FORMAT
        data = json.loads(pf.to_json())
        assert data["encoding"]["video_bitrate"] == 8_000_000

    def test_from_dict_nested_with_encoding(self):
        """from_dict parses encoding.video_bitrate from nested format."""
        data = {
            "video": {"width": 1280, "height": 720, "frame_rate": "30/1"},
            "audio": {"sample_rate": 48000, "channels": 2},
            "encoding": {"video_bitrate": 3_000_000},
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.video_bitrate == 3_000_000

    def test_from_dict_nested_without_encoding_uses_default(self):
        """from_dict uses default bitrate when encoding section is absent."""
        data = {
            "video": {"width": 1280, "height": 720, "frame_rate": "30/1"},
            "audio": {"sample_rate": 48000, "channels": 2},
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.video_bitrate == 8_000_000

    def test_from_dict_flat_with_bitrate(self):
        """from_dict parses video_bitrate from flat format."""
        data = {
            "video_width": 1280,
            "video_height": 720,
            "frame_rate": "30/1",
            "audio_sample_rate": 48000,
            "audio_channels": 2,
            "video_bitrate": 4_000_000,
        }
        pf = ProgramFormat.from_dict(data)
        assert pf.video_bitrate == 4_000_000

    def test_roundtrip_json(self):
        """to_json → from_dict roundtrip preserves video_bitrate."""
        original = ProgramFormat(
            video_width=968,
            video_height=720,
            frame_rate="30000/1001",
            audio_sample_rate=48000,
            audio_channels=2,
            video_bitrate=12_000_000,
        )
        data = json.loads(original.to_json())
        restored = ProgramFormat.from_dict(data)
        assert restored.video_bitrate == original.video_bitrate
