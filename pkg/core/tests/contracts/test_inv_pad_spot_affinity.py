"""
Contract tests: Pad Spot Affinity — INV-PAD-SPOT-AFFINITY-001 and related

Validates that traffic padding segments are correctly associated with their
preceding asset via spot_index, and that all structural pad invariants hold:

- INV-PAD-SPOT-AFFINITY-001: pad.spot_index == predecessor.spot_index
- INV-PAD-NEVER-ORPHAN-001: pad never first; predecessor has spot_index != None
- INV-PAD-SPOT-UNIQUE-001: each spot_index → 1 asset + ≤1 pad
- INV-PAD-ONLY-TRAFFIC-001: traffic pads have spot_index != None; JIP pads have None
- INV-PAD-FRAME-DISTRIBUTION-001: remainder to final spot only
- INV-PAD-PROTO-INVISIBLE-001: spot_index not in proto output
- INV-PAD-CONSERVATION-UNCHANGED-001: spot_index does not alter conservation
- No adjacent pad segments
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pytest

try:
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    from retrovue.runtime.traffic_manager import fill_ad_blocks
    from retrovue.runtime.traffic_policy import PlayRecord, TrafficPolicy
    from retrovue.runtime.break_structure import BreakConfig
except ImportError:
    pytest.skip(
        "retrovue.runtime.traffic_manager or dependencies not yet implemented",
        allow_module_level=True,
    )

# Try to import BlockPlan + proto stubs for proto invisibility tests.
# These are optional — skip proto tests if stubs unavailable.
try:
    from retrovue.runtime.playout_session import BlockPlan
    import importlib
    import sys
    # Proto stubs may need dynamic loading; BlockPlan.to_proto does this internally.
    _HAS_PROTO = True
except ImportError:
    _HAS_PROTO = False

# Try to import _apply_jip_to_segments for JIP tests.
try:
    from retrovue.runtime.channel_manager import _apply_jip_to_segments
    _HAS_JIP = True
except ImportError:
    _HAS_JIP = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILLER_URI = "/media/filler/bars.ts"
FILLER_DURATION_MS = 30_000
NOW_MS = 10_000_000_000
DAY_START_MS = 9_900_000_000
GRID_DURATION_MS = 1_800_000


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_traffic_manager.py to keep test files independent)
# ---------------------------------------------------------------------------

@dataclass
class FakeFillerAsset:
    asset_uri: str
    asset_type: str
    duration_ms: int


class FakeAssetLibrary:
    def __init__(self, assets: list[FakeFillerAsset]) -> None:
        self._assets = assets

    def get_filler_assets(
        self, max_duration_ms: int = 0, count: int = 5,
    ) -> list[FakeFillerAsset]:
        eligible = [a for a in self._assets if a.duration_ms <= max_duration_ms]
        return eligible[:count]


def _make_library(*specs: tuple[str, str, int]) -> FakeAssetLibrary:
    return FakeAssetLibrary([
        FakeFillerAsset(asset_uri=uri, asset_type=atype, duration_ms=dur)
        for uri, atype, dur in specs
    ])


def _policy(**overrides) -> TrafficPolicy:
    defaults = dict(
        allowed_types=["commercial", "promo", "filler"],
        default_cooldown_seconds=0,
        type_cooldowns_seconds={},
        max_plays_per_day=0,
    )
    defaults.update(overrides)
    return TrafficPolicy(**defaults)


def _block_with_filler(filler_duration_ms: int, block_id: str = "blk-1") -> ScheduledBlock:
    content_ms = GRID_DURATION_MS - filler_duration_ms
    segments = [
        ScheduledSegment(
            segment_type="episode",
            asset_uri="/media/shows/ep01.ts",
            asset_start_offset_ms=0,
            segment_duration_ms=content_ms,
            is_primary=True,
        ),
        ScheduledSegment(
            segment_type="filler",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=filler_duration_ms,
        ),
    ]
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=NOW_MS,
        end_utc_ms=NOW_MS + GRID_DURATION_MS,
        segments=tuple(segments),
    )


def _fill(break_ms: int, lib: FakeAssetLibrary, **kwargs) -> ScheduledBlock:
    """Shorthand: build block with filler placeholder, fill it, return result."""
    block = _block_with_filler(break_ms)
    defaults = dict(
        filler_uri=FILLER_URI,
        filler_duration_ms=FILLER_DURATION_MS,
        asset_library=lib,
        policy=_policy(),
        play_history=[],
        now_ms=NOW_MS,
        day_start_ms=DAY_START_MS,
    )
    defaults.update(kwargs)
    return fill_ad_blocks(block, **defaults)


def _pads(result: ScheduledBlock) -> list[ScheduledSegment]:
    return [s for s in result.segments if s.segment_type == "pad"]


def _non_content(result: ScheduledBlock) -> list[ScheduledSegment]:
    """All segments that aren't episode/content (i.e., the filled break)."""
    return [s for s in result.segments
            if s.segment_type not in ("episode", "content") and not s.is_primary]


# ===========================================================================
# INV-PAD-SPOT-AFFINITY-001
# ===========================================================================


class TestPadSpotAffinity:
    """INV-PAD-SPOT-AFFINITY-001: pad.spot_index == predecessor.spot_index."""

    def test_pad_spot_index_matches_preceding_asset(self):
        """3 spots with gap — every pad's spot_index matches its predecessor."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        segs = result.segments
        for i, seg in enumerate(segs):
            if seg.segment_type == "pad":
                pred = segs[i - 1]
                assert seg.spot_index == pred.spot_index, (
                    f"INV-PAD-SPOT-AFFINITY-001: pad at {i} has spot_index="
                    f"{seg.spot_index} but predecessor has {pred.spot_index}"
                )

    def test_pad_affinity_with_single_spot(self):
        """1 spot + pad — both have spot_index == 0."""
        # 25s asset in a 30s break → 1 pick + 5s pad (no second asset fits)
        lib = _make_library(("a.ts", "promo", 25_000))
        result = _fill(30_000, lib)
        pads = _pads(result)
        assert len(pads) == 1
        assert pads[0].spot_index == 0
        # Find the asset segment with spot_index == 0
        assets = [s for s in result.segments if s.spot_index == 0 and s.segment_type != "pad"]
        assert len(assets) == 1

    def test_pad_affinity_structured_break(self):
        """Structured break: pad affinity holds within interstitial section."""
        bumper_config = BreakConfig(to_break_bumper_ms=3000, from_break_bumper_ms=3000)
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
        )
        result = _fill(
            60_000, lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            break_config=bumper_config,
        )
        segs = result.segments
        for i, seg in enumerate(segs):
            if seg.segment_type == "pad":
                pred = segs[i - 1]
                assert seg.spot_index == pred.spot_index
        # Bumpers must have spot_index == None
        bumpers = [s for s in segs if s.segment_type == "bumper"]
        for b in bumpers:
            assert b.spot_index is None, (
                f"Bumper should have spot_index=None, got {b.spot_index}"
            )


# ===========================================================================
# INV-PAD-NEVER-ORPHAN-001
# ===========================================================================


class TestPadNeverOrphan:
    """INV-PAD-NEVER-ORPHAN-001: pad never first; predecessor has spot_index != None."""

    def test_pad_never_first_in_break(self):
        """No pad segment appears at position 0 of the filled break sub-array."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        filled = _non_content(result)
        assert len(filled) > 0
        assert filled[0].segment_type != "pad", (
            "INV-PAD-NEVER-ORPHAN-001: pad at position 0 of break"
        )

    def test_pad_never_follows_bumper_directly(self):
        """Pad never immediately follows a bumper segment."""
        bumper_config = BreakConfig(to_break_bumper_ms=5000, from_break_bumper_ms=5000)
        lib = _make_library(
            ("bumper_in.ts", "bumper", 5000),
            ("bumper_out.ts", "bumper", 5000),
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        result = _fill(
            60_000, lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            break_config=bumper_config,
        )
        segs = result.segments
        for i, seg in enumerate(segs):
            if seg.segment_type == "pad":
                pred = segs[i - 1]
                assert pred.segment_type != "bumper", (
                    f"INV-PAD-NEVER-ORPHAN-001: pad at {i} follows bumper"
                )

    def test_pad_never_follows_content(self):
        """No pad immediately follows a content/episode segment."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        segs = result.segments
        for i, seg in enumerate(segs):
            if seg.segment_type == "pad":
                pred = segs[i - 1]
                assert pred.segment_type not in ("content", "episode"), (
                    f"INV-PAD-NEVER-ORPHAN-001: pad at {i} follows {pred.segment_type}"
                )


# ===========================================================================
# INV-PAD-SPOT-UNIQUE-001
# ===========================================================================


class TestPadSpotUnique:
    """INV-PAD-SPOT-UNIQUE-001: each spot_index → 1 asset + ≤1 pad."""

    def test_each_spot_index_has_one_asset_one_pad(self):
        """4 spots with gap: each spot_index has exactly 1 asset and at most 1 pad."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
            ("d.ts", "promo", 30_000),
        )
        result = _fill(130_000, lib)
        spot_assets: Counter[int] = Counter()
        spot_pads: Counter[int] = Counter()
        for seg in result.segments:
            if seg.spot_index is None:
                continue
            if seg.segment_type == "pad":
                spot_pads[seg.spot_index] += 1
            else:
                spot_assets[seg.spot_index] += 1
        for si in set(spot_assets) | set(spot_pads):
            assert spot_assets[si] == 1, f"spot_index={si} has {spot_assets[si]} assets"
            assert spot_pads[si] <= 1, f"spot_index={si} has {spot_pads[si]} pads"

    def test_exact_fill_no_pad_still_has_spot_index(self):
        """4 spots filling exactly — each asset has distinct spot_index, no pads."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
            ("d.ts", "promo", 30_000),
        )
        result = _fill(120_000, lib)
        pads = _pads(result)
        assert len(pads) == 0
        spot_indices = [
            s.spot_index for s in result.segments if s.spot_index is not None
        ]
        assert spot_indices == [0, 1, 2, 3]

    def test_spot_index_values_are_contiguous(self):
        """spot_index values are 0-based and contiguous."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        indices = sorted({
            s.spot_index for s in result.segments if s.spot_index is not None
        })
        assert indices == list(range(len(indices)))


# ===========================================================================
# INV-PAD-ONLY-TRAFFIC-001
# ===========================================================================


class TestPadOnlyTraffic:
    """INV-PAD-ONLY-TRAFFIC-001: traffic pads have spot_index != None;
    JIP/default pads have spot_index == None."""

    def test_traffic_pad_has_spot_index(self):
        """Every pad from traffic fill has spot_index != None."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        pads = _pads(result)
        assert len(pads) > 0
        for p in pads:
            assert p.spot_index is not None, (
                "INV-PAD-ONLY-TRAFFIC-001: traffic pad has spot_index=None"
            )

    @pytest.mark.skipif(not _HAS_JIP, reason="channel_manager not importable")
    def test_jip_pad_has_no_spot_index(self):
        """JIP-appended pad has spot_index == None."""
        # Simulate: 2 segments totalling 800ms, block is 1000ms → 200ms gap → JIP pad
        segments = [
            {"segment_type": "content", "asset_uri": "show.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 500},
            {"segment_type": "filler", "asset_uri": "promo.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 300},
        ]
        result = _apply_jip_to_segments(segments, jip_offset_ms=0, block_dur_ms=1000)
        # Last segment should be the appended pad
        assert result[-1]["segment_type"] == "pad"
        assert result[-1].get("spot_index") is None

    @pytest.mark.skipif(not _HAS_JIP, reason="channel_manager not importable")
    def test_jip_extended_pad_preserves_none_spot_index(self):
        """JIP does not extend a traffic pad (spot_index != None); creates a new one."""
        # Segment list ends with a traffic pad (spot_index=2)
        segments = [
            {"segment_type": "content", "asset_uri": "show.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 500},
            {"segment_type": "filler", "asset_uri": "promo.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 200,
             "spot_index": 0},
            {"segment_type": "pad", "asset_uri": "",
             "asset_start_offset_ms": 0, "segment_duration_ms": 100,
             "spot_index": 0},
        ]
        # Block is 1000ms; segments total 800ms; JIP offset 0 → needs 200ms gap
        result = _apply_jip_to_segments(segments, jip_offset_ms=0, block_dur_ms=1000)
        # The traffic pad (spot_index=0) should remain unchanged
        traffic_pad = [s for s in result if s.get("spot_index") == 0 and s["segment_type"] == "pad"]
        assert len(traffic_pad) == 1
        assert traffic_pad[0]["segment_duration_ms"] == 100
        # A new JIP pad with spot_index=None should be appended
        jip_pad = result[-1]
        assert jip_pad["segment_type"] == "pad"
        assert jip_pad.get("spot_index") is None
        assert jip_pad["segment_duration_ms"] == 200

    def test_default_spot_index_is_none(self):
        """ScheduledSegment with no spot_index argument defaults to None."""
        seg = ScheduledSegment(
            segment_type="pad",
            asset_uri="",
            asset_start_offset_ms=0,
            segment_duration_ms=100,
        )
        assert seg.spot_index is None


# ===========================================================================
# No adjacent pad segments
# ===========================================================================


class TestNoAdjacentPads:
    """No two consecutive segments may both be pad."""

    def test_no_adjacent_pad_segments(self):
        """4 spots with gap: no pad-pad adjacency."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
            ("d.ts", "promo", 30_000),
        )
        result = _fill(130_000, lib)
        segs = result.segments
        for i in range(1, len(segs)):
            if segs[i].segment_type == "pad" and segs[i - 1].segment_type == "pad":
                pytest.fail(f"Adjacent pads at indices {i-1} and {i}")

    def test_no_adjacent_pad_structured_break(self):
        """Structured break with bumper degradation: no pad-pad adjacency."""
        bumper_config = BreakConfig(to_break_bumper_ms=5000, from_break_bumper_ms=5000)
        lib = _make_library(
            # No bumper assets available → both degrade to pool
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        result = _fill(
            60_000, lib,
            policy=_policy(allowed_types=["promo"]),
            break_config=bumper_config,
        )
        segs = result.segments
        for i in range(1, len(segs)):
            if segs[i].segment_type == "pad" and segs[i - 1].segment_type == "pad":
                pytest.fail(f"Adjacent pads at indices {i-1} and {i}")

    def test_no_adjacent_pad_single_spot_large_gap(self):
        """1 spot in a large break: only one asset fits, rest is pad."""
        # 25s asset in 30s break → 1 pick + 5s pad (no second pick fits the 5s remainder)
        lib = _make_library(("a.ts", "promo", 25_000))
        result = _fill(30_000, lib)
        filled = _non_content(result)
        assert len(filled) == 2  # 1 asset + 1 pad
        assert filled[0].segment_type != "pad"
        assert filled[1].segment_type == "pad"


# ===========================================================================
# INV-PAD-FRAME-DISTRIBUTION-001
# ===========================================================================


class TestPadFrameDistribution:
    """INV-PAD-FRAME-DISTRIBUTION-001: base = gap // N per spot,
    ALL remainder to final spot only."""

    def test_pad_distribution_frame_exactness(self):
        """gap = 5ms across 3 spots → [1, 1, 3]."""
        # 3 spots × 30s = 90s; break = 90005ms → gap = 5ms
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        result = _fill(90_005, lib)
        pads = _pads(result)
        assert len(pads) == 3
        pad_sizes = [p.segment_duration_ms for p in pads]
        assert pad_sizes == [1, 1, 3]

    def test_pad_distribution_no_remainder(self):
        """gap = 6ms across 3 spots → [2, 2, 2] (uniform)."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        result = _fill(90_006, lib)
        pads = _pads(result)
        pad_sizes = [p.segment_duration_ms for p in pads]
        assert pad_sizes == [2, 2, 2]

    def test_pad_distribution_remainder_all_to_final(self):
        """gap = 7ms across 4 spots → [1, 1, 1, 4]."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
            ("d.ts", "promo", 30_000),
        )
        result = _fill(120_007, lib)
        pads = _pads(result)
        assert len(pads) == 4
        pad_sizes = [p.segment_duration_ms for p in pads]
        assert pad_sizes == [1, 1, 1, 4]

    def test_no_fractional_padding(self):
        """All pad durations are int."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        result = _fill(92_000, lib)
        for p in _pads(result):
            assert isinstance(p.segment_duration_ms, int), (
                f"Pad duration is {type(p.segment_duration_ms).__name__}, not int"
            )

    def test_pad_distribution_single_spot_gets_all(self):
        """1 spot: entire gap goes to the single pad."""
        lib = _make_library(("a.ts", "promo", 30_000))
        result = _fill(35_000, lib)
        pads = _pads(result)
        assert len(pads) == 1
        assert pads[0].segment_duration_ms == 5000

    def test_pad_distribution_gap_smaller_than_spots(self):
        """gap = 2ms across 5 spots → [0, 0, 0, 0, 2]. Only final spot gets pad."""
        lib = _make_library(
            ("a.ts", "promo", 10_000),
            ("b.ts", "promo", 10_000),
            ("c.ts", "promo", 10_000),
            ("d.ts", "promo", 10_000),
            ("e.ts", "promo", 10_000),
        )
        result = _fill(50_002, lib)
        pads = _pads(result)
        # base = 0, remainder = 2 → only final spot gets a pad
        assert len(pads) == 1
        assert pads[0].segment_duration_ms == 2
        assert pads[0].spot_index == 4  # final spot


# ===========================================================================
# INV-PAD-PROTO-INVISIBLE-001
# ===========================================================================


@pytest.mark.skipif(not _HAS_PROTO, reason="Proto stubs not available")
class TestPadProtoInvisible:
    """INV-PAD-PROTO-INVISIBLE-001: spot_index does not appear in proto."""

    def _make_block_plan(self, segments: list[dict]) -> BlockPlan:
        return BlockPlan(
            block_id="blk-proto-test",
            channel_id=1,
            start_utc_ms=NOW_MS,
            end_utc_ms=NOW_MS + 120_000,
            segments=segments,
        )

    def test_pad_spot_index_not_in_proto(self):
        """Proto BlockSegment has no spot_index field."""
        segments = [
            {"segment_index": 0, "segment_type": "filler", "asset_uri": "promo.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 30_000, "spot_index": 0},
            {"segment_index": 1, "segment_type": "pad",
             "segment_duration_ms": 2000, "spot_index": 0},
            {"segment_index": 2, "segment_type": "filler", "asset_uri": "promo2.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 30_000, "spot_index": 1},
        ]
        bp = self._make_block_plan(segments)
        pb = bp.to_proto()
        for seg in pb.segments:
            assert not hasattr(seg, "spot_index") or not seg.HasField("spot_index"), (
                "Proto BlockSegment must not contain spot_index"
            )

    def test_proto_round_trip_preserves_segment_identity_without_spot_index(self):
        """Proto segments have correct index, type, uri, duration — no spot_index."""
        segments = [
            {"segment_index": 0, "segment_type": "filler", "asset_uri": "promo.ts",
             "asset_start_offset_ms": 0, "segment_duration_ms": 30_000, "spot_index": 0},
            {"segment_index": 1, "segment_type": "pad",
             "segment_duration_ms": 2000, "spot_index": 0},
        ]
        bp = self._make_block_plan(segments)
        pb = bp.to_proto()
        assert pb.segments[0].segment_index == 0
        assert pb.segments[0].asset_uri == "promo.ts"
        assert pb.segments[0].segment_duration_ms == 30_000
        assert pb.segments[1].segment_index == 1
        assert pb.segments[1].segment_duration_ms == 2000
        # Verify the serialized bytes don't contain "spot_index" string
        raw = pb.SerializeToString()
        assert b"spot_index" not in raw

    def test_pad_proto_type_is_segment_type_pad(self):
        """Pad segment with spot_index serializes as SEGMENT_TYPE_PAD (enum value 2)."""
        segments = [
            {"segment_index": 0, "segment_type": "pad",
             "segment_duration_ms": 1500, "spot_index": 2},
        ]
        bp = self._make_block_plan(segments)
        pb = bp.to_proto()
        # SEGMENT_TYPE_PAD = 2 in the proto enum
        assert pb.segments[0].segment_type == 2


# ===========================================================================
# INV-PAD-CONSERVATION-UNCHANGED-001
# ===========================================================================


class TestPadConservationUnchanged:
    """INV-PAD-CONSERVATION-UNCHANGED-001: spot_index metadata does not
    alter duration accounting."""

    def test_spot_index_does_not_change_conservation_sum(self):
        """Sum of segment durations == block duration after fill with spot_index."""
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        break_ms = 100_000
        result = _fill(break_ms, lib)
        total = sum(s.segment_duration_ms for s in result.segments)
        block_dur = result.end_utc_ms - result.start_utc_ms
        assert total == block_dur

    def test_tier2_trim_works_with_spot_index(self):
        """Tier 2 trim preserves spot_index on trimmed segment.

        Build a block where filler placeholder is slightly larger than content
        would need, forcing Tier 2 trim. Verify conservation holds and
        spot_index is preserved.
        """
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        # Use exact filler duration that matches available assets + gap
        result = _fill(62_000, lib)
        total = sum(s.segment_duration_ms for s in result.segments)
        block_dur = result.end_utc_ms - result.start_utc_ms
        assert total == block_dur
        # All pads should still have spot_index
        for p in _pads(result):
            assert p.spot_index is not None

    def test_block_frame_audit_unaffected(self):
        """Proto-level conservation: sum of segment_duration_ms in proto ==
        block duration, proving spot_index doesn't contaminate durations."""
        if not _HAS_PROTO:
            pytest.skip("Proto stubs not available")
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
        )
        result = _fill(62_000, lib)
        # Convert to BlockPlan and proto
        plan_segments = []
        for i, seg in enumerate(result.segments):
            d = {
                "segment_index": i,
                "segment_type": seg.segment_type,
                "asset_uri": seg.asset_uri,
                "asset_start_offset_ms": seg.asset_start_offset_ms,
                "segment_duration_ms": seg.segment_duration_ms,
                "spot_index": seg.spot_index,
            }
            plan_segments.append(d)
        bp = BlockPlan(
            block_id="blk-audit",
            channel_id=1,
            start_utc_ms=result.start_utc_ms,
            end_utc_ms=result.end_utc_ms,
            segments=plan_segments,
        )
        pb = bp.to_proto()
        proto_sum = sum(seg.segment_duration_ms for seg in pb.segments)
        block_dur = result.end_utc_ms - result.start_utc_ms
        assert proto_sum == block_dur


# ===========================================================================
# Integration: end-to-end traffic break with spot_index lifecycle
# ===========================================================================


class TestIntegrationTrafficBreakSpotIndexLifecycle:
    """Integration test: full break generation verifies all pad invariants simultaneously."""

    def test_integration_traffic_break_spot_index_lifecycle(self):
        """8-minute break with mixed assets — all invariants checked."""
        break_ms = 480_000  # 8 minutes
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("comm1.ts", "commercial", 60_000),
            ("psa1.ts", "filler", 15_000),
            ("promo2.ts", "promo", 30_000),
            ("comm2.ts", "commercial", 45_000),
        )
        result = _fill(break_ms, lib)

        segs = result.segments

        # --- Conservation ---
        total = sum(s.segment_duration_ms for s in segs)
        block_dur = result.end_utc_ms - result.start_utc_ms
        assert total == block_dur

        # --- Content/episode segments have spot_index == None ---
        for s in segs:
            if s.segment_type in ("content", "episode") or s.is_primary:
                assert s.spot_index is None

        # Collect non-content segments (the filled break)
        filled = [s for s in segs if s.spot_index is not None or s.segment_type == "pad"]

        # --- Spot affinity: pad.spot_index == predecessor.spot_index ---
        for i in range(len(segs)):
            if segs[i].segment_type == "pad":
                assert i > 0
                pred = segs[i - 1]
                assert segs[i].spot_index == pred.spot_index

        # --- No orphan pads ---
        for i in range(len(segs)):
            if segs[i].segment_type == "pad":
                pred = segs[i - 1]
                assert pred.spot_index is not None
                assert pred.segment_type not in ("content", "episode", "bumper")

        # --- Uniqueness ---
        spot_assets: Counter[int] = Counter()
        spot_pads: Counter[int] = Counter()
        for s in segs:
            if s.spot_index is None:
                continue
            if s.segment_type == "pad":
                spot_pads[s.spot_index] += 1
            else:
                spot_assets[s.spot_index] += 1
        for si in set(spot_assets) | set(spot_pads):
            assert spot_assets[si] == 1
            assert spot_pads[si] <= 1

        # --- Traffic origin ---
        for s in segs:
            if s.segment_type == "pad":
                assert s.spot_index is not None

        # --- No adjacent pads ---
        for i in range(1, len(segs)):
            assert not (segs[i].segment_type == "pad" and segs[i - 1].segment_type == "pad")

        # --- Contiguous spot_index ---
        indices = sorted({s.spot_index for s in segs if s.spot_index is not None})
        assert indices == list(range(len(indices)))

        # --- Proto invisible ---
        if _HAS_PROTO:
            plan_segments = []
            for i, seg in enumerate(segs):
                d = {
                    "segment_index": i,
                    "segment_type": seg.segment_type,
                    "asset_uri": seg.asset_uri,
                    "asset_start_offset_ms": seg.asset_start_offset_ms,
                    "segment_duration_ms": seg.segment_duration_ms,
                    "spot_index": seg.spot_index,
                }
                plan_segments.append(d)
            bp = BlockPlan(
                block_id="blk-integration",
                channel_id=1,
                start_utc_ms=result.start_utc_ms,
                end_utc_ms=result.end_utc_ms,
                segments=plan_segments,
            )
            pb = bp.to_proto()
            assert b"spot_index" not in pb.SerializeToString()
            proto_sum = sum(seg.segment_duration_ms for seg in pb.segments)
            assert proto_sum == block_dur
