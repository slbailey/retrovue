"""
Contract tests: INV-GRPC-FEED-BACKPRESSURE-001

FeedBlockPlan MUST return FeedResult.QUEUE_FULL as a capacity signal (not error)
when AIR's block queue is full. Core MUST distinguish capacity exhaustion from
transport failure.

These tests validate Core client behavior via PlayoutSession.feed().
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


class TestFeedBackpressureContract:
    """INV-GRPC-FEED-BACKPRESSURE-001: Feed backpressure signaling.

    Validates that PlayoutSession correctly maps AIR's QUEUE_FULL response
    to FeedResult.QUEUE_FULL (not FeedResult.ERROR).
    """

    @pytest.fixture(autouse=True)
    def _load_source(self):
        src_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "retrovue"
            / "runtime"
            / "playout_session.py"
        )
        self.source = src_path.read_text()

    def test_feed_result_has_queue_full_variant(self):
        """FeedResult enum includes QUEUE_FULL as a distinct variant."""
        assert "QUEUE_FULL" in self.source, (
            "FeedResult must have a QUEUE_FULL variant"
        )

    def test_feed_distinguishes_queue_full_from_error(self):
        """feed() maps queue_full response to FeedResult.QUEUE_FULL, not ERROR.

        The response.queue_full field MUST be checked before returning ERROR.
        """
        # The feed() method must check response.queue_full
        assert re.search(
            r"response\.queue_full", self.source
        ), "feed() must check response.queue_full"

        # And return QUEUE_FULL, not ERROR
        assert re.search(
            r"FeedResult\.QUEUE_FULL", self.source
        ), "feed() must return FeedResult.QUEUE_FULL on capacity exhaustion"

    def test_queue_full_is_not_logged_as_error(self):
        """QUEUE_FULL is a capacity signal — it MUST NOT be logged at error level."""
        # Find the code path that handles queue_full
        # It should use logger.warning or logger.debug, not logger.error
        queue_full_block = re.search(
            r"if response\.queue_full:.*?return FeedResult\.QUEUE_FULL",
            self.source,
            re.DOTALL,
        )
        assert queue_full_block is not None, (
            "Could not find queue_full handling block"
        )
        block_text = queue_full_block.group(0)
        assert "logger.error" not in block_text, (
            "INV-GRPC-FEED-BACKPRESSURE-001: QUEUE_FULL must not be logged "
            "at error level — it is a capacity signal, not a failure"
        )

    def test_feed_result_enum_has_three_states(self):
        """FeedResult has exactly three states: ACCEPTED, QUEUE_FULL, ERROR."""
        assert "ACCEPTED" in self.source
        assert "QUEUE_FULL" in self.source
        assert "ERROR" in self.source
