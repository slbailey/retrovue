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


