"""Regression tests: INV-PLAYLOG-COVERAGE-HOLE-001 — backfill current block when Tier-2 has a hole.

When the daemon first extends after wall clock has passed a block's end, that block
is skipped (block_end <= cursor_ms) and never written. A viewer joining during that
block then gets a Tier-2 miss and unfilled content. This contract ensures we always
backfill the block containing now_ms before forward fill, so the current block is
never missing from Tier-2.
"""

import pytest
from unittest.mock import patch, MagicMock


def _make_daemon():
    from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
    return PlaylogHorizonDaemon(
        channel_id="test-ch",
        min_hours=2,
        programming_day_start_hour=6,
        channel_tz="UTC",
    )


def _fake_block_dict(block_id: str, start_ms: int, end_ms: int, segments_count: int = 3):
    """Minimal Tier-1 segmented block dict for _deserialize_scheduled_block."""
    seg_dur = (end_ms - start_ms) // segments_count if segments_count else 0
    return {
        "block_id": block_id,
        "start_utc_ms": start_ms,
        "end_utc_ms": end_ms,
        "segments": [
            {
                "segment_type": "content" if i == 0 else "filler",
                "asset_uri": "/path/to/asset.mp4" if i == 0 else "",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": seg_dur,
                "transition_in": "TRANSITION_NONE",
                "transition_in_duration_ms": 0,
                "transition_out": "TRANSITION_NONE",
                "transition_out_duration_ms": 0,
            }
            for i in range(segments_count)
        ],
    }


class TestEnsureTier2CoversNowBackfill:
    """_ensure_tier2_covers_now backfills the current block when Tier-2 has no row covering now_ms."""

    def test_backfill_current_block_when_tier2_empty(self):
        """Daemon starts late with empty Tier-2; now is inside a block (now > block.start).
        Ensure the current block is written.
        """
        daemon = _make_daemon()
        now_ms = 100_000
        block_start = 90_000
        block_end = 120_000
        block_id = "blk-current"
        block = _fake_block_dict(block_id, block_start, block_end)

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=block),
            patch.object(daemon, "_write_to_txlog") as mock_write,
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 1
        mock_write.assert_called_once()
        call_args = mock_write.call_args
        written_block = call_args[0][0]
        assert written_block.block_id == block_id
        assert written_block.start_utc_ms == block_start
        assert written_block.end_utc_ms == block_end

    def test_no_backfill_when_tier2_already_covers_now(self):
        """If Tier-2 already has a row covering now_ms, do nothing."""
        daemon = _make_daemon()
        now_ms = 100_000

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=True),
            patch.object(daemon, "_write_to_txlog") as mock_write,
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 0
        mock_write.assert_not_called()

    def test_backfill_fills_hole_when_future_blocks_exist(self):
        """A hole exists for the current block but future blocks are in Tier-2.
        Ensure the hole (current block) is filled.
        """
        daemon = _make_daemon()
        now_ms = 100_000
        block = _fake_block_dict("blk-hole", 90_000, 120_000)

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=block),
            patch.object(daemon, "_write_to_txlog") as mock_write,
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 1
        mock_write.assert_called_once()
        assert mock_write.call_args[0][0].block_id == "blk-hole"

    def test_no_backfill_when_now_ms_ge_block_end(self):
        """Do not backfill blocks where now_ms >= block_end (wholly in the past)."""
        daemon = _make_daemon()
        now_ms = 120_000
        # Block that ends exactly at now_ms (so now_ms >= block_end)
        block = _fake_block_dict("blk-past", 90_000, 120_000)

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=block),
            patch.object(daemon, "_write_to_txlog") as mock_write,
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 0
        mock_write.assert_not_called()

    def test_no_backfill_when_now_strictly_past_block_end(self):
        """Do not backfill when now is strictly after block end."""
        daemon = _make_daemon()
        now_ms = 130_000
        block = _fake_block_dict("blk-past", 90_000, 120_000)

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=block),
            patch.object(daemon, "_write_to_txlog") as mock_write,
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 0
        mock_write.assert_not_called()

    def test_no_backfill_when_no_tier1_block_containing_now(self):
        """If Tier-1 has no block containing now_ms (e.g. gap in schedule), do not write."""
        daemon = _make_daemon()
        now_ms = 100_000

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=None),
            patch.object(daemon, "_write_to_txlog") as mock_write,
        ):
            n = daemon._ensure_tier2_covers_now(now_ms)

        assert n == 0
        mock_write.assert_not_called()

    def test_inv_playlog_coverage_hole_001_logged_on_backfill(self, caplog):
        """Backfill logs INV-PLAYLOG-COVERAGE-HOLE-001 when filling the hole."""
        import logging
        caplog.set_level(logging.WARNING)

        daemon = _make_daemon()
        now_ms = 100_000
        block = _fake_block_dict("blk-backfill", 90_000, 120_000)

        with (
            patch.object(daemon, "_tier2_row_covers_now", return_value=False),
            patch.object(daemon, "_get_tier1_block_containing", return_value=block),
            patch.object(daemon, "_write_to_txlog"),
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
        ):
            daemon._ensure_tier2_covers_now(now_ms)

        assert "INV-PLAYLOG-COVERAGE-HOLE-001" in caplog.text
        assert "now_ms=100000" in caplog.text
        assert "block_id=blk-backfill" in caplog.text
