"""PlaylistScheduleManager Contract Tests

Contract: docs/contracts/runtime/PlaylistScheduleManagerContract.md

Tests the invariants that any conforming PlaylistScheduleManager implementation
must satisfy.  Uses a minimal hard-coded stub to validate contract properties.

Test IDs map to contract test specifications:
    PSM-T001  Determinism              (INV-PSM-06)
    PSM-T002  Broadcast-day tiling     (INV-PSM-01, INV-PSM-08)
    PSM-T003  Frame-math consistency   (INV-PSM-02, INV-PSM-04)  [join-in-progress]
    PSM-T004  Window coverage          (INV-PSM-01, INV-PSM-08)
    PSM-T005  Frame math exact         (INV-PSM-02, INV-PSM-04)
    PSM-T006  Negative frame_count     (INV-PSM-02)
    PSM-T007  Immutability             (INV-PSM-05)
    PSM-T008  Naive datetime rejection (INV-PSM-03)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Sequence

import pytest

from retrovue.runtime.channel_manager import Playlist, PlaylistSegment


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FPS: int = 30
CHANNEL_ID: str = "retrovue-classic"
CHANNEL_TZ: str = "America/New_York"

# Segment pattern: 22-min program (39600 frames) + 8-min interstitial (14400 frames)
PROGRAM_FRAMES: int = 22 * 60 * FPS      # 39600
INTERSTITIAL_FRAMES: int = 8 * 60 * FPS  # 14400


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round_half_up(x: float) -> int:
    """ROUND_HALF_UP as defined in the contract."""
    return int(math.floor(x + 0.5))


def _make_segment(
    index: int,
    start_at: datetime,
    frame_count: int,
    fps: int = FPS,
    seg_type: str = "PROGRAM",
) -> PlaylistSegment:
    """Build a single well-formed PlaylistSegment."""
    duration_seconds = frame_count / fps
    return PlaylistSegment(
        segment_id=f"seg-{index:04d}",
        start_at=start_at,
        duration_seconds=duration_seconds,
        type=seg_type,
        asset_id=f"asset-{index:04d}",
        asset_path=f"/mnt/media/test/asset-{index:04d}.mp4",
        frame_count=frame_count,
    )


# ---------------------------------------------------------------------------
# Stub PlaylistScheduleManager (fixture implementation)
# ---------------------------------------------------------------------------

class StubPlaylistScheduleManager:
    """Minimal conforming implementation for contract validation.

    Produces a repeating 22-min PROGRAM + 8-min INTERSTITIAL pattern at 30fps.
    The last segment in a window may be shorter to tile exactly.
    """

    def get_playlists(
        self,
        channel_id: str,
        window_start_at: datetime,
        window_end_at: datetime,
    ) -> list[Playlist]:
        # INV-PSM-03: reject naive datetimes
        if window_start_at.tzinfo is None or window_end_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if window_start_at >= window_end_at:
            raise ValueError("window_start_at must be before window_end_at")

        segments: list[PlaylistSegment] = []
        cursor = window_start_at
        idx = 0

        while cursor < window_end_at:
            if idx % 2 == 0:
                full_frames = PROGRAM_FRAMES
                seg_type = "PROGRAM"
            else:
                full_frames = INTERSTITIAL_FRAMES
                seg_type = "INTERSTITIAL"

            # Don't overshoot the window — clamp the last segment.
            remaining_seconds = (window_end_at - cursor).total_seconds()
            remaining_frames = _round_half_up(remaining_seconds * FPS)
            fc = min(full_frames, remaining_frames)

            seg = _make_segment(idx, cursor, fc, seg_type=seg_type)
            segments.append(seg)
            cursor = cursor + timedelta(seconds=fc / FPS)
            idx += 1

        return [
            Playlist(
                channel_id=channel_id,
                channel_timezone=CHANNEL_TZ,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                generated_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                source="HARD_CODED",
                segments=tuple(segments),
            )
        ]


class StubMultiPlaylistScheduleManager:
    """Stub that returns two Playlists splitting the window at the midpoint."""

    def get_playlists(
        self,
        channel_id: str,
        window_start_at: datetime,
        window_end_at: datetime,
    ) -> list[Playlist]:
        if window_start_at.tzinfo is None or window_end_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if window_start_at >= window_end_at:
            raise ValueError("window_start_at must be before window_end_at")

        mid = window_start_at + (window_end_at - window_start_at) / 2
        single = StubPlaylistScheduleManager()
        pl1_list = single.get_playlists(channel_id, window_start_at, mid)
        pl2_list = single.get_playlists(channel_id, mid, window_end_at)
        return pl1_list + pl2_list


# ---------------------------------------------------------------------------
# Tiling validation helper (reused across tests)
# ---------------------------------------------------------------------------

def assert_playlist_tiled(playlist: Playlist, fps: int = FPS) -> None:
    """Verify INV-PSM-01 frame-based tiling for a single Playlist."""
    segs = playlist.segments
    assert len(segs) > 0, "Playlist has no segments"

    # First segment starts at window start.
    assert segs[0].start_at == playlist.window_start_at, (
        f"First segment start {segs[0].start_at} != window_start_at {playlist.window_start_at}"
    )

    # Consecutive segments abut (frame-based).
    for i in range(len(segs) - 1):
        expected_next = segs[i].start_at + timedelta(seconds=segs[i].frame_count / fps)
        assert segs[i + 1].start_at == expected_next, (
            f"Gap between segment {i} and {i+1}: "
            f"expected {expected_next}, got {segs[i + 1].start_at}"
        )

    # Last segment closes the window.
    last = segs[-1]
    computed_end = last.start_at + timedelta(seconds=last.frame_count / fps)
    assert computed_end == playlist.window_end_at, (
        f"Last segment ends at {computed_end}, window_end_at is {playlist.window_end_at}"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def psm() -> StubPlaylistScheduleManager:
    return StubPlaylistScheduleManager()


@pytest.fixture
def multi_psm() -> StubMultiPlaylistScheduleManager:
    return StubMultiPlaylistScheduleManager()


# ===========================================================================
# PSM-T001: Deterministic Output  (INV-PSM-06)
# ===========================================================================

class TestPSMT001Determinism:
    """Two calls with identical arguments MUST return identical Playlists."""

    def test_identical_calls_return_identical_playlists(self, psm):
        w_start = datetime(2026, 2, 7, 6, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 8, 6, 0, 0, tzinfo=timezone.utc)

        result1 = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        result2 = psm.get_playlists(CHANNEL_ID, w_start, w_end)

        assert len(result1) == len(result2)
        for p1, p2 in zip(result1, result2):
            assert p1.window_start_at == p2.window_start_at
            assert p1.window_end_at == p2.window_end_at
            assert len(p1.segments) == len(p2.segments)
            for s1, s2 in zip(p1.segments, p2.segments):
                assert s1.segment_id == s2.segment_id
                assert s1.start_at == s2.start_at
                assert s1.duration_seconds == s2.duration_seconds
                assert s1.frame_count == s2.frame_count
                assert s1.type == s2.type
                assert s1.asset_id == s2.asset_id
                assert s1.asset_path == s2.asset_path

    def test_determinism_across_different_windows(self, psm):
        """Determinism holds for arbitrary windows, not just aligned ones."""
        w_start = datetime(2026, 3, 15, 9, 17, 42, tzinfo=timezone.utc)
        w_end = datetime(2026, 3, 15, 11, 3, 18, tzinfo=timezone.utc)

        r1 = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        r2 = psm.get_playlists(CHANNEL_ID, w_start, w_end)

        for p1, p2 in zip(r1, r2):
            assert len(p1.segments) == len(p2.segments)
            for s1, s2 in zip(p1.segments, p2.segments):
                assert s1 == s2


# ===========================================================================
# PSM-T002: Broadcast Day Boundary Handling  (INV-PSM-01, INV-PSM-08)
# ===========================================================================

class TestPSMT002BroadcastDayBoundary:
    """Tiling holds across multi-day windows."""

    def test_48_hour_window_fully_tiled(self, psm):
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 9, 11, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        assert len(playlists) >= 1
        assert playlists[0].window_start_at == w_start
        assert playlists[-1].window_end_at == w_end

        for pl in playlists:
            assert_playlist_tiled(pl)

    def test_day_boundary_segment_exists(self, psm):
        """A segment must straddle or abut the 24-hour mark."""
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 9, 11, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        all_segs = [s for pl in playlists for s in pl.segments]

        # The 24-hour mark
        day_boundary = datetime(2026, 2, 8, 11, 0, 0, tzinfo=timezone.utc)

        # Find the segment covering the boundary or starting at it.
        covering = [
            s for s in all_segs
            if s.start_at <= day_boundary
            < s.start_at + timedelta(seconds=s.frame_count / FPS)
        ]
        at_boundary = [s for s in all_segs if s.start_at == day_boundary]

        assert len(covering) > 0 or len(at_boundary) > 0, (
            "No segment covers or starts at the day boundary"
        )


# ===========================================================================
# PSM-T003: Join-In-Progress Frame Correctness  (INV-PSM-04)
# ===========================================================================

class TestPSMT003JoinInProgress:
    """Remaining frames derived from frame_count, not duration_seconds."""

    def test_remaining_frames_from_frame_count(self):
        """Hand-construct a segment and verify remaining-frame math."""
        seg = PlaylistSegment(
            segment_id="seg-jip-001",
            start_at=datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            duration_seconds=39600 / 30,  # 1320.0
            type="PROGRAM",
            asset_id="asset-cheers-s01e01",
            asset_path="/mnt/media/cheers/s01e01.mp4",
            frame_count=39600,
        )

        # Viewer joins 600s into the segment.
        offset_seconds = 600.0
        fps = 30

        frames_consumed = _round_half_up(offset_seconds * fps)
        remaining_frames = max(0, seg.frame_count - frames_consumed)

        assert frames_consumed == 18000
        assert remaining_frames == 21600

    def test_fractional_offset_rounding(self):
        """ROUND_HALF_UP correctly handles fractional-frame offsets."""
        # 29.97fps scenario: 30000/1001
        fps = 30000 / 1001  # ~29.97002997...

        seg = PlaylistSegment(
            segment_id="seg-jip-002",
            start_at=datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            duration_seconds=39600 / fps,
            type="PROGRAM",
            asset_id="asset-test",
            asset_path="/mnt/media/test.mp4",
            frame_count=39600,
        )

        offset_seconds = 600.5  # mid-frame scenario
        frames_consumed = _round_half_up(offset_seconds * fps)
        remaining = max(0, seg.frame_count - frames_consumed)

        # frames_consumed is deterministic for this input.
        assert frames_consumed == _round_half_up(600.5 * fps)
        assert remaining == seg.frame_count - frames_consumed
        assert remaining >= 0


# ===========================================================================
# PSM-T004: Playlist Window Coverage  (INV-PSM-01, INV-PSM-08)
# ===========================================================================

class TestPSMT004WindowCoverage:
    """Segments tile the full window with frame-based abutment."""

    def test_two_hour_window(self, psm):
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        assert playlists[0].window_start_at == w_start
        assert playlists[-1].window_end_at == w_end

        for pl in playlists:
            assert_playlist_tiled(pl)

    def test_arbitrary_non_aligned_window(self, psm):
        """Tiling works for windows that don't align to pattern boundaries."""
        w_start = datetime(2026, 2, 7, 11, 7, 13, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 12, 3, 47, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        assert playlists[0].window_start_at == w_start
        assert playlists[-1].window_end_at == w_end

        for pl in playlists:
            assert_playlist_tiled(pl)

    def test_very_short_window(self, psm):
        """A window shorter than one full segment still tiles correctly."""
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 11, 5, 0, tzinfo=timezone.utc)  # 5 minutes

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        for pl in playlists:
            assert_playlist_tiled(pl)


# ===========================================================================
# PSM-T005: Frame Math Consistency  (INV-PSM-02, INV-PSM-04)
# ===========================================================================

class TestPSMT005FrameMath:
    """duration_seconds == frame_count / fps (exact) for every segment."""

    EPSILON = 1e-9

    def test_duration_equals_frame_count_over_fps(self, psm):
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        for pl in playlists:
            for seg in pl.segments:
                expected = seg.frame_count / FPS
                assert abs(seg.duration_seconds - expected) < self.EPSILON, (
                    f"Segment {seg.segment_id}: duration_seconds={seg.duration_seconds} "
                    f"!= frame_count/fps={expected}"
                )

    def test_all_frame_counts_non_negative(self, psm):
        """INV-PSM-02: every segment has frame_count >= 0."""
        w_start = datetime(2026, 2, 7, 6, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 8, 6, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        for pl in playlists:
            for seg in pl.segments:
                assert seg.frame_count >= 0, (
                    f"Segment {seg.segment_id} has frame_count={seg.frame_count}"
                )

    def test_frame_abutment_consistency(self, psm):
        """Abutment via frame_count / fps matches segment start_at chain."""
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 15, 0, 0, tzinfo=timezone.utc)

        playlists = psm.get_playlists(CHANNEL_ID, w_start, w_end)
        for pl in playlists:
            segs = pl.segments
            for i in range(len(segs) - 1):
                frame_end = segs[i].start_at + timedelta(
                    seconds=segs[i].frame_count / FPS
                )
                assert frame_end == segs[i + 1].start_at, (
                    f"Segment {i}: frame-based end {frame_end} "
                    f"!= next start {segs[i + 1].start_at}"
                )

    def test_non_integer_duration_when_frames_not_fps_multiple(self):
        """When frame_count is not a multiple of fps, duration_seconds is a float."""
        # 39601 frames at 30fps => duration_seconds = 39601/30 = 1320.0333...
        frame_count = 39601
        expected_duration = frame_count / FPS
        assert expected_duration != int(expected_duration), (
            "Test precondition: duration should not be integer"
        )

        seg = _make_segment(
            0,
            datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            frame_count,
        )
        assert abs(seg.duration_seconds - expected_duration) < 1e-9


# PSM-T006 (load_playlist / negative frame_count) removed: Phase8DecommissionContract;
# ChannelManager no longer has load_playlist().


# ===========================================================================
# PSM-T007: Immutability After Return  (INV-PSM-05)
# ===========================================================================

class TestPSMT007Immutability:
    """Frozen dataclass prevents mutation after handoff."""

    def test_playlist_fields_are_frozen(self, psm):
        playlists = psm.get_playlists(
            CHANNEL_ID,
            datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc),
        )
        pl = playlists[0]

        with pytest.raises(AttributeError):
            pl.channel_id = "hacked"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            pl.window_start_at = datetime.now(timezone.utc)  # type: ignore[misc]

    def test_segment_fields_are_frozen(self, psm):
        playlists = psm.get_playlists(
            CHANNEL_ID,
            datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc),
        )
        seg = playlists[0].segments[0]

        with pytest.raises(AttributeError):
            seg.frame_count = -999  # type: ignore[misc]

        with pytest.raises(AttributeError):
            seg.start_at = datetime.now(timezone.utc)  # type: ignore[misc]


# ===========================================================================
# PSM-T008: Naive Datetime Rejection  (INV-PSM-03)
# ===========================================================================

class TestPSMT008NaiveDatetimeRejection:
    """Naive (tzinfo-less) datetime arguments must be rejected."""

    def test_naive_window_start_rejected(self, psm):
        naive_start = datetime(2026, 2, 7, 11, 0, 0)
        aware_end = datetime(2026, 2, 7, 13, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(ValueError, match="timezone-aware"):
            psm.get_playlists(CHANNEL_ID, naive_start, aware_end)

    def test_naive_window_end_rejected(self, psm):
        aware_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        naive_end = datetime(2026, 2, 7, 13, 0, 0)

        with pytest.raises(ValueError, match="timezone-aware"):
            psm.get_playlists(CHANNEL_ID, aware_start, naive_end)

    def test_both_naive_rejected(self, psm):
        naive_start = datetime(2026, 2, 7, 11, 0, 0)
        naive_end = datetime(2026, 2, 7, 13, 0, 0)

        with pytest.raises(ValueError):
            psm.get_playlists(CHANNEL_ID, naive_start, naive_end)

    def test_inverted_window_rejected(self, psm):
        """window_start_at >= window_end_at is also an error."""
        t = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            psm.get_playlists(CHANNEL_ID, t, t)


# ===========================================================================
# Multi-Playlist Tiling  (INV-PSM-08)
# ===========================================================================

class TestMultiPlaylistTiling:
    """When multiple playlists are returned, they tile the full window."""

    def test_two_playlists_tile_window(self, multi_psm):
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 15, 0, 0, tzinfo=timezone.utc)

        playlists = multi_psm.get_playlists(CHANNEL_ID, w_start, w_end)
        assert len(playlists) == 2

        # Playlist-level tiling (INV-PSM-08).
        assert playlists[0].window_start_at == w_start
        assert playlists[-1].window_end_at == w_end
        assert playlists[0].window_end_at == playlists[1].window_start_at

        # Each playlist is internally tiled (INV-PSM-01).
        for pl in playlists:
            assert_playlist_tiled(pl)

    def test_multi_playlist_no_gap_at_boundary(self, multi_psm):
        """The last segment of playlist[0] abuts the first of playlist[1]."""
        w_start = datetime(2026, 2, 7, 11, 0, 0, tzinfo=timezone.utc)
        w_end = datetime(2026, 2, 7, 15, 0, 0, tzinfo=timezone.utc)

        playlists = multi_psm.get_playlists(CHANNEL_ID, w_start, w_end)

        last_seg_p0 = playlists[0].segments[-1]
        first_seg_p1 = playlists[1].segments[0]

        p0_end = last_seg_p0.start_at + timedelta(
            seconds=last_seg_p0.frame_count / FPS
        )
        assert p0_end == first_seg_p1.start_at, (
            f"Gap between playlists: p0 ends at {p0_end}, p1 starts at {first_seg_p1.start_at}"
        )
