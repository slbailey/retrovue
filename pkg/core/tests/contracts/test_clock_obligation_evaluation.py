"""Contract tests for Clock Obligation Evaluation (Second Compilation Pass).

Validates INV-CLOCK-OBLIGATIONS-OVERRIDE-001 defined in:
    docs/contracts/block_assembly_tiers.md

Derived From: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-CLOCK

The second compilation pass evaluates clock-scoped obligations against
absolute wall-clock time and inserts obligation segments into the
compiled_segments of each affected block.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

try:
    from retrovue.runtime.clock_obligations import (
        ClockObligation,
        evaluate_clock_obligations,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime.clock_obligations not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 1_800_000
EPISODE_22_MIN_MS = 1_320_000

# Block at 20:00–20:30 UTC on 2026-03-27
BLOCK_START = datetime(2026, 3, 27, 20, 0, 0, tzinfo=timezone.utc)
BLOCK_END = datetime(2026, 3, 27, 20, 30, 0, tzinfo=timezone.utc)
BLOCK_START_MS = int(BLOCK_START.timestamp() * 1000)
BLOCK_END_MS = int(BLOCK_END.timestamp() * 1000)

# Block spanning top-of-hour: 20:45–21:15 UTC
SPANNING_BLOCK_START = datetime(2026, 3, 27, 20, 45, 0, tzinfo=timezone.utc)
SPANNING_BLOCK_END = datetime(2026, 3, 27, 21, 15, 0, tzinfo=timezone.utc)
SPANNING_BLOCK_START_MS = int(SPANNING_BLOCK_START.timestamp() * 1000)

STATION_ID_DURATION_MS = 10_000  # 10s station ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _station_id_obligation(
    *,
    interval_minutes: int = 60,
    duration_ms: int = STATION_ID_DURATION_MS,
    mandatory: bool = True,
    pool: str = "station_ids",
) -> ClockObligation:
    """Create a station_id clock obligation."""
    return ClockObligation(
        type="station_id",
        interval_minutes=interval_minutes,
        trigger_times=None,
        pool=pool,
        duration_ms=duration_ms,
        mandatory=mandatory,
    )


def _daypart_obligation(
    *,
    trigger_times: list[str],
    duration_ms: int = 60_000,
    mandatory: bool = True,
    pool: str = "daypart_intros",
) -> ClockObligation:
    """Create a daypart_transition clock obligation."""
    return ClockObligation(
        type="daypart_transition",
        interval_minutes=None,
        trigger_times=trigger_times,
        pool=pool,
        duration_ms=duration_ms,
        mandatory=mandatory,
    )


def _make_compiled_segments(
    *,
    content_duration_ms: int = EPISODE_22_MIN_MS,
    filler_ms: int = 480_000,
    has_midroll_break: bool = True,
    midroll_position_ms: int = 660_000,
    midroll_filler_ms: int = 240_000,
) -> list[dict]:
    """Build a representative compiled_segments list for testing.

    Default: 22-min episode in 30-min slot with midroll break at ~11min.
    """
    segments = []

    if has_midroll_break:
        # Content act 1
        segments.append({
            "segment_type": "content",
            "asset_id": "ep001",
            "duration_ms": midroll_position_ms,
            "asset_start_offset_ms": 0,
        })
        # Midroll filler
        segments.append({
            "segment_type": "filler",
            "asset_id": "",
            "duration_ms": midroll_filler_ms,
        })
        # Content act 2
        act2_ms = content_duration_ms - midroll_position_ms
        segments.append({
            "segment_type": "content",
            "asset_id": "ep001",
            "duration_ms": act2_ms,
            "asset_start_offset_ms": midroll_position_ms,
        })
        # Trailing filler
        trailing = filler_ms - midroll_filler_ms
        if trailing > 0:
            segments.append({
                "segment_type": "filler",
                "asset_id": "",
                "duration_ms": trailing,
            })
    else:
        segments.append({
            "segment_type": "content",
            "asset_id": "ep001",
            "duration_ms": content_duration_ms,
            "asset_start_offset_ms": 0,
        })
        if filler_ms > 0:
            segments.append({
                "segment_type": "filler",
                "asset_id": "",
                "duration_ms": filler_ms,
            })

    return segments


def _make_block(
    *,
    start_utc: datetime = SPANNING_BLOCK_START,
    slot_duration_ms: int = GRID_30_MIN_MS,
    compiled_segments: list[dict] | None = None,
) -> dict:
    """Build a block dict for the second pass."""
    if compiled_segments is None:
        compiled_segments = _make_compiled_segments()
    return {
        "start_utc_ms": int(start_utc.timestamp() * 1000),
        "slot_duration_ms": slot_duration_ms,
        "compiled_segments": compiled_segments,
    }


# ---------------------------------------------------------------------------
# CLOCK-OBL-001: Trigger within a break
# ---------------------------------------------------------------------------


class TestObligationInBreak:
    """CLOCK-OBL-001: Obligation trigger within a break inserts into break
    and reduces fill budget.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_obligation_inserted_into_break(self):
        """Station ID at top-of-hour, block spans 20:45-21:15.
        The 21:00 trigger falls within the midroll break.
        Obligation segment inserted; filler reduced by obligation duration.
        """
        block = _make_block(
            start_utc=SPANNING_BLOCK_START,
            compiled_segments=_make_compiled_segments(
                midroll_position_ms=660_000,  # break at ~11min = 20:56
                midroll_filler_ms=300_000,    # 5min filler = 20:56-21:01
            ),
        )

        obligations = [_station_id_obligation(interval_minutes=60)]

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        # Find obligation segment in result
        result_segs = result[0]["compiled_segments"]
        obl_segs = [s for s in result_segs if s["segment_type"] == "obligation"]
        assert len(obl_segs) == 1
        assert obl_segs[0]["duration_ms"] == STATION_ID_DURATION_MS
        assert obl_segs[0]["obligation_type"] == "station_id"

        # Filler should be reduced by obligation duration
        filler_total = sum(
            s["duration_ms"] for s in result_segs if s["segment_type"] == "filler"
        )
        original_filler = 300_000 + (GRID_30_MIN_MS - EPISODE_22_MIN_MS - 300_000)
        assert filler_total == original_filler - STATION_ID_DURATION_MS


# ---------------------------------------------------------------------------
# CLOCK-OBL-002: Trigger within primary content
# ---------------------------------------------------------------------------


class TestObligationInContent:
    """CLOCK-OBL-002: Obligation trigger within primary content inserts
    micro-break at nearest safe point.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_micro_break_at_safe_point(self):
        """Station ID at 21:00, block 20:45-21:15, no break near 21:00.
        Content runs from 20:45. At minute 15 (21:00), trigger within content.
        Micro-break inserted; content NOT cut or shifted.
        """
        # No midroll break — content spans the full trigger time
        block = _make_block(
            start_utc=SPANNING_BLOCK_START,
            compiled_segments=_make_compiled_segments(
                has_midroll_break=False,
                content_duration_ms=EPISODE_22_MIN_MS,
                filler_ms=GRID_30_MIN_MS - EPISODE_22_MIN_MS,
            ),
        )

        obligations = [_station_id_obligation(interval_minutes=60)]

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        result_segs = result[0]["compiled_segments"]
        obl_segs = [s for s in result_segs if s["segment_type"] == "obligation"]
        assert len(obl_segs) == 1

        # Content total must be preserved (no cutting or shifting)
        content_total = sum(
            s["duration_ms"] for s in result_segs if s["segment_type"] == "content"
        )
        assert content_total == EPISODE_22_MIN_MS


# ---------------------------------------------------------------------------
# CLOCK-OBL-005: Trigger at block boundary
# ---------------------------------------------------------------------------


class TestObligationAtBoundary:
    """CLOCK-OBL-005: Obligation trigger at block boundary prepends before
    Tier 1 presentation.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_obligation_prepended_at_block_head(self):
        """Block starts exactly at top-of-hour (21:00). The obligation
        should appear as the first segment, before any presentation.
        """
        block_start = datetime(2026, 3, 27, 21, 0, 0, tzinfo=timezone.utc)
        segs = [
            {"segment_type": "presentation", "asset_id": "intro01", "duration_ms": 5_000},
        ] + _make_compiled_segments(has_midroll_break=False)

        block = _make_block(
            start_utc=block_start,
            compiled_segments=segs,
        )

        obligations = [_station_id_obligation(interval_minutes=60)]

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        result_segs = result[0]["compiled_segments"]
        # First segment must be the obligation
        assert result_segs[0]["segment_type"] == "obligation"
        assert result_segs[0]["obligation_type"] == "station_id"


# ---------------------------------------------------------------------------
# CLOCK-OBL-006: Mandatory cannot be suppressed
# ---------------------------------------------------------------------------


class TestMandatoryObligation:
    """CLOCK-OBL-006: Mandatory obligation cannot be suppressed by template
    configuration.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_mandatory_obligation_always_honored(self):
        """Even with template opt-out, mandatory obligations are inserted."""
        block = _make_block(start_utc=SPANNING_BLOCK_START)

        obligations = [_station_id_obligation(mandatory=True)]

        # Template declares opt-out from station_id
        template_participation = {"station_id": False}

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
            template_participation=template_participation,
        )

        result_segs = result[0]["compiled_segments"]
        obl_segs = [s for s in result_segs if s["segment_type"] == "obligation"]
        # Mandatory = always honored regardless of template
        assert len(obl_segs) == 1


# ---------------------------------------------------------------------------
# CLOCK-OBL-007: Multiple obligations at same trigger time
# ---------------------------------------------------------------------------


class TestMultipleObligations:
    """CLOCK-OBL-007: Multiple obligations at same trigger time stack in
    YAML declaration order.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_stacked_in_declaration_order(self):
        """Two obligations trigger at 21:00: station_id then legal_id.
        Both appear in that order.
        """
        block = _make_block(start_utc=SPANNING_BLOCK_START)

        obligations = [
            _station_id_obligation(interval_minutes=60),
            ClockObligation(
                type="legal_id",
                interval_minutes=60,
                trigger_times=None,
                pool="legal_ids",
                duration_ms=15_000,
                mandatory=True,
            ),
        ]

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        result_segs = result[0]["compiled_segments"]
        obl_segs = [s for s in result_segs if s["segment_type"] == "obligation"]
        assert len(obl_segs) == 2
        # Declaration order preserved
        assert obl_segs[0]["obligation_type"] == "station_id"
        assert obl_segs[1]["obligation_type"] == "legal_id"


# ---------------------------------------------------------------------------
# CLOCK-OBL-008: Never cuts, truncates, or shifts primary content
# ---------------------------------------------------------------------------


class TestContentPreservation:
    """CLOCK-OBL-008: Obligation insertion never cuts, truncates, or shifts
    primary content.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_content_duration_preserved(self):
        """After obligation insertion, total content duration is unchanged."""
        block = _make_block(start_utc=SPANNING_BLOCK_START)
        original_content_ms = sum(
            s["duration_ms"]
            for s in block["compiled_segments"]
            if s["segment_type"] == "content"
        )

        obligations = [_station_id_obligation(interval_minutes=60)]

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        result_content_ms = sum(
            s["duration_ms"]
            for s in result[0]["compiled_segments"]
            if s["segment_type"] == "content"
        )
        assert result_content_ms == original_content_ms


# ---------------------------------------------------------------------------
# CLOCK-OBL-009: Deterministic — same inputs produce same output
# ---------------------------------------------------------------------------


class TestDeterminism:
    """CLOCK-OBL-009: Same config + block boundaries produce identical
    obligation placements across compilations.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001
    """

    def test_deterministic_placement(self):
        """Running the same input twice yields identical output."""
        block = _make_block(start_utc=SPANNING_BLOCK_START)
        obligations = [_station_id_obligation(interval_minutes=60)]

        result1 = evaluate_clock_obligations(
            blocks=[block],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )
        # Deep-copy block for second run
        import copy
        block2 = copy.deepcopy(_make_block(start_utc=SPANNING_BLOCK_START))
        result2 = evaluate_clock_obligations(
            blocks=[block2],
            obligations=obligations,
            broadcast_day="2026-03-27",
        )

        assert result1[0]["compiled_segments"] == result2[0]["compiled_segments"]


# ---------------------------------------------------------------------------
# Backward compatibility: no obligations → no changes
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Channels without clock obligations → no second pass, same output."""

    def test_no_obligations_no_changes(self):
        """Empty obligations list returns blocks unchanged."""
        block = _make_block(start_utc=SPANNING_BLOCK_START)
        original_segs = list(block["compiled_segments"])

        result = evaluate_clock_obligations(
            blocks=[block],
            obligations=[],
            broadcast_day="2026-03-27",
        )

        assert result[0]["compiled_segments"] == original_segs
