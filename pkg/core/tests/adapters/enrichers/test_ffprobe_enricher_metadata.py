from __future__ import annotations

from pathlib import Path
from typing import Any

from retrovue.adapters.enrichers.ffprobe_enricher import FFprobeEnricher
from retrovue.adapters.importers.base import DiscoveredItem


def test_ffprobe_enricher_preserves_editorial_and_adds_probed(tmp_path: Path, monkeypatch: Any) -> None:
    # Create a temporary media file to satisfy existence checks
    media_file = tmp_path / "video.mkv"
    media_file.write_bytes(b"\x00\x00")

    item = DiscoveredItem(
        path_uri=str(media_file),
        provider_key="test-key",
        editorial={"title": "Akira"},
    )

    # Mock _run_ffprobe to return controlled JSON
    def _fake_run_ffprobe(self: FFprobeEnricher, file_path: Path) -> dict[str, Any]:
        return {
            "format": {"duration": "120.0", "bit_rate": "800000", "format_name": "matroska"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "24000/1001",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", _fake_run_ffprobe, raising=True)

    enricher = FFprobeEnricher()

    enriched = enricher.enrich(item)

    # Editorial preserved
    assert enriched.editorial is not None
    assert enriched.editorial.get("title") == "Akira"

    # Probed populated
    assert enriched.probed is not None
    assert enriched.probed.get("duration_ms") == 120000
    assert (enriched.probed.get("video") or {}).get("codec") == "h264"

    # Labels present
    assert isinstance(enriched.raw_labels, list)
    assert len(enriched.raw_labels) > 0




def test_ffprobe_enricher_extracts_chapters(tmp_path: Path, monkeypatch: Any) -> None:
    """Test that FFprobe enricher extracts chapter timestamps into probed data."""
    # Create a temporary media file
    media_file = tmp_path / "video_with_chapters.mkv"
    media_file.write_bytes(b"\x00\x00")

    item = DiscoveredItem(
        path_uri=str(media_file),
        provider_key="test-key",
        editorial={"title": "Movie with Chapters"},
    )

    # Mock _run_ffprobe to return JSON with chapters
    def _fake_run_ffprobe_with_chapters(self: FFprobeEnricher, file_path: Path) -> dict[str, Any]:
        return {
            "format": {
                "duration": "7200.0",
                "bit_rate": "1200000",
                "format_name": "matroska"
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
            ],
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "180.5",
                    "tags": {"title": "Opening"}
                },
                {
                    "start_time": "180.5",
                    "end_time": "6900.0",
                    "tags": {"title": "Main Feature"}
                },
                {
                    "start_time": "6900.0",
                    "end_time": "7200.0",
                    "tags": {"title": "End Credits"}
                },
            ],
        }

    monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", _fake_run_ffprobe_with_chapters, raising=True)

    enricher = FFprobeEnricher()
    enriched = enricher.enrich(item)

    # Verify probed data contains chapters
    assert enriched.probed is not None
    assert "chapters" in enriched.probed
    
    chapters = enriched.probed["chapters"]
    assert len(chapters) == 3
    
    # Verify first chapter
    assert chapters[0]["start_ms"] == 0
    assert chapters[0]["end_ms"] == 180500
    assert chapters[0]["title"] == "Opening"
    
    # Verify second chapter
    assert chapters[1]["start_ms"] == 180500
    assert chapters[1]["end_ms"] == 6900000
    assert chapters[1]["title"] == "Main Feature"
    
    # Verify third chapter
    assert chapters[2]["start_ms"] == 6900000
    assert chapters[2]["end_ms"] == 7200000
    assert chapters[2]["title"] == "End Credits"
    
    # Verify labels still contain chapter count
    assert "chapters:3" in enriched.raw_labels


def test_ffprobe_enricher_handles_missing_chapter_titles(tmp_path: Path, monkeypatch: Any) -> None:
    """Test that FFprobe enricher handles chapters without title tags."""
    # Create a temporary media file
    media_file = tmp_path / "video_untitled_chapters.mkv"
    media_file.write_bytes(b"\x00\x00")

    item = DiscoveredItem(
        path_uri=str(media_file),
        provider_key="test-key",
    )

    # Mock _run_ffprobe to return JSON with chapters missing title tags
    def _fake_run_ffprobe_no_titles(self: FFprobeEnricher, file_path: Path) -> dict[str, Any]:
        return {
            "format": {"duration": "300.0", "format_name": "mp4"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "chapters": [
                {
                    "start_time": "0.0",
                    "end_time": "150.0",
                    "tags": {}  # No title tag
                },
                {
                    "start_time": "150.0",
                    "end_time": "300.0",
                    # No tags at all
                },
            ],
        }

    monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", _fake_run_ffprobe_no_titles, raising=True)

    enricher = FFprobeEnricher()
    enriched = enricher.enrich(item)

    # Verify chapters are still extracted
    assert enriched.probed is not None
    assert "chapters" in enriched.probed
    
    chapters = enriched.probed["chapters"]
    assert len(chapters) == 2
    
    # Verify empty titles
    assert chapters[0]["title"] == ""
    assert chapters[1]["title"] == ""
    
    # Verify timestamps are still correct
    assert chapters[0]["start_ms"] == 0
    assert chapters[0]["end_ms"] == 150000
    assert chapters[1]["start_ms"] == 150000
    assert chapters[1]["end_ms"] == 300000


def test_ffprobe_enricher_no_chapters(tmp_path: Path, monkeypatch: Any) -> None:
    """Test that FFprobe enricher works correctly when media has no chapters."""
    # Create a temporary media file
    media_file = tmp_path / "video_no_chapters.mkv"
    media_file.write_bytes(b"\x00\x00")

    item = DiscoveredItem(
        path_uri=str(media_file),
        provider_key="test-key",
    )

    # Mock _run_ffprobe to return JSON without chapters
    def _fake_run_ffprobe_no_chapters(self: FFprobeEnricher, file_path: Path) -> dict[str, Any]:
        return {
            "format": {"duration": "600.0", "format_name": "matroska"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "chapters": []  # Empty chapters list
        }

    monkeypatch.setattr(FFprobeEnricher, "_run_ffprobe", _fake_run_ffprobe_no_chapters, raising=True)

    enricher = FFprobeEnricher()
    enriched = enricher.enrich(item)

    # Verify probed data exists but has no chapters key
    assert enriched.probed is not None
    assert "chapters" not in enriched.probed
    
    # Verify no chapter labels
    assert not any(label.startswith("chapters:") for label in (enriched.raw_labels or []))
