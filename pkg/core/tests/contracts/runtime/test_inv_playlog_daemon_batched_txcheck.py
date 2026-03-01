"""Contract tests for INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001.

PlaylogHorizonDaemon MUST batch TransmissionLog existence checks and
yield GIL between block fills.

Rules:
1. _extend_to_target() MUST check TransmissionLog existence for
   candidate blocks using a single batched query per scan-day —
   not one query per block.
2. _extend_to_target() MUST yield the GIL (e.g. time.sleep(0.001))
   after each block fill.
3. A _batch_block_exists_in_txlog(block_ids) method MUST exist and
   MUST return set[str].
"""

import time
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daemon():
    from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
    return PlaylogHorizonDaemon(
        channel_id="test-ch",
        min_hours=2,
        programming_day_start_hour=6,
        channel_tz="UTC",
    )


def _fake_block_dict(block_id: str, start_ms: int, end_ms: int, segments_count: int = 3):
    """Minimal Tier-1 segmented block dict."""
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


# ---------------------------------------------------------------------------
# Rule 3: _batch_block_exists_in_txlog method MUST exist
# ---------------------------------------------------------------------------

class TestRule3BatchMethodExists:
    """Rule 3: _batch_block_exists_in_txlog(block_ids) MUST exist and return set[str]."""

    def test_method_exists(self):
        daemon = _make_daemon()
        assert hasattr(daemon, "_batch_block_exists_in_txlog"), (
            "_batch_block_exists_in_txlog method MUST exist on PlaylogHorizonDaemon"
        )
        assert callable(daemon._batch_block_exists_in_txlog)


# ---------------------------------------------------------------------------
# Rule 1: Batched existence checks — not per-block queries
# ---------------------------------------------------------------------------

class TestRule1BatchedExistenceCheck:
    """Rule 1: _extend_to_target() MUST NOT call _block_exists_in_txlog per-block."""

    def test_extend_does_not_call_per_block_exists(self):
        """When extending over multiple candidate blocks, the per-block
        _block_exists_in_txlog MUST NOT be called. Instead, the batched
        method _batch_block_exists_in_txlog MUST be used.
        """
        daemon = _make_daemon()
        now_ms = 1_000_000
        target_ms = 2 * 3_600_000  # 2 hours

        # 4 blocks spanning now → now+2h
        blocks = [
            _fake_block_dict(f"blk-{i}", now_ms + i * 1_800_000, now_ms + (i + 1) * 1_800_000)
            for i in range(4)
        ]

        with (
            patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
            patch.object(daemon, "_block_exists_in_txlog", wraps=lambda _bid: False) as mock_per_block,
            patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()) as mock_batch,
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
            patch.object(daemon, "_write_to_txlog"),
            patch("time.sleep"),
        ):
            daemon._farthest_end_utc_ms = now_ms
            daemon._extend_to_target(now_ms, target_ms)

        # INV: per-block method MUST NOT have been called
        mock_per_block.assert_not_called(), (
            "_extend_to_target called _block_exists_in_txlog per-block "
            "instead of using batched _batch_block_exists_in_txlog"
        )

        # INV: batched method MUST have been called at least once
        assert mock_batch.call_count >= 1, (
            "_batch_block_exists_in_txlog was never called — "
            "_extend_to_target must use batched existence checks"
        )


# ---------------------------------------------------------------------------
# Rule 2: GIL yield after each block fill
# ---------------------------------------------------------------------------

class TestRule2GilYield:
    """Rule 2: _extend_to_target() MUST yield GIL after each block fill."""

    def test_sleep_called_after_each_fill(self):
        """After filling each block, time.sleep() MUST be called to yield GIL."""
        daemon = _make_daemon()
        now_ms = 1_000_000
        target_ms = 2 * 3_600_000

        # 3 blocks, none exist in txlog → all will be filled
        blocks = [
            _fake_block_dict(f"blk-{i}", now_ms + i * 1_800_000, now_ms + (i + 1) * 1_800_000)
            for i in range(3)
        ]

        sleep_calls = []

        with (
            patch.object(daemon, "_load_tier1_blocks", return_value=blocks),
            patch.object(daemon, "_batch_block_exists_in_txlog", return_value=set()),
            patch.object(daemon, "_fill_ads", side_effect=lambda b: b),
            patch.object(daemon, "_write_to_txlog"),
            patch("retrovue.runtime.playlog_horizon_daemon.time.sleep", side_effect=lambda s: sleep_calls.append(s)) as mock_sleep,
        ):
            daemon._farthest_end_utc_ms = now_ms
            daemon._extend_to_target(now_ms, target_ms)

        # INV: sleep MUST be called at least once per filled block
        assert len(sleep_calls) >= 3, (
            f"time.sleep() called {len(sleep_calls)} times for 3 block fills — "
            f"MUST yield GIL after each fill"
        )
        # Each sleep must be > 0 (meaningful yield)
        for s in sleep_calls:
            assert s > 0, f"time.sleep({s}) is not a meaningful GIL yield"
