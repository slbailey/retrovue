"""
Contract test for INV-BLOCKPLAN-PROTO-INT-001.

Invariant:
    All millisecond fields in BlockPlan.to_proto() MUST be integers.
    Protobuf int64 fields reject float values with:
        TypeError: 'float' object cannot be interpreted as an integer

    This invariant guards the boundary between Python schedule data
    (which may contain floats from duration_sec * 1000 arithmetic)
    and the gRPC protobuf wire format (which requires exact int types).
"""

import pytest

from retrovue.runtime.playout_session import BlockPlan


def _make_block(*, segment_duration_ms=5000, asset_start_offset_ms=0):
    """Build a minimal BlockPlan with configurable segment fields."""
    return BlockPlan(
        block_id="test-block-001",
        channel_id=1,
        start_utc_ms=1000000,
        end_utc_ms=1005000,
        segments=[
            {
                "segment_index": 0,
                "segment_type": "content",
                "asset_uri": "/media/test.ts",
                "asset_start_offset_ms": asset_start_offset_ms,
                "segment_duration_ms": segment_duration_ms,
            }
        ],
    )


class TestInvBlockplanProtoInt001:
    """INV-BLOCKPLAN-PROTO-INT-001: to_proto() MUST accept float-typed ms
    fields and coerce them to int, since schedule compilation may produce
    floats from duration_sec * 1000 arithmetic."""

    def test_float_segment_duration_ms_accepted(self):
        """BPINT-001: Float segment_duration_ms does not raise TypeError."""
        block = _make_block(segment_duration_ms=5000.0)
        pb = block.to_proto()
        assert pb.segments[0].segment_duration_ms == 5000

    def test_float_asset_start_offset_ms_accepted(self):
        """BPINT-002: Float asset_start_offset_ms does not raise TypeError."""
        block = _make_block(asset_start_offset_ms=1500.0)
        pb = block.to_proto()
        assert pb.segments[0].asset_start_offset_ms == 1500

    def test_float_transition_duration_ms_accepted(self):
        """BPINT-003: Float transition durations do not raise TypeError."""
        block = BlockPlan(
            block_id="test-block-002",
            channel_id=1,
            start_utc_ms=1000000,
            end_utc_ms=1005000,
            segments=[
                {
                    "segment_index": 0,
                    "segment_type": "content",
                    "asset_uri": "/media/test.ts",
                    "asset_start_offset_ms": 0,
                    "segment_duration_ms": 5000,
                    "transition_in": "TRANSITION_FADE",
                    "transition_in_duration_ms": 500.0,
                    "transition_out": "TRANSITION_FADE",
                    "transition_out_duration_ms": 500.0,
                }
            ],
        )
        pb = block.to_proto()
        assert pb.segments[0].transition_in_duration_ms == 500
        assert pb.segments[0].transition_out_duration_ms == 500

    def test_int_values_still_work(self):
        """BPINT-004: Integer values continue to work (regression guard)."""
        block = _make_block(segment_duration_ms=5000, asset_start_offset_ms=0)
        pb = block.to_proto()
        assert pb.segments[0].segment_duration_ms == 5000
        assert pb.segments[0].asset_start_offset_ms == 0

    def test_pad_segment_float_duration(self):
        """BPINT-005: PAD segment with float duration does not raise."""
        block = BlockPlan(
            block_id="test-block-003",
            channel_id=1,
            start_utc_ms=1000000,
            end_utc_ms=1005000,
            segments=[
                {
                    "segment_index": 0,
                    "segment_type": "pad",
                    "segment_duration_ms": 3000.0,
                }
            ],
        )
        pb = block.to_proto()
        assert pb.segments[0].segment_duration_ms == 3000
