"""
Integration Tests: INV-AIR-SEGMENT-IDENTITY-AUTHORITY (Runtime)

These tests exercise the ACTUAL runtime code path and will fail 
until segment_uuid support is fully implemented.

Run: pytest pkg/air/tests/contracts/test_air_segment_identity_runtime.py -v
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.planning_pipeline import (
    to_block_plan,
    TransmissionLogEntry,
)


# =============================================================================
# Test: segment_uuid generation at feed time (to_block_plan)
# =============================================================================

class TestSegmentUuidGeneration:
    """INV-AIR-SEGMENT-ID-001: segment_uuid generated at block feed time."""

    def test_to_block_plan_includes_segment_uuid(self):
        """Fail if to_block_plan output lacks segment_uuid fields."""
        seg_entry = TransmissionLogEntry(
            block_id="blk-001",
            block_index=0,
            start_utc_ms=1735680000000,
            end_utc_ms=1735681800000,
            segments=[
                {
                    "segment_index": 0,
                    "asset_uri": "/media/asset1.mp4",
                    "segment_duration_ms": 30000,
                    "segment_type": "episode",
                }
            ],
        )
        
        block_plan = to_block_plan(seg_entry, channel_id_int=1)
        
        # First segment must have segment_uuid
        assert "segments" in block_plan
        seg = block_plan["segments"][0]
        
        assert "segment_uuid" in seg, (
            "INV-AIR-SEGMENT-ID-001 VIOLATION: to_block_plan() output "
            "missing segment_uuid. UUID must be generated at feed time."
        )
        # Must be a valid UUID
        uuid.UUID(seg["segment_uuid"])
        
    def test_segment_uuid_presence_in_block_plan(self):
        """Every segment in a fed block must carry segment_uuid."""
        seg_entry = TransmissionLogEntry(
            block_id="blk-test-042",
            block_index=0,
            start_utc_ms=1735680000000,
            end_utc_ms=1735681800000,
            segments=[
                {"segment_index": 0, "asset_uri": "/a.mp4", "segment_duration_ms": 10000, "segment_type": "episode"},
                {"segment_index": 1, "asset_uri": "/b.mp4", "segment_duration_ms": 15000, "segment_type": "filler"},
                {"segment_index": 2, "segment_duration_ms": 5000, "segment_type": "pad"},
            ],
        )
        
        block_plan = to_block_plan(seg_entry, channel_id_int=1)
        
        for seg in block_plan["segments"]:
            assert "segment_uuid" in seg, (
                f"INV-AIR-SEGMENT-ID-001 VIOLATION: segment_index={seg['segment_index']} "
                f"missing segment_uuid in block_plan output"
            )
            uuid.UUID(seg["segment_uuid"])


# =============================================================================
# Test: asset_uuid presence in fed segments
# =============================================================================

class TestAssetUuidInFedSegments:
    """INV-AIR-SEGMENT-ID-002: CONTENT/FILLER must have asset_uuid, PAD null."""

    def test_content_segment_has_asset_uuid(self):
        """Fail if CONTENT segment lacks asset_uuid."""
        seg_entry = TransmissionLogEntry(
            block_id="blk-001",
            block_index=0,
            start_utc_ms=1735680000000,
            end_utc_ms=1735681800000,
            segments=[
                {"segment_index": 0, "asset_uri": "/media/ep1.mp4", "segment_duration_ms": 30000, "segment_type": "episode"},
            ],
        )
        
        block_plan = to_block_plan(seg_entry, channel_id_int=1)
        seg = block_plan["segments"][0]
        
        assert "asset_uuid" in seg, (
            "INV-AIR-SEGMENT-ID-002 VIOLATION: CONTENT segment missing asset_uuid. "
            "Asset identity must be explicit at feed time."
        )
        if seg["asset_uuid"] is not None:
            uuid.UUID(seg["asset_uuid"])

    def test_pad_segment_has_null_asset_uuid(self):
        """Fail if PAD segment has non-null asset_uuid."""
        seg_entry = TransmissionLogEntry(
            block_id="blk-001",
            block_index=0,
            start_utc_ms=1735680000000,
            end_utc_ms=1735681800000,
            segments=[
                {"segment_index": 0, "segment_duration_ms": 5000, "segment_type": "pad"},
            ],
        )
        
        block_plan = to_block_plan(seg_entry, channel_id_int=1)
        seg = block_plan["segments"][0]
        
        assert "asset_uuid" in seg
        assert seg["asset_uuid"] is None, (
            f"INV-AIR-SEGMENT-ID-002 VIOLATION: PAD segment has asset_uuid="
            f"{seg['asset_uuid']}. PAD must emit asset_uuid=null."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
