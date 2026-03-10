"""
Contract tests: Traffic Manager — INV-TRAFFIC-FILL-*

Validates that the traffic manager correctly orchestrates break filling:
- BreakStructure integration (INV-TRAFFIC-FILL-STRUCTURED-001)
- Bumper degradation (INV-TRAFFIC-FILL-BUMPER-DEGRADE-001)
- Exact fill duration (INV-TRAFFIC-FILL-EXACT-001)
- Pad distribution (INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001)
- Fill order (INV-TRAFFIC-FILL-ORDER-001)
- No invented positions (INV-TRAFFIC-FILL-NO-INVENT-001)
- Rotation advances (INV-TRAFFIC-FILL-ROTATION-ADVANCES-001)
- Late-bind semantics (INV-TRAFFIC-FILL-LATE-BIND-001)
- Fallback filler (INV-TRAFFIC-FILL-FALLBACK-001)
- Budget compliance (INV-TRAFFIC-FILL-BUDGET-001)
- DSL-derived TrafficPolicy integration

Contract: docs/contracts/traffic_manager.md
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

try:
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    from retrovue.runtime.traffic_manager import fill_ad_blocks
    from retrovue.runtime.traffic_policy import (
        PlayRecord,
        TrafficCandidate,
        TrafficPolicy,
    )
    from retrovue.runtime.break_detection import BreakOpportunity, BreakPlan
    from retrovue.runtime.traffic_dsl import resolve_traffic_policy
    from retrovue.runtime.break_structure import BreakConfig
except ImportError:
    pytest.skip(
        "retrovue.runtime.traffic_manager or dependencies not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILLER_URI = "/media/filler/bars.ts"
FILLER_DURATION_MS = 30_000  # 30s filler file
NOW_MS = 10_000_000_000
DAY_START_MS = 9_900_000_000
GRID_DURATION_MS = 1_800_000  # 30-minute grid block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Build a ScheduledBlock with content + one empty filler placeholder."""
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
            asset_uri="",  # empty placeholder
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


def _block_with_multiple_fillers(
    filler_durations: list[int],
    block_id: str = "blk-multi",
) -> ScheduledBlock:
    """Build a block with content followed by multiple filler placeholders."""
    total_filler = sum(filler_durations)
    content_ms = GRID_DURATION_MS - total_filler
    segments = [
        ScheduledSegment(
            segment_type="episode",
            asset_uri="/media/shows/ep01.ts",
            asset_start_offset_ms=0,
            segment_duration_ms=content_ms,
            is_primary=True,
        ),
    ]
    for dur in filler_durations:
        segments.append(
            ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=dur,
            )
        )
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=NOW_MS,
        end_utc_ms=NOW_MS + GRID_DURATION_MS,
        segments=tuple(segments),
    )


@dataclass
class FakeFillerAsset:
    """Minimal filler asset returned by a fake asset library."""
    asset_uri: str
    asset_type: str
    duration_ms: int


class FakeAssetLibrary:
    """Fake asset library for testing traffic fill without a database."""

    def __init__(self, assets: list[FakeFillerAsset]) -> None:
        self._assets = assets

    def get_filler_assets(
        self, max_duration_ms: int = 0, count: int = 5,
    ) -> list[FakeFillerAsset]:
        eligible = [a for a in self._assets if a.duration_ms <= max_duration_ms]
        return eligible[:count]


def _make_library(*specs: tuple[str, str, int]) -> FakeAssetLibrary:
    """Build a FakeAssetLibrary from (uri, type, duration_ms) tuples."""
    return FakeAssetLibrary([
        FakeFillerAsset(asset_uri=uri, asset_type=atype, duration_ms=dur)
        for uri, atype, dur in specs
    ])


def _filled_segments(result: ScheduledBlock) -> list[ScheduledSegment]:
    """Extract non-primary segments from a filled block (ads + pads)."""
    return [s for s in result.segments if not s.is_primary and s.segment_type != "episode"]


def _ad_segments(result: ScheduledBlock) -> list[ScheduledSegment]:
    """Extract only the spot/asset segments (not pad, not primary content)."""
    return [
        s for s in result.segments
        if s.segment_type not in ("episode", "pad", "padding")
        and s.is_primary is False
    ]


# ===========================================================================
# INV-TRAFFIC-FILL-EXACT-001 — Break fill must produce exact duration
# ===========================================================================


class TestFillExactDuration:
    """INV-TRAFFIC-FILL-EXACT-001: Sum of filled segment durations must
    exactly equal the break's allocated duration."""

    # Tier: 2 | Scheduling logic invariant
    def test_fill_exact_duration(self):
        """Assets + pad sum to allocated break duration."""
        break_ms = 120_000  # 2 minutes
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("promo2.ts", "promo", 30_000),
            ("promo3.ts", "promo", 30_000),
            ("promo4.ts", "promo", 30_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_partial_fill_pad_exact(self):
        """Partial fill: assets + pad = allocated duration."""
        break_ms = 120_000
        # Only one 30s promo available — leaves 90s gap
        lib = _make_library(("promo1.ts", "promo", 30_000))
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_empty_fill_filler_exact(self):
        """No assets: filler loop fills break exactly."""
        break_ms = 90_000  # 1.5 minutes
        block = _block_with_filler(break_ms)
        # No asset library → static filler fallback
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms


# ===========================================================================
# INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001 — Even pad distribution
# ===========================================================================


class TestPadDistribution:
    """INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001: Leftover time distributed as
    even inter-spot pads. Remainder goes to last items."""

    # Tier: 2 | Scheduling logic invariant
    def test_pad_distributed_evenly(self):
        """3 spots with 2000ms gap → ~667ms pads between spots."""
        break_ms = 92_000  # 3×30s spots = 90s, 2000ms leftover
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        pads = [s for s in result.segments if s.segment_type == "pad"]
        assert len(pads) == 3  # one pad per spot
        # Even distribution: 2000 // 3 = 666, remainder 2
        pad_durations = [p.segment_duration_ms for p in pads]
        assert sum(pad_durations) == 2000
        # No single pad should differ from base by more than 1ms
        base = 2000 // 3
        for d in pad_durations:
            assert d in (base, base + 1)

    # Tier: 2 | Scheduling logic invariant
    def test_pad_remainder_to_last(self):
        """Indivisible gap: extra ms applied to last items first."""
        break_ms = 92_000
        lib = _make_library(
            ("a.ts", "promo", 30_000),
            ("b.ts", "promo", 30_000),
            ("c.ts", "promo", 30_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        pads = [s for s in result.segments if s.segment_type == "pad"]
        assert len(pads) == 3
        # 2000ms / 3 spots = 666 base, 2 remainder
        # Remainder goes to LAST items: pad[2]=667, pad[1]=667, pad[0]=666
        assert pads[0].segment_duration_ms == 666
        assert pads[1].segment_duration_ms == 667
        assert pads[2].segment_duration_ms == 667


# ===========================================================================
# INV-TRAFFIC-FILL-ORDER-001 — Opportunities filled in BreakPlan order
# ===========================================================================


class TestFillOrder:
    """INV-TRAFFIC-FILL-ORDER-001: Break opportunities processed in
    BreakPlan order, never reordered or skipped."""

    # Tier: 2 | Scheduling logic invariant
    def test_opportunities_filled_in_order(self):
        """Multi-break plan: fills processed in position_ms order."""
        # Create a block with two filler placeholders
        break_1_ms = 60_000
        break_2_ms = 60_000
        lib = _make_library(
            ("a.ts", "promo", 15_000),
            ("b.ts", "promo", 15_000),
            ("c.ts", "promo", 15_000),
            ("d.ts", "promo", 15_000),
        )
        block = _block_with_multiple_fillers([break_1_ms, break_2_ms])
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        # Content segment should still be first
        assert result.segments[0].segment_type == "episode"
        # Both filler placeholders must be replaced (no empty fillers remain)
        empty_fillers = [
            s for s in result.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(empty_fillers) == 0


# ===========================================================================
# INV-TRAFFIC-FILL-NO-INVENT-001 — No invented break positions
# ===========================================================================


class TestNoInventedBreaks:
    """INV-TRAFFIC-FILL-NO-INVENT-001: Traffic fill must only produce
    segments at positions defined by the existing filler placeholders."""

    # Tier: 2 | Scheduling logic invariant
    def test_no_invented_break_positions(self):
        """Filled segments only appear where filler placeholders existed."""
        break_ms = 60_000
        lib = _make_library(("a.ts", "promo", 30_000))
        block = _block_with_filler(break_ms)
        original_non_filler = [
            s for s in block.segments if s.segment_type != "filler"
        ]
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        # Primary content segments should be unchanged
        result_primary = [
            s for s in result.segments if s.segment_type == "episode"
        ]
        assert len(result_primary) == len(original_non_filler)
        for orig, filled in zip(original_non_filler, result_primary):
            assert orig.asset_uri == filled.asset_uri
            assert orig.segment_duration_ms == filled.segment_duration_ms

        # Total duration must equal original block duration
        orig_total = sum(s.segment_duration_ms for s in block.segments)
        result_total = sum(s.segment_duration_ms for s in result.segments)
        assert result_total == orig_total


# ===========================================================================
# INV-TRAFFIC-FILL-ROTATION-ADVANCES-001 — Rotation across breaks
# ===========================================================================


class TestRotationAdvances:
    """INV-TRAFFIC-FILL-ROTATION-ADVANCES-001: Asset selection advances
    across breaks within a block."""

    # Tier: 2 | Scheduling logic invariant
    def test_rotation_advances_across_breaks(self):
        """Different assets selected in consecutive breaks when multiple available."""
        break_1_ms = 30_000
        break_2_ms = 30_000
        # Two distinct promos, each exactly one break long
        lib = _make_library(
            ("promo_a.ts", "promo", 30_000),
            ("promo_b.ts", "promo", 30_000),
        )
        block = _block_with_multiple_fillers([break_1_ms, break_2_ms])
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads = _ad_segments(result)
        if len(ads) >= 2:
            # With rotation, the two breaks should get different assets
            assert ads[0].asset_uri != ads[1].asset_uri

    # Tier: 2 | Scheduling logic invariant
    def test_play_history_not_mutated(self):
        """Caller's original play_history list must not be modified."""
        break_ms = 30_000
        lib = _make_library(("promo.ts", "promo", 15_000))
        block = _block_with_filler(break_ms)
        original_history: list[PlayRecord] = [
            PlayRecord(asset_id="old.ts", asset_type="promo", played_at_ms=DAY_START_MS),
        ]
        history_copy = copy.deepcopy(original_history)

        fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=original_history,
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        assert original_history == history_copy


# ===========================================================================
# INV-TRAFFIC-FILL-LATE-BIND-001 — Traffic fill at feed time
# ===========================================================================


class TestLateBind:
    """INV-TRAFFIC-FILL-LATE-BIND-001: Schedule compiler produces empty
    filler placeholders. Traffic fill occurs at feed time."""

    # Tier: 2 | Scheduling logic invariant
    def test_late_bind_empty_placeholders(self):
        """Block arrives with empty filler placeholders (asset_uri='')."""
        block = _block_with_filler(60_000)
        # Verify the block has an empty filler placeholder
        fillers = [
            s for s in block.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(fillers) == 1
        assert fillers[0].segment_duration_ms == 60_000

    # Tier: 2 | Scheduling logic invariant
    def test_late_bind_fill_replaces_placeholder(self):
        """fill_ad_blocks replaces empty placeholders with concrete segments."""
        break_ms = 60_000
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        # No empty filler placeholders should remain
        empty = [
            s for s in result.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(empty) == 0
        # All filler segments must have a real URI
        fillers = [s for s in result.segments if s.segment_type == "filler"]
        for f in fillers:
            assert f.asset_uri != ""


# ===========================================================================
# INV-TRAFFIC-FILL-FALLBACK-001 — Fallback produces valid segments
# ===========================================================================


class TestFallback:
    """INV-TRAFFIC-FILL-FALLBACK-001: When no interstitials are available,
    fall back to static filler file. No error, exact duration."""

    # Tier: 2 | Scheduling logic invariant
    def test_fallback_fills_exactly(self):
        """No library: static filler fills break exactly."""
        break_ms = 90_000
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_fallback_wraps_filler(self):
        """Filler shorter than break: wraps and fills exactly."""
        break_ms = 75_000  # 2.5x the 30s filler
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        fillers = [s for s in result.segments if s.segment_type == "filler"]
        total = sum(s.segment_duration_ms for s in fillers)
        assert total == break_ms
        # Should have multiple filler segments (wrapping)
        assert len(fillers) >= 2
        # All filler segments reference the filler URI
        for f in fillers:
            assert f.asset_uri == FILLER_URI

    # Tier: 2 | Scheduling logic invariant
    def test_fallback_no_error(self):
        """No candidates: no exception, produces valid segments."""
        break_ms = 60_000
        # Empty library — all excluded
        lib = _make_library()  # no assets
        block = _block_with_filler(break_ms)
        # Must not raise
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_fallback_produces_valid_segments(self):
        """Fallback segments have valid segment_type and asset_uri."""
        break_ms = 45_000
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        for seg in result.segments:
            assert seg.segment_type in ("episode", "filler", "pad", "padding",
                                         "content", "promo", "commercial")
            assert seg.segment_duration_ms > 0


# ===========================================================================
# INV-TRAFFIC-FILL-BUDGET-001 — Total fill within budget
# ===========================================================================


class TestBudgetCompliance:
    """INV-TRAFFIC-FILL-BUDGET-001: Total filled duration across all breaks
    must not exceed break budget."""

    # Tier: 2 | Scheduling logic invariant
    def test_total_fill_within_budget(self):
        """Sum of all break allocations <= break_budget_ms."""
        break_budget = 120_000  # total budget across all breaks
        # Two breaks: 60s each = 120s total = exactly budget
        block = _block_with_multiple_fillers([60_000, 60_000])
        lib = _make_library(
            ("a.ts", "promo", 15_000),
            ("b.ts", "promo", 15_000),
        )
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        # Total filled must not exceed the original filler budget
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total <= break_budget
        assert total == break_budget  # exact match expected

    # Tier: 2 | Scheduling logic invariant
    def test_rounding_does_not_overshoot(self):
        """Weight rounding across 5 breaks stays within budget."""
        # 5 breaks of varying size, total = 150_000ms
        break_sizes = [33_000, 29_000, 31_000, 28_000, 29_000]
        total_budget = sum(break_sizes)  # 150_000
        block = _block_with_multiple_fillers(break_sizes)
        lib = _make_library(
            ("a.ts", "promo", 10_000),
            ("b.ts", "promo", 10_000),
        )
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total <= total_budget
        # Each break individually should be exact
        assert total == total_budget

    # Tier: 2 | Scheduling logic invariant
    def test_block_total_duration_preserved(self):
        """Total block duration (content + breaks) unchanged after fill."""
        break_ms = 90_000
        block = _block_with_filler(break_ms)
        orig_total = sum(s.segment_duration_ms for s in block.segments)

        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        result_total = sum(s.segment_duration_ms for s in result.segments)
        assert result_total == orig_total


# ===========================================================================
# DSL-derived TrafficPolicy integration
# ===========================================================================


def _cheers_channel_dsl(
    *,
    profiles: dict | None = None,
    default_profile: str = "default",
    schedule: dict | None = None,
) -> dict:
    """Build a channel DSL dict resembling cheers-24-7 with traffic config."""
    return {
        "channel": "cheers-24-7",
        "name": "Cheers 24/7",
        "channel_type": "network",
        "format": {"grid_minutes": 30},
        "pools": {"cheers": {"match": {"type": "episode", "series_title": "Cheers"}}},
        "programs": {
            "cheers_30": {"pool": "cheers", "grid_blocks": 1, "fill_mode": "single"},
        },
        "traffic": {
            "inventories": {
                "promos": {"match": {"type": "promo"}, "asset_type": "promo"},
                "station_ids": {"match": {"type": "station_id"}, "asset_type": "station_id"},
                "bumpers": {"match": {"type": "bumper"}, "asset_type": "bumper"},
            },
            "profiles": profiles or {
                "default": {
                    "allowed_types": ["promo", "station_id", "bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
            "default_profile": default_profile,
        },
        "schedule": schedule or {
            "all_day": [{"start": "06:00", "slots": 48, "program": "cheers_30"}],
        },
    }


class TestDslDerivedPolicy:
    """DSL-derived TrafficPolicy flows into fill_ad_blocks and affects
    asset selection via the policy's allowed_types filter."""

    # Tier: 2 | Scheduling logic invariant
    def test_dsl_policy_filters_by_allowed_types(self):
        """Policy from DSL restricts which asset types are selected."""
        # DSL allows only "promo" — commercials must be excluded
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
        )
        policy = resolve_traffic_policy(dsl, {"start": "06:00", "program": "cheers_30"})
        assert policy.allowed_types == ["promo"]

        break_ms = 60_000
        # Library has both promos and commercials
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("commercial1.ts", "commercial", 30_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads = _ad_segments(result)
        # Only promos should be selected, commercials excluded
        for ad in ads:
            assert ad.asset_uri.startswith("promo"), (
                f"Expected only promos, got {ad.asset_uri}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_default_profile_used_when_no_block_override(self):
        """Block without traffic_profile uses the channel default_profile."""
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo", "bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
        )
        # Block has no traffic_profile → uses "default" which only allows bumpers
        block_dict = {"start": "06:00", "program": "cheers_30"}
        policy = resolve_traffic_policy(dsl, block_dict)
        assert policy.allowed_types == ["bumper"]

        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("bumper1.ts", "bumper", 15_000),
        )
        block = _block_with_filler(60_000)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads = _ad_segments(result)
        # Only bumpers allowed by default profile
        for ad in ads:
            assert ad.asset_uri.startswith("bumper"), (
                f"Expected only bumpers from default profile, got {ad.asset_uri}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_block_override_changes_selection(self):
        """Block with traffic_profile override uses the override profile."""
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
        )
        # Block explicitly overrides to "primetime" which allows only promos
        block_dict = {
            "start": "20:00",
            "program": "cheers_30",
            "traffic_profile": "primetime",
        }
        policy = resolve_traffic_policy(dsl, block_dict)
        assert policy.allowed_types == ["promo"]

        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("bumper1.ts", "bumper", 15_000),
        )
        block = _block_with_filler(60_000)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads = _ad_segments(result)
        # Only promos allowed by primetime override
        for ad in ads:
            assert ad.asset_uri.startswith("promo"), (
                f"Expected only promos from primetime override, got {ad.asset_uri}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_no_traffic_section_uses_structural_defaults(self):
        """Channel without traffic section falls back to static filler."""
        dsl_no_traffic = {
            "channel": "simple-channel",
            "name": "Simple",
            "channel_type": "network",
            "format": {"grid_minutes": 30},
            "pools": {"shows": {"match": {"type": "episode"}}},
            "programs": {"show_30": {"pool": "shows", "grid_blocks": 1}},
            "schedule": {"all_day": [{"start": "06:00", "slots": 48, "program": "show_30"}]},
        }
        # No traffic section — fill_ad_blocks without policy falls back to filler
        block = _block_with_filler(60_000)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == 60_000
        # All segments should be static filler (no policy, no asset library)
        for seg in filled:
            assert seg.asset_uri == FILLER_URI

    # Tier: 2 | Scheduling logic invariant
    def test_dsl_policy_exact_fill_invariant_holds(self):
        """DSL-derived policy still satisfies INV-TRAFFIC-FILL-EXACT-001."""
        dsl = _cheers_channel_dsl()
        policy = resolve_traffic_policy(dsl, {"start": "06:00", "program": "cheers_30"})

        break_ms = 90_000
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("station1.ts", "station_id", 15_000),
            ("bumper1.ts", "bumper", 10_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms


# ===========================================================================
# Block-level traffic_profile on ScheduledBlock
# ===========================================================================


def _block_with_filler_and_profile(
    filler_duration_ms: int,
    traffic_profile: str | None = None,
    block_id: str = "blk-tp",
) -> ScheduledBlock:
    """Build a ScheduledBlock with content, filler, and traffic_profile."""
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
        traffic_profile=traffic_profile,
    )


class TestBlockLevelTrafficProfile:
    """Block-level traffic_profile override is preserved on ScheduledBlock
    and produces a different TrafficPolicy than the channel default."""

    # Tier: 2 | Scheduling logic invariant
    def test_scheduled_block_carries_traffic_profile(self):
        """ScheduledBlock.traffic_profile field is preserved."""
        block = _block_with_filler_and_profile(60_000, traffic_profile="primetime")
        assert block.traffic_profile == "primetime"

    # Tier: 2 | Scheduling logic invariant
    def test_scheduled_block_default_traffic_profile_is_none(self):
        """ScheduledBlock without override has traffic_profile=None."""
        block = _block_with_filler(60_000)
        assert block.traffic_profile is None

    # Tier: 2 | Scheduling logic invariant
    def test_override_produces_different_policy_than_default(self):
        """Block override resolves a different TrafficPolicy than default."""
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 12,
                },
            },
        )
        default_policy = resolve_traffic_policy(dsl, {})
        override_policy = resolve_traffic_policy(dsl, {"traffic_profile": "primetime"})

        assert default_policy.allowed_types == ["bumper"]
        assert override_policy.allowed_types == ["promo"]
        assert override_policy.max_plays_per_day == 12

    # Tier: 2 | Scheduling logic invariant
    def test_override_affects_asset_selection(self):
        """Block with traffic_profile override selects different assets."""
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["bumper"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
        )
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("bumper1.ts", "bumper", 15_000),
        )

        # Default profile: only bumpers
        default_policy = resolve_traffic_policy(dsl, {})
        block_default = _block_with_filler_and_profile(60_000, traffic_profile=None)
        result_default = fill_ad_blocks(
            block_default,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=default_policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads_default = _ad_segments(result_default)
        for ad in ads_default:
            assert ad.asset_uri.startswith("bumper")

        # Override profile: only promos
        override_policy = resolve_traffic_policy(dsl, {"traffic_profile": "primetime"})
        block_override = _block_with_filler_and_profile(60_000, traffic_profile="primetime")
        result_override = fill_ad_blocks(
            block_override,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=override_policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads_override = _ad_segments(result_override)
        for ad in ads_override:
            assert ad.asset_uri.startswith("promo")

    # Tier: 2 | Scheduling logic invariant
    def test_fill_preserves_traffic_profile_on_result(self):
        """fill_ad_blocks preserves traffic_profile on the returned block."""
        block = _block_with_filler_and_profile(60_000, traffic_profile="primetime")
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )
        assert result.traffic_profile == "primetime"

    # Tier: 2 | Scheduling logic invariant
    def test_no_override_uses_default(self):
        """Block without traffic_profile uses channel default_profile."""
        dsl = _cheers_channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["station_id"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo"],
                    "default_cooldown_seconds": 0,
                    "max_plays_per_day": 0,
                },
            },
        )
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("station1.ts", "station_id", 15_000),
        )

        # No override → default profile → only station_id allowed
        default_policy = resolve_traffic_policy(dsl, {})
        block = _block_with_filler_and_profile(60_000, traffic_profile=None)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=default_policy,
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        ads = _ad_segments(result)
        for ad in ads:
            assert ad.asset_uri.startswith("station")


# ===========================================================================
# INV-TRAFFIC-FILL-STRUCTURED-001 — BreakStructure integration
# ===========================================================================


class TestStructuredFill:
    """INV-TRAFFIC-FILL-STRUCTURED-001: Filler placeholders are expanded
    through BreakStructure before filling."""

    # Tier: 2 | Scheduling logic invariant
    def test_structured_fill_produces_bumper_then_spots(self):
        """With bumper config and bumper assets, output begins with bumper."""
        break_ms = 60_000
        bumper_config = BreakConfig(to_break_bumper_ms=3000, from_break_bumper_ms=3000)
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
            ("promo4.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        assert len(filled) > 0
        # First non-primary segment should be a bumper
        assert filled[0].asset_uri.startswith("bumper")
        assert filled[0].segment_type == "bumper"
        # Last non-pad segment should be a bumper (from_break)
        non_pad = [s for s in filled if s.segment_type != "pad"]
        assert non_pad[-1].asset_uri.startswith("bumper")
        assert non_pad[-1].segment_type == "bumper"
        # Total duration must still be exact
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_structured_fill_interstitial_pool_only(self):
        """Without bumper config, output is interstitial spots only (no bumpers)."""
        break_ms = 60_000
        bare_config = BreakConfig(to_break_bumper_ms=0, from_break_bumper_ms=0)
        lib = _make_library(
            ("promo1.ts", "promo", 30_000),
            ("promo2.ts", "promo", 30_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bare_config,
        )
        filled = _filled_segments(result)
        # No bumper segments should appear
        bumpers = [s for s in filled if s.segment_type == "bumper"]
        assert len(bumpers) == 0
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_structured_fill_slot_order_preserved(self):
        """Output segment order matches BreakStructure: bumper → spots → bumper."""
        break_ms = 60_000
        bumper_config = BreakConfig(to_break_bumper_ms=3000, from_break_bumper_ms=3000)
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        non_pad = [s for s in filled if s.segment_type != "pad"]
        # First = to_break bumper, middle = interstitial spots, last = from_break bumper
        assert non_pad[0].segment_type == "bumper"
        assert non_pad[-1].segment_type == "bumper"
        for s in non_pad[1:-1]:
            assert s.segment_type != "bumper"

    # Tier: 2 | Scheduling logic invariant
    def test_no_break_config_backward_compatible(self):
        """Without break_config parameter, fill_ad_blocks works as before."""
        break_ms = 60_000
        lib = _make_library(("promo1.ts", "promo", 30_000))
        block = _block_with_filler(break_ms)
        # No break_config — backward compatible
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms


# ===========================================================================
# INV-TRAFFIC-FILL-BUMPER-DEGRADE-001 — Bumper degradation
# ===========================================================================


class TestBumperDegrade:
    """INV-TRAFFIC-FILL-BUMPER-DEGRADE-001: Unfilled bumper slots degrade
    to interstitial pool. Budget is conserved."""

    # Tier: 2 | Scheduling logic invariant
    def test_bumper_degrade_merges_to_pool(self):
        """No bumper available: bumper duration added to interstitial pool."""
        break_ms = 60_000
        bumper_config = BreakConfig(to_break_bumper_ms=3000, from_break_bumper_ms=3000)
        # Library has NO bumper assets — only promos
        lib = _make_library(
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
            ("promo4.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        # No bumper segments
        bumpers = [s for s in filled if s.segment_type == "bumper"]
        assert len(bumpers) == 0
        # Total still exact — bumper budget merged into interstitial pool
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_bumper_degrade_budget_conserved(self):
        """Total duration unchanged when bumper degrades."""
        break_ms = 90_000
        bumper_config = BreakConfig(to_break_bumper_ms=5000, from_break_bumper_ms=5000)
        # No bumpers in library
        lib = _make_library(("promo1.ts", "promo", 30_000))
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_partial_bumper_degrade(self):
        """One bumper available, one not — partial degradation."""
        break_ms = 60_000
        bumper_config = BreakConfig(to_break_bumper_ms=3000, from_break_bumper_ms=3000)
        # Only one bumper (3s) — second bumper slot degrades
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        bumpers = [s for s in filled if s.segment_type == "bumper"]
        # At least one bumper was placed (to_break), from_break degraded
        assert len(bumpers) >= 1
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms


# ===========================================================================
# INV-TRAFFIC-FILL-STRUCTURED-001 — Station ID structural fill
# ===========================================================================


class TestStationIdStructuredFill:
    """Station ID slots are filled by dedicated selection, not traffic policy."""

    # Tier: 2 | Scheduling logic invariant
    def test_station_id_slot_filled(self):
        """With station_id config and assets, station_id segment appears."""
        break_ms = 60_000
        config = BreakConfig(
            to_break_bumper_ms=3000,
            from_break_bumper_ms=3000,
            station_id_ms=5000,
        )
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("sid.ts", "station_id", 5000),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=config,
        )
        filled = _filled_segments(result)
        sid_segs = [s for s in filled if s.segment_type == "station_id"]
        assert len(sid_segs) == 1
        assert sid_segs[0].asset_uri == "sid.ts"
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_station_id_position_after_interstitial(self):
        """Station ID appears after interstitial content, before from_break bumper."""
        break_ms = 60_000
        config = BreakConfig(
            to_break_bumper_ms=3000,
            from_break_bumper_ms=3000,
            station_id_ms=5000,
        )
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("sid.ts", "station_id", 5000),
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=config,
        )
        filled = _filled_segments(result)
        non_pad = [s for s in filled if s.segment_type != "pad"]
        # Order: bumper → interstitial spots → station_id → bumper
        assert non_pad[0].segment_type == "bumper"
        assert non_pad[-1].segment_type == "bumper"
        # Station ID should be second-to-last non-pad segment
        sid_idx = next(i for i, s in enumerate(non_pad) if s.segment_type == "station_id")
        assert sid_idx > 0  # not first
        assert sid_idx < len(non_pad) - 1  # not last (from_break bumper is last)

    # Tier: 2 | Scheduling logic invariant
    def test_station_id_degrade_no_asset(self):
        """No station_id asset available: duration merges into interstitial pool."""
        break_ms = 60_000
        config = BreakConfig(
            to_break_bumper_ms=3000,
            from_break_bumper_ms=3000,
            station_id_ms=5000,
        )
        # No station_id in library
        lib = _make_library(
            ("bumper_in.ts", "bumper", 3000),
            ("bumper_out.ts", "bumper", 3000),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=config,
        )
        filled = _filled_segments(result)
        # No station_id segments
        sid_segs = [s for s in filled if s.segment_type == "station_id"]
        assert len(sid_segs) == 0
        # Budget conserved — station_id duration merged into pool
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms

    # Tier: 2 | Scheduling logic invariant
    def test_station_id_not_in_traffic_policy(self):
        """Station ID selection bypasses traffic policy engine."""
        break_ms = 60_000
        config = BreakConfig(
            to_break_bumper_ms=0,
            from_break_bumper_ms=0,
            station_id_ms=5000,
        )
        # Policy does NOT include station_id in allowed_types
        lib = _make_library(
            ("sid.ts", "station_id", 5000),
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=config,
        )
        filled = _filled_segments(result)
        # Station ID still appears despite not being in allowed_types
        sid_segs = [s for s in filled if s.segment_type == "station_id"]
        assert len(sid_segs) == 1
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms


class TestStructuralSlotShortfall:
    """INV-TRAFFIC-FILL-EXACT-001: When a bumper or station_id asset is
    shorter than its allocated slot, the shortfall degrades into the
    interstitial pool so the total break duration remains exact."""

    # Tier: 2 | Scheduling logic invariant
    def test_undersized_bumper_shortfall_degrades_to_pool(self):
        """Bumper asset shorter than slot → shortfall fills with interstitials."""
        break_ms = 60_000
        # Slots: 5000ms to_break + 5000ms from_break = 10000ms structural
        bumper_config = BreakConfig(to_break_bumper_ms=5000, from_break_bumper_ms=5000)
        # Bumpers are only 4608ms — 392ms shortfall each, 784ms total
        lib = _make_library(
            ("bumper_in.ts", "bumper", 4608),
            ("bumper_out.ts", "bumper", 4608),
            ("promo1.ts", "promo", 15_000),
            ("promo2.ts", "promo", 15_000),
            ("promo3.ts", "promo", 15_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo", "bumper"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=bumper_config,
        )
        filled = _filled_segments(result)
        # Total must exactly match break budget
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms, (
            f"INV-TRAFFIC-FILL-EXACT-001: {total}ms != {break_ms}ms"
        )
        # Bumpers should be present at their actual (shorter) duration
        bumpers = [s for s in filled if s.segment_type == "bumper"]
        assert len(bumpers) == 2
        assert all(b.segment_duration_ms == 4608 for b in bumpers)

    # Tier: 2 | Scheduling logic invariant
    def test_undersized_station_id_shortfall_degrades_to_pool(self):
        """Station ID asset shorter than slot → shortfall fills with interstitials."""
        break_ms = 60_000
        config = BreakConfig(station_id_ms=5000)
        # Station ID is only 3500ms — 1500ms shortfall
        lib = _make_library(
            ("sid.ts", "station_id", 3500),
            ("promo1.ts", "promo", 20_000),
            ("promo2.ts", "promo", 20_000),
        )
        block = _block_with_filler(break_ms)
        result = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
            asset_library=lib,
            policy=_policy(allowed_types=["promo"]),
            play_history=[],
            now_ms=NOW_MS,
            day_start_ms=DAY_START_MS,
            break_config=config,
        )
        filled = _filled_segments(result)
        total = sum(s.segment_duration_ms for s in filled)
        assert total == break_ms, (
            f"INV-TRAFFIC-FILL-EXACT-001: {total}ms != {break_ms}ms"
        )
