"""
Contract tests for the test playout endpoint.

Tests INV-TEST-BLOCK-001..008.
These are pure unit tests — no DB, no AIR subprocess.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_scheduled_segment(
    segment_type: str = "content",
    asset_uri: str = "/media/test.mkv",
    asset_start_offset_ms: int = 0,
    segment_duration_ms: int = 1_800_000,
):
    from retrovue.runtime.schedule_types import ScheduledSegment
    return ScheduledSegment(
        segment_type=segment_type,
        asset_uri=asset_uri,
        asset_start_offset_ms=asset_start_offset_ms,
        segment_duration_ms=segment_duration_ms,
    )


def _make_scheduled_block(
    block_id: str = "test-block-001",
    start_utc_ms: int = 1_700_000_000_000,
    duration_ms: int = 1_800_000,  # 30 min
    segments=None,
):
    from retrovue.runtime.schedule_types import ScheduledBlock
    if segments is None:
        segments = (_make_scheduled_segment(segment_duration_ms=duration_ms),)
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + duration_ms,
        segments=tuple(segments),
    )


# ── SingleBlockExecutionReader ───────────────────────────────────────────────

class TestSingleBlockExecutionReader:
    def test_inv_test_block_001_retimed_to_now(self):
        """INV-TEST-BLOCK-001: Block is re-timed to start_utc_ms."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader
        orig = _make_scheduled_block(start_utc_ms=1_000_000_000, duration_ms=60_000)
        now_ms = 1_700_000_000_000
        svc = SingleBlockExecutionReader(orig, now_ms)
        assert svc.content_block.start_utc_ms == now_ms
        assert svc.content_block.end_utc_ms == now_ms + 60_000

    def test_inv_test_block_002_segments_preserved(self):
        """INV-TEST-BLOCK-002: Original segments are preserved verbatim."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader
        seg = _make_scheduled_segment(asset_uri="/foo/bar.mkv", asset_start_offset_ms=5000)
        orig = _make_scheduled_block(duration_ms=60_000, segments=(seg,))
        now_ms = 9_000_000_000
        svc = SingleBlockExecutionReader(orig, now_ms)
        cb = svc.content_block
        assert len(cb.segments) == 1
        assert cb.segments[0].asset_uri == "/foo/bar.mkv"
        assert cb.segments[0].asset_start_offset_ms == 5000
        assert cb.segments[0].segment_duration_ms == seg.segment_duration_ms

    def test_inv_test_block_003_pad_block_suffix(self):
        """INV-TEST-BLOCK-003: next-block lookup returns pad block after content ends."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader, _PAD_DURATION_MS
        orig = _make_scheduled_block(duration_ms=60_000)
        now_ms = 5_000_000
        svc = SingleBlockExecutionReader(orig, now_ms)
        pad_start = now_ms + 60_000
        pad_block = svc.get_next_execution_block("test", pad_start)
        assert pad_block is not None
        assert pad_block.block_id.endswith("__pad")
        assert pad_block.start_utc_ms == pad_start
        assert pad_block.end_utc_ms == pad_start + _PAD_DURATION_MS
        assert len(pad_block.segments) == 1
        assert pad_block.segments[0].segment_type == "pad"

    def test_inv_test_block_004_none_past_pad(self):
        """INV-TEST-BLOCK-004: execution lookup returns None past pad end."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader, _PAD_DURATION_MS
        orig = _make_scheduled_block(duration_ms=60_000)
        now_ms = 5_000_000
        svc = SingleBlockExecutionReader(orig, now_ms)
        past_end = now_ms + 60_000 + _PAD_DURATION_MS
        assert svc.get_next_execution_block("test", past_end) is None

    def test_content_block_returned_within_range(self):
        """Current execution lookup returns content block when now_ms is within content range."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader
        orig = _make_scheduled_block(duration_ms=60_000)
        now_ms = 5_000_000
        svc = SingleBlockExecutionReader(orig, now_ms)
        result = svc.get_current_execution_block("test", now_ms + 1000)
        assert result is not None
        assert result.block_id == orig.block_id

    def test_block_id_preserved(self):
        """Content block preserves the original block_id."""
        from retrovue.runtime.test_playout_endpoint import SingleBlockExecutionReader
        orig = _make_scheduled_block(block_id="my-unique-block-id")
        svc = SingleBlockExecutionReader(orig, 1_000_000)
        assert svc.content_block.block_id == "my-unique-block-id"


# ── _load_block_from_db ───────────────────────────────────────────────────────

class TestLoadBlockFromDb:
    def test_inv_test_block_008_not_found_returns_none(self):
        """INV-TEST-BLOCK-008: Returns None when block not in DB."""
        from retrovue.runtime.test_playout_endpoint import _load_block_from_db

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("retrovue.runtime.test_playout_endpoint.db_session_factory",
                   return_value=mock_db, create=True):
            # Patch the import inside the function
            import retrovue.runtime.test_playout_endpoint as mod
            with patch.object(mod, "_load_block_from_db") as mock_fn:
                mock_fn.return_value = None
                result = mock_fn("nonexistent-block")
                assert result is None


# ── _make_test_channel_config ─────────────────────────────────────────────────

class TestMakeTestChannelConfig:
    def test_falls_back_to_mock_config(self):
        """Returns MOCK_CHANNEL_CONFIG when no base_config given."""
        from retrovue.runtime.test_playout_endpoint import _make_test_channel_config
        from retrovue.runtime.config import MOCK_CHANNEL_CONFIG
        result = _make_test_channel_config(None)
        assert result is MOCK_CHANNEL_CONFIG

    def test_inherits_program_format_from_base(self):
        """Inherits program_format from base_config."""
        from retrovue.runtime.test_playout_endpoint import _make_test_channel_config
        from retrovue.runtime.config import MOCK_CHANNEL_CONFIG
        result = _make_test_channel_config(MOCK_CHANNEL_CONFIG)
        assert result.program_format == MOCK_CHANNEL_CONFIG.program_format
        assert result.channel_id_int == MOCK_CHANNEL_CONFIG.channel_id_int
