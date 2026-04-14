"""
Contract tests: INV-DURATION-EXTRACTION-NORMALIZATION-001

Duration extraction MUST normalize across ffprobe source variants before
declaring failure:
1) format.duration
2) max(stream.duration)
3) stream.tags.DURATION (HH:MM:SS[.fraction])

Tests use mocked ffprobe payloads only (no real files, no subprocess calls).
"""

from __future__ import annotations

import pytest

from retrovue.adapters.enrichers.ffprobe_enricher import FFprobeEnricher


class TestInvDurationExtractionNormalization001:
    """Normalization contract for ffprobe duration extraction."""

    def setup_method(self) -> None:
        self.enricher = FFprobeEnricher()

    def test_tden_001_format_duration_preferred_over_stream_disagreement(self) -> None:
        """
        If format.duration is valid, it MUST win even when stream durations disagree.
        """
        payload = {
            "format": {"duration": "74.211"},
            "streams": [
                {"codec_type": "video", "duration": "10.0"},
                {"codec_type": "audio", "duration": "80.0"},
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        assert probed.get("duration_ms") == 74211

    def test_tden_002_fallback_to_max_stream_duration_when_format_missing(self) -> None:
        """
        If format.duration is missing, duration MUST be max(stream.duration).
        """
        payload = {
            "format": {},
            "streams": [
                {"codec_type": "video", "duration": "31.5"},
                {"codec_type": "audio", "duration": "32.75"},
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        # 32.75 s -> 32750 ms
        assert probed.get("duration_ms") == 32750

    def test_tden_003_fallback_to_stream_tag_duration_hms(self) -> None:
        """
        If no numeric format/stream duration exists, tag duration MUST be parsed.
        """
        payload = {
            "format": {},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "N/A",
                    "tags": {"DURATION": "00:01:14.211"},
                }
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        assert probed.get("duration_ms") == 74211

    def test_tden_004_na_and_missing_fields_across_all_sources_is_invalid(self) -> None:
        """
        If all sources fail (missing/N/A), duration MUST remain unresolved.
        """
        payload = {
            "format": {"duration": "N/A"},
            "streams": [
                {"codec_type": "video", "duration": "N/A"},
                {"codec_type": "audio"},  # duration missing
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        assert "duration_ms" not in probed

    def test_tden_005_malformed_tag_duration_is_rejected(self) -> None:
        """
        Malformed stream.tags.DURATION must not produce a duration_ms.
        """
        payload = {
            "format": {},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "N/A",
                    "tags": {"DURATION": "not-a-time"},
                }
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        assert "duration_ms" not in probed

    def test_tden_006_zero_or_negative_duration_is_invalid(self) -> None:
        """
        Zero/negative extracted durations MUST be treated as invalid.
        """
        payloads = [
            {"format": {"duration": "0"}, "streams": []},
            {"format": {"duration": "-5"}, "streams": []},
        ]

        for payload in payloads:
            probed = self.enricher._metadata_to_probed(payload)
            assert "duration_ms" not in probed

    def test_tden_007_stream_disagreement_without_format_chooses_max(self) -> None:
        """
        Without format.duration, disagreement between streams MUST resolve to max.
        """
        payload = {
            "format": {},
            "streams": [
                {"codec_type": "video", "duration": "59.0"},
                {"codec_type": "audio", "duration": "61.2"},
                {"codec_type": "audio", "duration": "60.8"},
            ],
        }

        probed = self.enricher._metadata_to_probed(payload)
        assert probed.get("duration_ms") == 61200

