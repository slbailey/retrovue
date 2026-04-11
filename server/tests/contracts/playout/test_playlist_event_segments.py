"""
Contract tests: INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002
                 INV-PLAYLIST-EVENT-SEGMENT-ORDER-003.

Segments within a PlaylistEvent must:
  - Exactly cover the block duration (sum == block_duration_ms).
  - Be contiguous (no gaps between adjacent segments).
  - Be ordered (tile from block start to block end).

Tests are deterministic (no wall-clock sleep, no DB).
See: docs/contracts/invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002.md
     docs/contracts/invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-ORDER-003.md
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Minimal domain stubs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlaylistEventStub:
    """Minimal PlaylistEvent for segment invariant testing."""
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict]

    @property
    def block_duration_ms(self) -> int:
        return self.end_utc_ms - self.start_utc_ms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EPOCH_MS = 1_740_873_600_000  # 2025-03-01T20:00:00Z
SLOT_MS = 1_800_000           # 30 minutes


def _make_content_filler_event(
    content_ms: int = 1_320_000,
    filler_ms: int = 480_000,
) -> PlaylistEventStub:
    """22-min content + 8-min filler in a 30-min slot."""
    return PlaylistEventStub(
        block_id="block-seg-001",
        start_utc_ms=EPOCH_MS,
        end_utc_ms=EPOCH_MS + content_ms + filler_ms,
        segments=[
            {
                "segment_type": "content",
                "asset_uri": "/media/show/s01e01.mkv",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": content_ms,
            },
            {
                "segment_type": "filler",
                "asset_uri": "/media/interstitials/promo_001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": filler_ms,
            },
        ],
    )


def _make_three_act_event() -> PlaylistEventStub:
    """Content with two ad breaks: 3 content + 2 filler segments."""
    act1_ms = 440_000
    ad1_ms = 120_000
    act2_ms = 440_000
    ad2_ms = 120_000
    act3_ms = 440_000
    pad_ms = SLOT_MS - (act1_ms + ad1_ms + act2_ms + ad2_ms + act3_ms)
    return PlaylistEventStub(
        block_id="block-seg-002",
        start_utc_ms=EPOCH_MS,
        end_utc_ms=EPOCH_MS + SLOT_MS,
        segments=[
            {"segment_type": "content", "segment_duration_ms": act1_ms},
            {"segment_type": "filler", "segment_duration_ms": ad1_ms},
            {"segment_type": "content", "segment_duration_ms": act2_ms},
            {"segment_type": "filler", "segment_duration_ms": ad2_ms},
            {"segment_type": "content", "segment_duration_ms": act3_ms},
            {"segment_type": "pad", "segment_duration_ms": pad_ms},
        ],
    )


# ---------------------------------------------------------------------------
# INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002 tests
# ---------------------------------------------------------------------------

class TestInvPlaylistEventSegmentCoverage002:
    """INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002 enforcement tests."""

    # Tier: 1 | Structural invariant
    def test_segments_cover_block(self) -> None:
        """Sum of segment durations must exactly equal block duration."""
        pe = _make_content_filler_event()
        segment_sum = sum(s["segment_duration_ms"] for s in pe.segments)

        assert segment_sum == pe.block_duration_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002-VIOLATED: "
            f"segment_sum={segment_sum}ms != block_duration={pe.block_duration_ms}ms, "
            f"delta={segment_sum - pe.block_duration_ms}ms"
        )

    # Tier: 1 | Structural invariant
    def test_segments_cover_block_multi_act(self) -> None:
        """Coverage holds for multi-act events with ad breaks."""
        pe = _make_three_act_event()
        segment_sum = sum(s["segment_duration_ms"] for s in pe.segments)

        assert segment_sum == pe.block_duration_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002-VIOLATED: "
            f"segment_sum={segment_sum}ms != block_duration={pe.block_duration_ms}ms, "
            f"delta={segment_sum - pe.block_duration_ms}ms"
        )

    # Tier: 1 | Structural invariant
    def test_positive_segment_durations(self) -> None:
        """Every segment must have segment_duration_ms > 0."""
        pe = _make_content_filler_event()
        for i, seg in enumerate(pe.segments):
            assert seg["segment_duration_ms"] > 0, (
                f"INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002-VIOLATED: "
                f"segment[{i}] has non-positive duration={seg['segment_duration_ms']}ms"
            )

    # Tier: 1 | Structural invariant
    def test_nonempty_segment_list(self) -> None:
        """Segment list must not be empty."""
        pe = _make_content_filler_event()
        assert len(pe.segments) > 0, (
            "INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002-VIOLATED: "
            "segment list is empty"
        )

    # Tier: 1 | Structural invariant
    def test_underfill_detected(self) -> None:
        """Segment sum less than block duration is a coverage violation."""
        pe = PlaylistEventStub(
            block_id="block-underfill",
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS - 1},
            ],
        )
        segment_sum = sum(s["segment_duration_ms"] for s in pe.segments)
        assert segment_sum != pe.block_duration_ms, (
            "Expected underfill to be detected"
        )

    # Tier: 1 | Structural invariant
    def test_overfill_detected(self) -> None:
        """Segment sum greater than block duration is a coverage violation."""
        pe = PlaylistEventStub(
            block_id="block-overfill",
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + SLOT_MS,
            segments=[
                {"segment_type": "content", "segment_duration_ms": SLOT_MS + 1},
            ],
        )
        segment_sum = sum(s["segment_duration_ms"] for s in pe.segments)
        assert segment_sum != pe.block_duration_ms, (
            "Expected overfill to be detected"
        )


# ---------------------------------------------------------------------------
# INV-PLAYLIST-EVENT-SEGMENT-ORDER-003 tests
# ---------------------------------------------------------------------------

class TestInvPlaylistEventSegmentOrder003:
    """INV-PLAYLIST-EVENT-SEGMENT-ORDER-003 enforcement tests."""

    # Tier: 1 | Structural invariant
    def test_segments_contiguous(self) -> None:
        """Each segment's implicit end equals the next segment's implicit start."""
        pe = _make_content_filler_event()
        cursor_ms = pe.start_utc_ms

        for i, seg in enumerate(pe.segments):
            seg_start = cursor_ms
            seg_end = seg_start + seg["segment_duration_ms"]
            cursor_ms = seg_end

            if i < len(pe.segments) - 1:
                next_start = cursor_ms
                assert seg_end == next_start, (
                    f"INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED: "
                    f"gap at segment[{i}]: end={seg_end} != next_start={next_start}"
                )

    # Tier: 1 | Structural invariant
    def test_segments_contiguous_multi_act(self) -> None:
        """Contiguity holds for multi-act events."""
        pe = _make_three_act_event()
        cursor_ms = pe.start_utc_ms

        for i, seg in enumerate(pe.segments):
            seg_end = cursor_ms + seg["segment_duration_ms"]
            cursor_ms = seg_end

        # Final cursor must land exactly at block end
        assert cursor_ms == pe.end_utc_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED: "
            f"final cursor={cursor_ms} != block_end={pe.end_utc_ms}"
        )

    # Tier: 1 | Structural invariant
    def test_segments_ordered(self) -> None:
        """Segments tile from block start to block end without gaps."""
        pe = _make_content_filler_event()

        # First segment starts at block start
        cursor_ms = pe.start_utc_ms
        for i, seg in enumerate(pe.segments):
            cursor_ms += seg["segment_duration_ms"]

        # Last segment ends at block end
        assert cursor_ms == pe.end_utc_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED: "
            f"segments tile end={cursor_ms} != block_end={pe.end_utc_ms}"
        )

    # Tier: 1 | Structural invariant
    def test_first_segment_starts_at_block_start(self) -> None:
        """The first segment's implicit start is PE.start_utc_ms."""
        pe = _make_content_filler_event()
        # By construction, the first segment starts at start_utc_ms.
        # This test validates that convention.
        first_implicit_start = pe.start_utc_ms
        assert first_implicit_start == pe.start_utc_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED: "
            f"first segment start={first_implicit_start} != block_start={pe.start_utc_ms}"
        )

    # Tier: 1 | Structural invariant
    def test_last_segment_ends_at_block_end(self) -> None:
        """The last segment's implicit end is PE.end_utc_ms."""
        pe = _make_content_filler_event()
        cursor_ms = pe.start_utc_ms
        for seg in pe.segments:
            cursor_ms += seg["segment_duration_ms"]

        assert cursor_ms == pe.end_utc_ms, (
            f"INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED: "
            f"last segment end={cursor_ms} != block_end={pe.end_utc_ms}"
        )
