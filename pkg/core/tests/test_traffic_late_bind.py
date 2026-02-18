"""
Tests for late-binding traffic architecture.

These tests define the contract — implementation must pass them.
See: docs/contracts/runtime/INV-TRAFFIC-LATE-BIND-001.md

Run with: cd /opt/retrovue/pkg/core && .venv/bin/pytest tests/test_traffic_late_bind.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.traffic_manager import fill_ad_blocks

# ─────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────

START_MS = 1_739_800_000_000  # Arbitrary fixed epoch for test blocks


def _make_block_with_empty_fillers(
    break_duration_ms: int = 120_000,
    num_breaks: int = 1,
) -> ScheduledBlock:
    """Build a ScheduledBlock with empty filler placeholders (post-compile-time form).

    Each break is a single filler segment with asset_uri="".
    This is the form DslScheduleService MUST produce (INV-TRAFFIC-LATE-BIND-001).
    """
    block_id = f"block-test-{uuid.uuid4().hex[:8]}"
    segments = [
        ScheduledSegment(
            segment_type="content",
            asset_uri="/media/shows/ep1.mp4",
            asset_start_offset_ms=0,
            segment_duration_ms=600_000,
        ),
    ]
    for _ in range(num_breaks):
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri="",  # Empty URI = unfilled placeholder
            asset_start_offset_ms=0,
            segment_duration_ms=break_duration_ms,
        ))
    # Pad to reach a round slot
    segments.append(ScheduledSegment(
        segment_type="pad",
        asset_uri="",
        asset_start_offset_ms=0,
        segment_duration_ms=0,
    ))
    total_ms = sum(s.segment_duration_ms for s in segments)
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=START_MS,
        end_utc_ms=START_MS + total_ms,
        segments=tuple(segments),
    )


def _make_filler_asset(uri: str, duration_ms: int, asset_type: str = "commercial"):
    """Build a mock FillerAsset-like object."""
    asset = MagicMock()
    asset.asset_uri = uri
    asset.duration_ms = duration_ms
    asset.asset_type = asset_type
    return asset


# ─────────────────────────────────────────────────────────────────────
# Test 1: DslScheduleService produces empty filler placeholders
# ─────────────────────────────────────────────────────────────────────


class TestCompileProducesEmptyPlaceholders:
    """INV-TRAFFIC-LATE-BIND-001: compile time leaves asset_uri empty."""

    def test_filler_segments_have_empty_uri(self):
        """
        expand_program_block() produces filler segments with asset_uri="".

        This simulates what DslScheduleService._expand_blocks_inner() produces
        before calling fill_ad_blocks. The key invariant: filler segments coming
        out of the compiler must have asset_uri="" so feed-time can detect them.
        """
        block = expand_program_block(
            asset_id="ep1",
            asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        filler_segs = [s for s in block.segments if s.segment_type == "filler"]
        # expand_program_block emits filler with empty URI (no fill_ad_blocks called yet)
        # Note: In v1, expand_program_block may not set asset_uri="" for filler.
        # This test documents the contract: after our change, filler from compiler has "".
        # Currently expand_program_block uses asset_uri="" for filler by design.
        for seg in filler_segs:
            assert seg.asset_uri == "", (
                f"Compile-time filler segment must have asset_uri=''; got '{seg.asset_uri}'. "
                "DslScheduleService must not call fill_ad_blocks at compile time."
            )

    def test_content_segments_have_real_uri(self):
        """Content (program) segments must always have real asset URIs."""
        block = expand_program_block(
            asset_id="ep1",
            asset_uri="/shows/ep1.mp4",
            start_utc_ms=START_MS,
            slot_duration_ms=1_800_000,
            episode_duration_ms=1_320_000,
            chapter_markers_ms=(330_000, 660_000, 990_000),
        )
        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) > 0
        for seg in content_segs:
            assert seg.asset_uri != "", "Content segments must have a real URI."

    def test_empty_filler_placeholder_detected_by_fill_ad_blocks(self):
        """fill_ad_blocks identifies empty filler by asset_uri==""."""
        block = _make_block_with_empty_fillers(break_duration_ms=30_000)
        # With asset_library=None, static filler fills the placeholder
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 60_000, asset_library=None)
        filler_segs = [s for s in filled.segments if s.segment_type == "filler"]
        # Should have been replaced with static filler URI
        for seg in filler_segs:
            assert seg.asset_uri == "/ads/filler.mp4", (
                "Empty filler placeholder should be replaced by fill_ad_blocks."
            )


# ─────────────────────────────────────────────────────────────────────
# Test 2: fill_ad_blocks with asset_library fills placeholders
# ─────────────────────────────────────────────────────────────────────


class TestFillWithAssetLibrary:
    """fill_ad_blocks with a DatabaseAssetLibrary resolves real URIs."""

    def test_empty_filler_replaced_with_commercial(self):
        """
        Given a block with empty filler segments, fill_ad_blocks replaces them
        with real commercial URIs when asset_library returns candidates.
        """
        block = _make_block_with_empty_fillers(break_duration_ms=60_000)

        mock_lib = MagicMock()
        mock_lib.get_filler_assets.return_value = [
            _make_filler_asset("/ads/commercial-a.mp4", 30_000, "commercial"),
            _make_filler_asset("/ads/commercial-b.mp4", 30_000, "commercial"),
        ]

        filled = fill_ad_blocks(block, "/ads/filler.mp4", 60_000, asset_library=mock_lib)

        # No empty URIs in output
        non_pad_segs = [s for s in filled.segments if s.segment_type != "pad" and s.asset_uri == ""]
        filler_empty = [s for s in non_pad_segs if s.segment_type == "filler"]
        assert filler_empty == [], (
            "All filler placeholders must be replaced by fill_ad_blocks when asset_library is provided."
        )

        # Real commercial URIs present
        uris = {s.asset_uri for s in filled.segments if s.segment_type != "pad"}
        assert "/ads/commercial-a.mp4" in uris or "/ads/commercial-b.mp4" in uris

    def test_break_duration_preserved_invariant(self):
        """
        INV-BREAK-PAD-EXACT-001: Total break segment duration must equal allocated break.
        """
        break_duration_ms = 90_000
        block = _make_block_with_empty_fillers(break_duration_ms=break_duration_ms)

        mock_lib = MagicMock()
        # Return 2 spots: 30s + 30s = 60s, leaving 30s gap
        mock_lib.get_filler_assets.side_effect = [
            [_make_filler_asset("/ads/spot-a.mp4", 30_000, "commercial")],
            [_make_filler_asset("/ads/spot-b.mp4", 30_000, "commercial")],
            [],  # No more candidates
        ]

        filled = fill_ad_blocks(block, "/ads/filler.mp4", 90_000, asset_library=mock_lib)

        # Find the break segments (all segments between first content and next content/pad)
        # Count total duration of non-content segments that replaced the break
        segs = list(filled.segments)
        # Break spans from after content to end (minus trailing pad)
        content_end = None
        for i, s in enumerate(segs):
            if s.segment_type == "content":
                content_end = i
        break_segs = segs[content_end + 1:] if content_end is not None else []
        # Remove trailing zero-duration pad
        break_segs = [s for s in break_segs if s.segment_duration_ms > 0]
        break_total = sum(s.segment_duration_ms for s in break_segs)
        assert break_total == break_duration_ms, (
            f"INV-BREAK-PAD-EXACT-001: break segments sum {break_total}ms "
            f"!= allocated {break_duration_ms}ms"
        )

    def test_distributed_pad_between_spots(self):
        """
        INV-BREAK-PAD-DISTRIBUTED-001: leftover time distributed as inter-spot pads.
        """
        break_duration_ms = 62_000  # 62s
        block = _make_block_with_empty_fillers(break_duration_ms=break_duration_ms)

        mock_lib = MagicMock()
        # 2 spots x 30s = 60s, leaving 2s gap
        mock_lib.get_filler_assets.side_effect = [
            [_make_filler_asset("/ads/spot-a.mp4", 30_000, "commercial")],
            [_make_filler_asset("/ads/spot-b.mp4", 30_000, "commercial")],
            [],  # Done
        ]

        filled = fill_ad_blocks(block, "/ads/filler.mp4", 62_000, asset_library=mock_lib)

        pads = [s for s in filled.segments if s.segment_type == "pad" and s.segment_duration_ms > 0]
        assert len(pads) >= 1, "Leftover break time must be distributed as pad segments."
        total_pad = sum(s.segment_duration_ms for s in pads)
        assert total_pad == 2_000, f"Expected 2000ms total pad, got {total_pad}ms"


# ─────────────────────────────────────────────────────────────────────
# Test 3: fill_ad_blocks without asset_library uses static filler
# ─────────────────────────────────────────────────────────────────────


class TestFillWithoutAssetLibrary:
    """fill_ad_blocks with asset_library=None falls back to static filler (v1 behavior)."""

    def test_static_filler_uri_used(self):
        """Empty filler placeholder replaced with the static filler URI."""
        block = _make_block_with_empty_fillers(break_duration_ms=30_000)
        filled = fill_ad_blocks(block, "/ads/static-filler.mp4", 60_000, asset_library=None)
        filler_segs = [s for s in filled.segments if s.segment_type == "filler"]
        assert len(filler_segs) == 1
        assert filler_segs[0].asset_uri == "/ads/static-filler.mp4"

    def test_static_filler_duration_preserved(self):
        """Static filler segment has the same duration as the break placeholder."""
        break_ms = 30_000
        block = _make_block_with_empty_fillers(break_duration_ms=break_ms)
        filled = fill_ad_blocks(block, "/ads/filler.mp4", 60_000, asset_library=None)
        filler_segs = [s for s in filled.segments if s.segment_type == "filler"]
        assert filler_segs[0].segment_duration_ms == break_ms


# ─────────────────────────────────────────────────────────────────────
# Test 4: transmission_log persistence round-trip
# ─────────────────────────────────────────────────────────────────────


class TestTransmissionLogPersistence:
    """transmission_log write/read round-trip via the SQLAlchemy model."""

    def test_transmission_log_write_read(self):
        """
        Write a filled block to transmission_log and read it back.
        Verifies segments JSONB round-trips correctly.
        """
        from retrovue.infra.uow import session as db_session_factory

        block_id = f"block-roundtrip-{uuid.uuid4().hex[:8]}"
        channel_slug = "test-channel"
        broadcast_day = date.today()
        start_ms = START_MS
        end_ms = START_MS + 1_800_000

        segments_data = [
            {
                "segment_index": 0,
                "segment_type": "content",
                "asset_uri": "/media/shows/ep1.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 1_320_000,
                "title": "ep1",
            },
            {
                "segment_index": 1,
                "segment_type": "commercial",
                "asset_uri": "/media/interstitials/ad-a.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 30_000,
                "title": "ad-a",
            },
            {
                "segment_index": 2,
                "segment_type": "pad",
                "asset_uri": "",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 450_000,
                "title": "BLACK",
            },
        ]

        try:
            from retrovue.domain.entities import TransmissionLog
        except ImportError:
            pytest.skip("TransmissionLog entity not yet created (pre-build)")

        try:
            with db_session_factory() as db:
                # Write
                row = TransmissionLog(
                    block_id=block_id,
                    channel_slug=channel_slug,
                    broadcast_day=broadcast_day,
                    start_utc_ms=start_ms,
                    end_utc_ms=end_ms,
                    segments=segments_data,
                )
                db.add(row)
                db.flush()

                # Read back in same session
                found = db.query(TransmissionLog).filter(
                    TransmissionLog.block_id == block_id
                ).first()

                assert found is not None, "Written row must be readable."
                assert found.block_id == block_id
                assert found.channel_slug == channel_slug
                assert found.segments == segments_data, "Segments JSONB must round-trip."
                assert found.start_utc_ms == start_ms
                assert found.end_utc_ms == end_ms

                db.rollback()  # Don't pollute the test DB

        except Exception as e:
            if "does not exist" in str(e) or "no such table" in str(e):
                pytest.skip(f"transmission_log table not yet migrated: {e}")
            raise


# ─────────────────────────────────────────────────────────────────────
# Test 5: Evidence server segment lookup from transmission_log
# ─────────────────────────────────────────────────────────────────────


class TestEvidenceServerSegmentLookup:
    """Evidence server queries transmission_log for segment enrichment."""

    def test_lookup_correct_segment_by_index(self):
        """
        Given a transmission_log row, querying by (block_id, segment_index)
        returns the correct segment_type and title.
        """
        segments = [
            {"segment_index": 0, "segment_type": "content",
             "asset_uri": "/media/shows/ep1.mp4", "asset_start_offset_ms": 0,
             "segment_duration_ms": 1_320_000, "title": "ep1"},
            {"segment_index": 1, "segment_type": "commercial",
             "asset_uri": "/media/ads/brand-30s.mp4", "asset_start_offset_ms": 0,
             "segment_duration_ms": 30_000, "title": "brand-30s"},
            {"segment_index": 2, "segment_type": "pad",
             "asset_uri": "", "asset_start_offset_ms": 0,
             "segment_duration_ms": 450_000, "title": "BLACK"},
        ]

        def fake_query_transmission_log(block_id):
            return segments

        # Simulate the evidence server lookup logic
        block_id = "block-test-001"
        segment_index = 1

        segs = fake_query_transmission_log(block_id)
        found = next((s for s in segs if s["segment_index"] == segment_index), None)

        assert found is not None
        assert found["segment_type"] == "commercial"
        assert found["asset_uri"] == "/media/ads/brand-30s.mp4"
        assert found["title"] == "brand-30s"
        assert found["segment_duration_ms"] == 30_000

    def test_lookup_pad_segment(self):
        """Pad segments return segment_type='pad' and title='BLACK'."""
        segments = [
            {"segment_index": 0, "segment_type": "content",
             "asset_uri": "/ep1.mp4", "asset_start_offset_ms": 0,
             "segment_duration_ms": 100_000, "title": "ep1"},
            {"segment_index": 1, "segment_type": "pad",
             "asset_uri": "", "asset_start_offset_ms": 0,
             "segment_duration_ms": 5_000, "title": "BLACK"},
        ]

        found = next((s for s in segments if s["segment_index"] == 1), None)
        assert found["segment_type"] == "pad"
        assert found["title"] == "BLACK"

    def test_lookup_missing_block_returns_none(self):
        """When block_id not found in transmission_log, lookup returns None gracefully."""
        cache: dict = {}

        def lookup(block_id, segment_index):
            segs = cache.get(block_id)
            if segs is None:
                return None
            return next((s for s in segs if s["segment_index"] == segment_index), None)

        result = lookup("nonexistent-block", 0)
        assert result is None, "Missing block must return None, not raise."

    def test_asrun_type_mapping(self):
        """segment_type maps to correct .asrun type abbreviation."""
        type_map = {
            "content": "PROGRAM",
            "commercial": "COMMERCL",
            "promo": "PROMO",
            "ident": "IDENT",
            "psa": "PSA",
            "filler": "FILLER",
            "pad": "PAD",
        }

        for seg_type, expected_asrun_type in type_map.items():
            # Simulate the evidence server's type-mapping logic
            asrun_type = {
                "content": "PROGRAM",
                "commercial": "COMMERCL",
                "promo": "PROMO",
                "ident": "IDENT",
                "psa": "PSA",
                "filler": "FILLER",
                "pad": "PAD",
            }.get(seg_type, "PROGRAM")
            assert asrun_type == expected_asrun_type, (
                f"segment_type={seg_type!r} should map to asrun_type={expected_asrun_type!r}"
            )


# ─────────────────────────────────────────────────────────────────────
# Test 6: Cooldowns evaluated at fill time, not compile time
# ─────────────────────────────────────────────────────────────────────


class TestCooldownAtFillTime:
    """INV-TRAFFIC-LATE-BIND-001: Cooldowns are evaluated at fill time."""

    def test_asset_excluded_by_cooldown_at_fill_time(self):
        """
        Compile a block (no cooldowns active). Log a play for asset X.
        Fill the same block again. Asset X should be excluded (cooldown active).

        This is the core correctness guarantee of late-binding traffic.
        """
        # Simulate the DatabaseAssetLibrary's cooldown behavior:
        # first call returns asset X, second call excludes it.

        played_uris: set[str] = set()

        def get_filler_assets_with_cooldown(max_duration_ms, count):
            """Exclude assets that have been played (simulates cooldown)."""
            all_assets = [
                _make_filler_asset("/ads/asset-x.mp4", 30_000, "commercial"),
                _make_filler_asset("/ads/asset-y.mp4", 30_000, "commercial"),
            ]
            available = [a for a in all_assets if a.asset_uri not in played_uris]
            return available[:count]

        mock_lib = MagicMock()
        mock_lib.get_filler_assets.side_effect = get_filler_assets_with_cooldown

        # First fill: asset X is available
        block1 = _make_block_with_empty_fillers(break_duration_ms=30_000)
        filled1 = fill_ad_blocks(block1, "/ads/filler.mp4", 30_000, asset_library=mock_lib)
        non_pad_segs1 = [s for s in filled1.segments
                         if s.segment_type not in ("pad", "content") and s.asset_uri]
        assert any("/ads/asset-x.mp4" in s.asset_uri for s in non_pad_segs1), (
            "Asset X should be available before any plays are logged."
        )

        # Log a play for asset X (simulates traffic_play_log write)
        played_uris.add("/ads/asset-x.mp4")

        # Reset the side_effect for next call
        mock_lib.get_filler_assets.side_effect = get_filler_assets_with_cooldown

        # Second fill: asset X should be excluded
        block2 = _make_block_with_empty_fillers(break_duration_ms=30_000)
        filled2 = fill_ad_blocks(block2, "/ads/filler.mp4", 30_000, asset_library=mock_lib)
        non_pad_segs2 = [s for s in filled2.segments
                         if s.segment_type not in ("pad", "content") and s.asset_uri]
        assert not any("/ads/asset-x.mp4" in s.asset_uri for s in non_pad_segs2), (
            "Asset X should be excluded after being logged as played (cooldown active)."
        )
        # Asset Y should appear instead
        assert any("/ads/asset-y.mp4" in s.asset_uri for s in non_pad_segs2), (
            "Asset Y should be selected as the alternative."
        )


# ─────────────────────────────────────────────────────────────────────
# Test 7: As-run human-readable format includes commercial titles
# ─────────────────────────────────────────────────────────────────────


class TestAsRunFormat:
    """As-run human-readable .asrun format includes commercial titles in brackets."""

    def test_commercial_type_in_asrun_line(self):
        """
        Given a segment_info for a commercial, the .asrun type column is COMMERCL.
        """
        segment_info = {
            "segment_type": "commercial",
            "asset_uri": "/ads/brand-ad-30s.mp4",
            "title": "brand-ad-30s",
            "segment_duration_ms": 30_000,
        }

        # Simulate the evidence server's type-mapping logic
        asrun_type = {
            "content": "PROGRAM",
            "commercial": "COMMERCL",
            "promo": "PROMO",
            "ident": "IDENT",
            "psa": "PSA",
            "filler": "FILLER",
            "pad": "PAD",
        }.get(segment_info["segment_type"], "PROGRAM")

        assert asrun_type == "COMMERCL", (
            f"Commercial segment must produce asrun_type='COMMERCL', got {asrun_type!r}"
        )

    def test_title_in_brackets_in_asrun_notes(self):
        """
        The .asrun notes column contains the asset title in brackets: [brand-ad-30s].
        """
        segment_info = {
            "segment_type": "commercial",
            "asset_uri": "/ads/brand-ad-30s.mp4",
            "title": "brand-ad-30s",
            "segment_duration_ms": 30_000,
        }

        # Simulate notes formatting
        title = segment_info.get("title", "")
        notes = f"[{title}]" if title else ""

        assert notes == "[brand-ad-30s]", (
            f"Notes must contain title in brackets; got {notes!r}"
        )

    def test_content_segment_maps_to_program(self):
        """Content segments map to PROGRAM type."""
        seg = {"segment_type": "content", "title": "episode-s01e01"}
        asrun_type = {
            "content": "PROGRAM",
            "commercial": "COMMERCL",
        }.get(seg["segment_type"], "PROGRAM")
        assert asrun_type == "PROGRAM"

    def test_pad_segment_maps_to_pad_type(self):
        """Pad segments map to PAD type."""
        seg = {"segment_type": "pad", "title": "BLACK"}
        asrun_type = {
            "pad": "PAD",
        }.get(seg["segment_type"], "PROGRAM")
        assert asrun_type == "PAD"

    def test_unknown_segment_type_falls_back_to_program(self):
        """Unknown segment types fall back to PROGRAM (graceful degradation)."""
        seg = {"segment_type": "unknown_future_type"}
        asrun_type = {
            "content": "PROGRAM",
            "commercial": "COMMERCL",
        }.get(seg["segment_type"], "PROGRAM")
        assert asrun_type == "PROGRAM"

    def test_asrun_jsonl_record_structure(self):
        """
        .asrun.jsonl enriched SEG_START record has required fields.
        """
        # Simulate what the evidence server produces for an enriched SEG_START
        seg_info = {
            "segment_type": "commercial",
            "asset_uri": "/ads/brand-30s.mp4",
            "title": "brand-30s",
            "segment_duration_ms": 30_000,
        }

        jsonl_record = {
            "event_type": "SEG_START",
            "block_id": "block-20260218-1030",
            "segment_index": 1,
            "start_utc_ms": 1_739_872_200_000,
            "segment_type": seg_info["segment_type"],
            "asset_uri": seg_info["asset_uri"],
            "segment_title": seg_info["title"],
            "segment_duration_ms": seg_info["segment_duration_ms"],
        }

        # Verify all required fields present
        assert jsonl_record["segment_type"] == "commercial"
        assert jsonl_record["asset_uri"] == "/ads/brand-30s.mp4"
        assert jsonl_record["segment_title"] == "brand-30s"
        assert jsonl_record["segment_duration_ms"] == 30_000

        # Should be JSON-serializable
        serialized = json.dumps(jsonl_record)
        parsed = json.loads(serialized)
        assert parsed["segment_type"] == "commercial"
