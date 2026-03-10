"""Contract tests for `retrovue schedule rebuild --tier 2`.

Tests validate rebuild behavior by mocking database operations.

Coverage:
  1. Tier-2 rebuild replaces segmented blocks in the rebuild window
  2. Tier-1 ScheduleItems remain unchanged after Tier-2 rebuild
  3. compiled_segments template blocks produce intro + movie segments
  4. --dry-run performs no database writes
  5. --live-safe prevents modification of the currently playing block
  6. Only blocks inside the rebuild window are modified
  7. expand_editorial_block receives filler_uri and filler_duration_ms
  8. Blocks with filler placeholders receive filled segments
  9. Template-derived blocks remain intro + movie + filler after rebuild
  10. No exceptions during rebuild with filler args
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch, call

import pytest

from retrovue.usecases.schedule_rebuild import (
    RebuildResult,
    _get_currently_playing_block,
    _broadcast_date_for,
    rebuild_tier2,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

BASE_DT = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
BASE_MS = int(BASE_DT.timestamp() * 1000)
HOUR_MS = 3_600_000
HALF_HOUR_MS = 1_800_000


def _block_id(asset_id: str, start_ms: int) -> str:
    raw = f"{asset_id}:{start_ms}"
    return f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _make_tier1_block(
    asset_id: str, start_ms: int, end_ms: int,
    *, compiled_segments: list | None = None,
) -> dict:
    """Minimal Tier-1 segmented block dict (as returned by schedule_items_reader).

    compiled_segments uses V2 schema (asset_id + duration_ms). This function
    converts them to playout-level ScheduledSegment dicts (asset_uri + segment_duration_ms).
    """
    segs = []
    if compiled_segments:
        for i, cs in enumerate(compiled_segments):
            seg_asset_id = cs.get("asset_id", "")
            segs.append({
                "segment_type": cs["segment_type"],
                "asset_uri": f"/assets/{seg_asset_id}.mp4" if seg_asset_id else "",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": cs["duration_ms"],
            })
    else:
        segs.append({
            "segment_type": "content",
            "asset_uri": f"/assets/{asset_id}.mp4",
            "asset_start_offset_ms": 0,
            "segment_duration_ms": end_ms - start_ms,
        })

    return {
        "block_id": _block_id(asset_id, start_ms),
        "start_utc_ms": start_ms,
        "end_utc_ms": end_ms,
        "segments": segs,
    }


def _fake_expand(sb_dict, *, filler_uri, filler_duration_ms, asset_library=None, **kwargs):
    """Stub for expand_editorial_block that returns a MagicMock block."""
    fake = MagicMock()
    fake.block_id = sb_dict["block_id"]
    fake.start_utc_ms = sb_dict["start_utc_ms"]
    fake.end_utc_ms = sb_dict["end_utc_ms"]
    fake.segments = []
    return fake


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _broadcast_date_for
# ─────────────────────────────────────────────────────────────────────────────

class TestBroadcastDate:
    # Tier: 2 | Scheduling logic invariant
    def test_after_day_start(self):
        dt = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
        assert _broadcast_date_for(dt) == date(2026, 3, 6)

    # Tier: 2 | Scheduling logic invariant
    def test_before_day_start(self):
        dt = datetime(2026, 3, 6, 3, 0, tzinfo=timezone.utc)
        assert _broadcast_date_for(dt) == date(2026, 3, 5)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tier-2 rebuild replaces segmented blocks in the rebuild window
# ─────────────────────────────────────────────────────────────────────────────

class TestTier2RebuildReplacesBlocks:

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_deletes_and_rebuilds(self, mock_load, mock_expand):
        """Rebuild deletes existing Tier-2 blocks and rebuilds from Tier-1."""
        db = MagicMock()

        # Mock delete count
        db.query.return_value.filter.return_value.delete.return_value = 2

        # Mock Tier-1 blocks — return block only for matching day
        block = _make_tier1_block("movie-001", BASE_MS, BASE_MS + HALF_HOUR_MS)
        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
        )

        assert result.deleted == 2
        assert result.rebuilt == 1
        # Verify merge was called (write path)
        assert db.merge.called


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tier-1 ScheduleItems remain unchanged
# ─────────────────────────────────────────────────────────────────────────────

class TestTier1Unchanged:

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_no_tier1_writes(self, mock_load, mock_expand):
        """Tier-2 rebuild must never write to ScheduleItem or ScheduleRevision."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0
        mock_load.return_value = []

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
        )

        # Verify no ScheduleItem or ScheduleRevision mutations
        for c in db.add.call_args_list:
            obj = c[0][0]
            assert not hasattr(obj, 'schedule_revision_id') or obj.__class__.__name__ == 'PlaylistEvent'


# ─────────────────────────────────────────────────────────────────────────────
# 3. compiled_segments template blocks produce intro + movie segments
# ─────────────────────────────────────────────────────────────────────────────

class TestCompiledSegmentsRebuild:

    # Tier: 2 | Scheduling logic invariant
    def test_compiled_segments_honored_via_hydration(self):
        """When Tier-1 items have compiled_segments, the rebuilt Tier-2 blocks
        must reflect the template segment structure (intro + content)."""
        from retrovue.runtime.schedule_items_reader import _hydrate_compiled_segments
        from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver

        resolver = StubAssetResolver()
        resolver.add("intro-001", AssetMetadata(
            type="intro", duration_sec=30, file_uri="/assets/intro-001.mp4",
        ))
        resolver.add("movie-001", AssetMetadata(
            type="movie", duration_sec=5400, file_uri="/assets/movie-001.mp4",
        ))

        compiled = [
            {
                "segment_type": "intro",
                "asset_id": "intro-001",
                "duration_ms": 30000,
            },
            {
                "segment_type": "content",
                "asset_id": "movie-001",
                "duration_ms": 5400000,
            },
        ]

        block = _hydrate_compiled_segments(
            compiled_segments=compiled,
            asset_id="movie-001",
            start_utc_ms=BASE_MS,
            slot_duration_ms=7200000,
            resolver=resolver,
        )

        seg_types = [s.segment_type for s in block.segments]
        assert seg_types[0] == "intro"
        assert seg_types[1] == "content"
        # Filler should follow
        assert "filler" in seg_types

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_rebuild_with_compiled_segments_block(self, mock_load, mock_expand):
        """Tier-1 blocks with compiled_segments are loaded and rebuilt by
        the same reader path that honors compiled_segments."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        # The Tier-1 block has compiled_segments (V2 schema)
        block = _make_tier1_block(
            "movie-001", BASE_MS, BASE_MS + 7200000,
            compiled_segments=[
                {
                    "segment_type": "intro",
                    "asset_id": "intro-001",
                    "duration_ms": 30000,
                },
                {
                    "segment_type": "content",
                    "asset_id": "movie-001",
                    "duration_ms": 5400000,
                },
            ],
        )
        # Return block only for the matching broadcast day, None for others
        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load_side_effect(db, *, channel_slug, broadcast_day):
            if broadcast_day == target_bd:
                return [block]
            return None
        mock_load.side_effect = _load_side_effect

        fake_scheduled = MagicMock()
        fake_scheduled.block_id = block["block_id"]
        fake_scheduled.start_utc_ms = block["start_utc_ms"]
        fake_scheduled.end_utc_ms = block["end_utc_ms"]
        fake_scheduled.segments = [
            MagicMock(segment_type="intro", asset_uri="/assets/intro.mp4",
                     asset_start_offset_ms=0, segment_duration_ms=30000),
            MagicMock(segment_type="content", asset_uri="/assets/movie.mp4",
                     asset_start_offset_ms=0, segment_duration_ms=5400000),
        ]
        mock_expand.return_value = fake_scheduled

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + 3 * HOUR_MS,
        )

        assert result.rebuilt == 1
        # Verify the block was written
        written = db.merge.call_args[0][0]
        seg_types = [s["segment_type"] for s in written.segments]
        assert "intro" in seg_types
        assert "content" in seg_types


# ─────────────────────────────────────────────────────────────────────────────
# 4. --dry-run performs no database writes
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRun:

    # Tier: 2 | Scheduling logic invariant
    def test_dry_run_counts_without_deleting(self):
        """dry_run=True must count deletable rows but not actually delete."""
        db = MagicMock()

        # Mock count (used in dry_run)
        db.query.return_value.filter.return_value.count.return_value = 3

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
            dry_run=True,
        )

        assert result.deleted == 3
        assert result.rebuilt == 0
        # Verify delete was NOT called
        db.query.return_value.filter.return_value.delete.assert_not_called()
        # Verify merge was NOT called
        db.merge.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 5. --live-safe prevents modification of the currently playing block
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveSafe:

    # Tier: 2 | Scheduling logic invariant
    def test_live_safe_shifts_start_past_playing_block(self):
        """When start falls inside a playing block, live-safe shifts start
        to end of that block."""
        db = MagicMock()

        playing_end = BASE_MS + HALF_HOUR_MS

        # Mock _get_currently_playing_block via the PlaylistEvent query
        playing_row = MagicMock()
        playing_row.start_utc_ms = BASE_MS - HALF_HOUR_MS
        playing_row.end_utc_ms = playing_end

        # First query call is for currently playing block (live_safe check)
        # Then delete, then load_segmented_blocks...
        # Use side_effect to control different query paths
        with patch(
            "retrovue.usecases.schedule_rebuild._get_currently_playing_block"
        ) as mock_playing:
            mock_playing.return_value = {
                "start_utc_ms": BASE_MS - HALF_HOUR_MS,
                "end_utc_ms": playing_end,
            }

            # Mock delete returns 0 (after shift, maybe nothing to delete)
            db.query.return_value.filter.return_value.delete.return_value = 0

            with patch(
                "retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision"
            ) as mock_load:
                mock_load.return_value = []

                result = rebuild_tier2(
                    db,
                    channel_slug="test-channel",
                    start_utc_ms=BASE_MS,
                    end_utc_ms=BASE_MS + 2 * HOUR_MS,
                    live_safe=True,
                )

        assert result.live_safe_skipped is True
        assert result.start_utc_ms == playing_end

    # Tier: 2 | Scheduling logic invariant
    def test_live_safe_no_shift_when_not_playing(self):
        """When no block is currently playing, live-safe is a no-op."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        with patch(
            "retrovue.usecases.schedule_rebuild._get_currently_playing_block"
        ) as mock_playing:
            mock_playing.return_value = None

            with patch(
                "retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision"
            ) as mock_load:
                mock_load.return_value = []

                result = rebuild_tier2(
                    db,
                    channel_slug="test-channel",
                    start_utc_ms=BASE_MS,
                    end_utc_ms=BASE_MS + HOUR_MS,
                    live_safe=True,
                )

        assert result.live_safe_skipped is False
        assert result.start_utc_ms == BASE_MS


# ─────────────────────────────────────────────────────────────────────────────
# 6. Only blocks that overlap the rebuild window are modified
# ─────────────────────────────────────────────────────────────────────────────

class TestWindowBoundary:

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_non_overlapping_blocks_excluded(self, mock_load, mock_expand):
        """Blocks that ended before the window or start after it are excluded."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        window_start = BASE_MS
        window_end = BASE_MS + HOUR_MS

        # Three blocks: ended-before, inside, starts-after
        block_before = _make_tier1_block("b-before", BASE_MS - HOUR_MS, BASE_MS)
        block_inside = _make_tier1_block("b-inside", BASE_MS + 100, BASE_MS + HALF_HOUR_MS)
        block_after = _make_tier1_block("b-after", BASE_MS + 2 * HOUR_MS, BASE_MS + 3 * HOUR_MS)

        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            if broadcast_day == target_bd:
                return [block_before, block_inside, block_after]
            return None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=window_start,
            end_utc_ms=window_end,
        )

        assert result.rebuilt == 1
        assert mock_expand.call_count == 1

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_block_overlapping_window_start_is_rebuilt(self, mock_load, mock_expand):
        """A block that started before the window but is still active (end > window_start)
        MUST be rebuilt. This is the --from now case: the currently-playing block
        started before 'now' but is still playing."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        window_start = BASE_MS
        window_end = BASE_MS + 3 * HOUR_MS

        # Started 1h before window, ends 1h after window start — overlaps
        overlapping = _make_tier1_block("playing", BASE_MS - HOUR_MS, BASE_MS + HOUR_MS)
        # Starts inside window
        future = _make_tier1_block("future", BASE_MS + HOUR_MS, BASE_MS + 2 * HOUR_MS)

        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            if broadcast_day == target_bd:
                return [overlapping, future]
            return None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=window_start,
            end_utc_ms=window_end,
        )

        rebuilt_ids = [c[0][0]["block_id"] for c in mock_expand.call_args_list]
        assert overlapping["block_id"] in rebuilt_ids, (
            f"Block started before window but still active MUST be rebuilt. "
            f"Rebuilt: {rebuilt_ids}"
        )
        assert result.rebuilt == 2


# ─────────────────────────────────────────────────────────────────────────────
# 7. expand_editorial_block receives filler_uri and filler_duration_ms
# ─────────────────────────────────────────────────────────────────────────────

FILLER_URI = "/media/test-filler.mp4"
FILLER_DURATION_MS = 60_000


class TestFillerArgsPassedToExpandEditorialBlock:

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_filler_args_forwarded(self, mock_load, mock_expand):
        """rebuild_tier2 must pass filler_uri and filler_duration_ms to
        expand_editorial_block."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        block = _make_tier1_block("movie-001", BASE_MS, BASE_MS + HALF_HOUR_MS)
        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        mock_expand.assert_called_once_with(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=ANY,
            policy=ANY,
            break_config=ANY,
        )

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_default_filler_args(self, mock_load, mock_expand):
        """When no filler args are provided, defaults match PlaylistBuilderDaemon."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 0

        block = _make_tier1_block("movie-001", BASE_MS, BASE_MS + HALF_HOUR_MS)
        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
        )

        mock_expand.assert_called_once_with(
            block,
            filler_uri="/opt/retrovue/assets/filler.mp4",
            filler_duration_ms=3_650_000,
            asset_library=ANY,
            policy=ANY,
            break_config=ANY,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Blocks with filler placeholders receive filled segments
# ─────────────────────────────────────────────────────────────────────────────

class TestFillerPlaceholdersFilled:

    # Tier: 2 | Scheduling logic invariant
    def test_fill_ad_blocks_replaces_empty_filler(self):
        """fill_ad_blocks replaces empty filler placeholders with the filler URI."""
        from retrovue.runtime.traffic_manager import fill_ad_blocks
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HALF_HOUR_MS,
            segments=(
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/assets/movie.mp4",
                    asset_start_offset_ms=0,
                    segment_duration_ms=HALF_HOUR_MS - 60_000,
                ),
                ScheduledSegment(
                    segment_type="filler",
                    asset_uri="",
                    asset_start_offset_ms=0,
                    segment_duration_ms=60_000,
                ),
            ),
        )

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        filler_segs = [s for s in filled.segments if s.segment_type == "filler"]
        assert len(filler_segs) == 1
        assert filler_segs[0].asset_uri == FILLER_URI
        assert filler_segs[0].segment_duration_ms == 60_000


# ─────────────────────────────────────────────────────────────────────────────
# 9. Template-derived blocks remain intro + movie + filler after rebuild
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateBlocksWithFiller:

    # Tier: 2 | Scheduling logic invariant
    def test_template_block_intro_content_filler(self):
        """Template-derived blocks with compiled_segments produce
        intro + content + filler segments after fill_ad_blocks."""
        from retrovue.runtime.traffic_manager import fill_ad_blocks
        from retrovue.runtime.schedule_items_reader import _hydrate_compiled_segments
        from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver

        resolver = StubAssetResolver()
        resolver.add("intro-001", AssetMetadata(
            type="intro", duration_sec=30, file_uri="/assets/intro.mp4",
        ))
        resolver.add("movie-001", AssetMetadata(
            type="movie", duration_sec=5400, file_uri="/assets/movie.mp4",
        ))

        compiled = [
            {
                "segment_type": "intro",
                "asset_id": "intro-001",
                "duration_ms": 30_000,
            },
            {
                "segment_type": "content",
                "asset_id": "movie-001",
                "duration_ms": 5_400_000,
            },
        ]

        block = _hydrate_compiled_segments(
            compiled_segments=compiled,
            asset_id="movie-001",
            start_utc_ms=BASE_MS,
            slot_duration_ms=7_200_000,
            resolver=resolver,
        )

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS * 30,  # must exceed filler slot
        )

        seg_types = [s.segment_type for s in filled.segments]
        assert seg_types[0] == "intro"
        assert seg_types[1] == "content"
        assert "filler" in seg_types
        # Filler segments should have the filler URI
        for seg in filled.segments:
            if seg.segment_type == "filler":
                assert seg.asset_uri == FILLER_URI


# ─────────────────────────────────────────────────────────────────────────────
# 10. No exceptions during rebuild with filler args
# ─────────────────────────────────────────────────────────────────────────────

class TestNoExceptionsDuringRebuild:

    # Tier: 2 | Scheduling logic invariant
    @patch("retrovue.usecases.schedule_rebuild.expand_editorial_block")
    @patch("retrovue.usecases.schedule_rebuild.load_segmented_blocks_from_active_revision")
    def test_rebuild_completes_without_errors(self, mock_load, mock_expand):
        """Tier-2 rebuild with filler args completes with zero errors."""
        db = MagicMock()
        db.query.return_value.filter.return_value.delete.return_value = 1

        block = _make_tier1_block("movie-001", BASE_MS, BASE_MS + HALF_HOUR_MS)
        from datetime import date as date_type
        target_bd = date_type(2026, 3, 6)
        def _load(db, *, channel_slug, broadcast_day):
            return [block] if broadcast_day == target_bd else None
        mock_load.side_effect = _load

        mock_expand.side_effect = _fake_expand

        result = rebuild_tier2(
            db,
            channel_slug="test-channel",
            start_utc_ms=BASE_MS,
            end_utc_ms=BASE_MS + HOUR_MS,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        assert result.errors == []
        assert result.rebuilt == 1
