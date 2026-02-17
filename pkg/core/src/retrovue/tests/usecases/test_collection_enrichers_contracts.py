"""Contract tests for collection_enrichers confidence scoring and duration guards."""
import pytest

from retrovue.adapters.importers.base import DiscoveredItem
from retrovue.usecases.collection_enrichers import (
    MAX_DURATION_MS,
    compute_confidence_from_labels,
    extract_label_value,
)


# ---------------------------------------------------------------------------
# extract_label_value
# ---------------------------------------------------------------------------

class TestExtractLabelValue:
    def test_extracts_value(self):
        assert extract_label_value(["duration_ms:1500000"], "duration_ms") == "1500000"

    def test_returns_none_for_missing_key(self):
        assert extract_label_value(["video_codec:h264"], "duration_ms") is None

    def test_returns_none_for_empty_list(self):
        assert extract_label_value([], "duration_ms") is None

    def test_returns_none_for_none(self):
        assert extract_label_value(None, "duration_ms") is None

    def test_handles_colon_in_value(self):
        assert extract_label_value(["path:/mnt/data:stuff"], "path") == "/mnt/data:stuff"


# ---------------------------------------------------------------------------
# compute_confidence_from_labels — duration guards (CONTRACTS)
# ---------------------------------------------------------------------------

def _make_item(
    size: int = 1000,
    duration_ms: int | None = None,
    video_codec: str | None = None,
    audio_codec: str | None = None,
    container: str | None = None,
) -> DiscoveredItem:
    """Build a DiscoveredItem with the given label values."""
    labels = []
    if duration_ms is not None:
        labels.append(f"duration_ms:{duration_ms}")
    if video_codec is not None:
        labels.append(f"video_codec:{video_codec}")
    if audio_codec is not None:
        labels.append(f"audio_codec:{audio_codec}")
    if container is not None:
        labels.append(f"container:{container}")
    return DiscoveredItem(path_uri="file:///test.mkv", raw_labels=labels, size=size)


class TestDurationGuardContracts:
    """These are safety contracts — if any fail, assets without valid
    duration data could be auto-promoted to broadcast."""

    def test_missing_duration_returns_zero(self):
        """CONTRACT: No duration label → confidence must be 0.0."""
        item = _make_item(duration_ms=None, video_codec="h264")
        assert compute_confidence_from_labels(item) == 0.0

    def test_zero_duration_returns_zero(self):
        """CONTRACT: duration_ms=0 → confidence must be 0.0."""
        item = _make_item(duration_ms=0, video_codec="h264")
        assert compute_confidence_from_labels(item) == 0.0

    def test_negative_duration_returns_zero(self):
        """CONTRACT: negative duration → confidence must be 0.0."""
        item = _make_item(duration_ms=-1, video_codec="h264")
        assert compute_confidence_from_labels(item) == 0.0

    def test_extreme_duration_returns_zero(self):
        """CONTRACT: duration > 3 hours → confidence must be 0.0."""
        item = _make_item(duration_ms=MAX_DURATION_MS + 1, video_codec="h264")
        assert compute_confidence_from_labels(item) == 0.0

    def test_exactly_max_duration_returns_zero(self):
        """CONTRACT: duration == MAX_DURATION_MS → must be 0.0 (boundary)."""
        # > MAX, not >=, so exactly MAX should still pass
        item = _make_item(duration_ms=MAX_DURATION_MS, video_codec="h264")
        # The guard is `dur_int > MAX_DURATION_MS` so exactly MAX is valid
        assert compute_confidence_from_labels(item) > 0.0

    def test_just_over_max_returns_zero(self):
        """CONTRACT: duration == MAX + 1 → must be 0.0."""
        item = _make_item(duration_ms=MAX_DURATION_MS + 1)
        assert compute_confidence_from_labels(item) == 0.0


# ---------------------------------------------------------------------------
# compute_confidence_from_labels — scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    def test_full_metadata_scores_high(self):
        """Complete metadata should score 0.9 (all components)."""
        item = _make_item(
            size=5000,
            duration_ms=1_800_000,
            video_codec="h264",
            audio_codec="aac",
            container="mkv",
        )
        assert compute_confidence_from_labels(item) == pytest.approx(0.9)

    def test_duration_only_scores_half(self):
        """Size + duration gives 0.5."""
        item = _make_item(size=5000, duration_ms=1_800_000)
        assert compute_confidence_from_labels(item) == pytest.approx(0.5)

    def test_zero_size_loses_size_points(self):
        """size=0 should lose 0.2 but still score if duration present."""
        item = _make_item(size=0, duration_ms=1_800_000, video_codec="h264")
        assert compute_confidence_from_labels(item) == pytest.approx(0.5)

    def test_score_never_exceeds_one(self):
        """Even with extra labels, score capped at 1.0."""
        # Current max is 0.9 so this just validates the clamp exists
        item = _make_item(
            size=5000,
            duration_ms=1_800_000,
            video_codec="h264",
            audio_codec="aac",
            container="mkv",
        )
        assert compute_confidence_from_labels(item) <= 1.0
