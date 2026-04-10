"""
Contract tests for INV-CHAPTER-MARKER-SHAPE-001.

Chapter markers extracted by FFprobeEnricher MUST be stored at
probed["chapter_markers"] with shape [{time_ms: int, title: str}, ...].
When no chapters exist in source media, chapter_markers MUST be absent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from retrovue.adapters.enrichers.ffprobe_enricher import FFprobeEnricher
from retrovue.adapters.importers.base import DiscoveredItem


def _make_item(tmp_path: Path) -> DiscoveredItem:
    media_file = tmp_path / "video.mkv"
    media_file.write_bytes(b"\x00\x00")
    return DiscoveredItem(path_uri=str(media_file), provider_key="test")


def _ffprobe_with_chapters(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": {"duration": "7200.0", "bit_rate": "1200000", "format_name": "matroska"},
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        "chapters": chapters,
    }


class TestChapterMarkerShape:
    """INV-CHAPTER-MARKER-SHAPE-001: chapter markers use canonical probed shape."""

    def test_chapter_markers_key_name(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Chapters MUST be stored at probed['chapter_markers'], not probed['chapters']."""
        ffprobe_out = _ffprobe_with_chapters([
            {"start_time": "0.0", "end_time": "420.0", "tags": {"title": "Introduction"}},
            {"start_time": "420.0", "end_time": "7200.0", "tags": {"title": "Chapter 1"}},
        ])
        monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", lambda self, fp: ffprobe_out)

        enriched = FFprobeEnricher().enrich(_make_item(tmp_path))

        assert "chapter_markers" in enriched.probed, "Key must be 'chapter_markers'"
        assert "chapters" not in enriched.probed, "Legacy key 'chapters' must not be present"

    def test_chapter_marker_entry_shape(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Each entry MUST have exactly {time_ms: int, title: str}."""
        ffprobe_out = _ffprobe_with_chapters([
            {"start_time": "0.0", "end_time": "180.5", "tags": {"title": "Opening"}},
            {"start_time": "180.5", "end_time": "6900.0", "tags": {"title": "Main Feature"}},
            {"start_time": "6900.0", "end_time": "7200.0", "tags": {"title": "End Credits"}},
        ])
        monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", lambda self, fp: ffprobe_out)

        enriched = FFprobeEnricher().enrich(_make_item(tmp_path))
        markers = enriched.probed["chapter_markers"]

        assert len(markers) == 3
        for m in markers:
            assert set(m.keys()) == {"time_ms", "title"}, f"Unexpected keys: {m.keys()}"
            assert isinstance(m["time_ms"], int)
            assert isinstance(m["title"], str)

    def test_chapter_marker_time_ms_values(self, tmp_path: Path, monkeypatch: Any) -> None:
        """time_ms MUST equal start_time converted to milliseconds."""
        ffprobe_out = _ffprobe_with_chapters([
            {"start_time": "0.0", "end_time": "420.0", "tags": {"title": "Intro"}},
            {"start_time": "420.0", "end_time": "7200.0", "tags": {"title": "Ch1"}},
        ])
        monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", lambda self, fp: ffprobe_out)

        enriched = FFprobeEnricher().enrich(_make_item(tmp_path))
        markers = enriched.probed["chapter_markers"]

        assert markers[0]["time_ms"] == 0
        assert markers[0]["title"] == "Intro"
        assert markers[1]["time_ms"] == 420000
        assert markers[1]["title"] == "Ch1"

    def test_no_chapters_means_absent_key(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When source has no chapters, chapter_markers MUST be absent (not empty list)."""
        ffprobe_out = _ffprobe_with_chapters([])
        monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", lambda self, fp: ffprobe_out)

        enriched = FFprobeEnricher().enrich(_make_item(tmp_path))

        assert "chapter_markers" not in enriched.probed
        assert "chapters" not in enriched.probed

    def test_missing_title_defaults_to_empty_string(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Chapters without title tags MUST have title=''."""
        ffprobe_out = _ffprobe_with_chapters([
            {"start_time": "0.0", "end_time": "150.0", "tags": {}},
            {"start_time": "150.0", "end_time": "300.0"},
        ])
        monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", lambda self, fp: ffprobe_out)

        enriched = FFprobeEnricher().enrich(_make_item(tmp_path))
        markers = enriched.probed["chapter_markers"]

        assert len(markers) == 2
        assert markers[0]["title"] == ""
        assert markers[1]["title"] == ""
        assert set(markers[0].keys()) == {"time_ms", "title"}
