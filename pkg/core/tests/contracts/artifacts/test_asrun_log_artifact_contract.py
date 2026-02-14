"""
Contract Tests — AsRunLogArtifactContract v0.2

Tests assert artifact invariants from
docs/contracts/artifacts/AsRunLogArtifactContract.md (v0.2).

Uses synthetic in-memory data and the asrun_artifact_validator module.
No database required — pure artifact format validation.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asrun_artifact_validator import (
    AsRunArtifactError,
    validate_aired_includes_segment_index,
    validate_broadcast_day_time_format,
    validate_fence_absolute_ticks,
    validate_fence_no_zero_ticks,
    validate_no_scheduled_fields_in_text,
    validate_no_zero_frame_terminal,
    validate_seg_start_requires_terminal,
    validate_single_terminal_event,
)


def _row(
    actual="09:00:00",
    dur="00:22:30",
    status="AIRED",
    type_="PROGRAM",
    event_id="EVT-0001",
    notes="ontime=Y fallback=0 frames=675",
):
    return {
        "actual": actual,
        "dur": dur,
        "status": status,
        "type": type_,
        "event_id": event_id,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# AR-ART-008 — Single Terminal Event
# ---------------------------------------------------------------------------


class TestSingleTerminalEvent:
    """AR-ART-008: Each non-BLOCK EVENT_ID must have exactly one terminal status."""

    def test_double_terminal_raises(self):
        """Double terminal emission for the same EVENT_ID must be rejected."""
        rows = [
            _row(status="SEG_START", dur="00:00:00", notes="(segment begin)"),
            _row(status="AIRED", notes="ontime=Y fallback=0 frames=675"),
            _row(status="TRUNCATED", notes="truncated_by_fence=Y frames=100"),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-008"):
            validate_single_terminal_event(rows)

    def test_single_terminal_passes(self):
        rows = [
            _row(status="SEG_START", dur="00:00:00", notes="(segment begin)"),
            _row(status="AIRED", notes="ontime=Y fallback=0 frames=675"),
        ]
        validate_single_terminal_event(rows)

    def test_multiple_events_each_single_terminal_passes(self):
        rows = [
            _row(status="SEG_START", dur="00:00:00", event_id="EVT-0001", notes="(segment begin)"),
            _row(status="AIRED", event_id="EVT-0001", notes="ontime=Y fallback=0 frames=675"),
            _row(status="SEG_START", dur="00:00:00", event_id="EVT-0002", notes="(segment begin)"),
            _row(status="AIRED", event_id="EVT-0002", notes="ontime=Y fallback=0 frames=30"),
        ]
        validate_single_terminal_event(rows)


# ---------------------------------------------------------------------------
# AR-ART-008 — No Zero-Frame Terminal
# ---------------------------------------------------------------------------


class TestNoZeroFrameTerminal:
    """AR-ART-008: AIRED with frames=0 must fail validation."""

    def test_aired_zero_frames_raises(self):
        rows = [
            _row(status="AIRED", notes="ontime=Y fallback=0 frames=0"),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-008.*frames=0"):
            validate_no_zero_frame_terminal(rows)

    def test_truncated_zero_frames_raises(self):
        rows = [
            _row(status="TRUNCATED", notes="truncated_by_fence=Y frames=0"),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-008.*frames=0"):
            validate_no_zero_frame_terminal(rows)

    def test_aired_positive_frames_passes(self):
        rows = [
            _row(status="AIRED", notes="ontime=Y fallback=0 frames=675"),
        ]
        validate_no_zero_frame_terminal(rows)


# ---------------------------------------------------------------------------
# SEG_START Requires Terminal
# ---------------------------------------------------------------------------


class TestSegStartRequiresTerminal:
    """SEG_START without terminal status must fail validation."""

    def test_seg_start_without_terminal_raises(self):
        rows = [
            _row(status="SEG_START", dur="00:00:00", notes="(segment begin)"),
        ]
        with pytest.raises(AsRunArtifactError, match="SEG_START without terminal"):
            validate_seg_start_requires_terminal(rows)

    def test_seg_start_with_terminal_passes(self):
        rows = [
            _row(status="SEG_START", dur="00:00:00", notes="(segment begin)"),
            _row(status="AIRED", notes="ontime=Y fallback=0 frames=675"),
        ]
        validate_seg_start_requires_terminal(rows)


# ---------------------------------------------------------------------------
# AR-ART-003 v0.2 — Fence Contains Absolute Ticks
# ---------------------------------------------------------------------------


class TestFenceContainsAbsoluteTicks:
    """AR-ART-003 v0.2: swap_tick and fence_tick must be > 0 and equal.
    frame_budget_remaining must equal 0."""

    def test_valid_fence_passes(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes=(
                    "swap_tick=10800 fence_tick=10800 frames_emitted=10800 "
                    "frame_budget_remaining=0 primed_success=Y "
                    "truncated_by_fence=N early_exhaustion=N"
                ),
            ),
        ]
        validate_fence_absolute_ticks(rows)

    def test_swap_not_equal_fence_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=900 fence_tick=10800 frame_budget_remaining=0",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match=r"AR-ART-003.*swap_tick.*!=.*fence_tick"):
            validate_fence_absolute_ticks(rows)

    def test_budget_nonzero_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=10800 fence_tick=10800 frame_budget_remaining=42",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-003.*frame_budget_remaining"):
            validate_fence_absolute_ticks(rows)

    def test_zero_swap_tick_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=0 fence_tick=0 frame_budget_remaining=0",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match=r"AR-ART-003.*swap_tick.*must be > 0"):
            validate_fence_absolute_ticks(rows)

    def test_missing_frame_budget_remaining_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=10800 fence_tick=10800",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-003.*missing frame_budget_remaining"):
            validate_fence_absolute_ticks(rows)

    def test_fence_both_ticks_absent_passes(self):
        """v0.2: When zero ticks are omitted, both absent is valid."""
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes=(
                    "frames_emitted=10800 frame_budget_remaining=0 "
                    "reason=FENCE primed_success=Y "
                    "truncated_by_fence=N early_exhaustion=N"
                ),
            ),
        ]
        validate_fence_absolute_ticks(rows)

    def test_fence_one_tick_present_other_absent_raises(self):
        """If swap_tick is present, fence_tick must also be present."""
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=10800 frame_budget_remaining=0",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="AR-ART-003.*swap_tick present but fence_tick missing"):
            validate_fence_absolute_ticks(rows)


# ---------------------------------------------------------------------------
# FENCE No Zero Ticks
# ---------------------------------------------------------------------------


class TestFenceNoZeroTicks:
    """FENCE must not contain swap_tick=0 or fence_tick=0."""

    def test_swap_tick_zero_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=0 fence_tick=0 frame_budget_remaining=0",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="FENCE contains swap_tick=0"):
            validate_fence_no_zero_ticks(rows)

    def test_fence_tick_zero_raises(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=10800 fence_tick=0 frame_budget_remaining=0",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="FENCE contains fence_tick=0"):
            validate_fence_no_zero_ticks(rows)

    def test_positive_ticks_passes(self):
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="swap_tick=10800 fence_tick=10800 frame_budget_remaining=0",
            ),
        ]
        validate_fence_no_zero_ticks(rows)

    def test_no_ticks_passes(self):
        """When zero ticks are omitted entirely, validation passes."""
        rows = [
            _row(
                actual="09:30:00",
                dur="00:00:00",
                status="FENCE",
                type_="BLOCK",
                event_id="BLK-001-FENCE",
                notes="frames_emitted=10800 frame_budget_remaining=0 reason=FENCE",
            ),
        ]
        validate_fence_no_zero_ticks(rows)


# ---------------------------------------------------------------------------
# AIRED Includes segment_index
# ---------------------------------------------------------------------------


class TestAiredIncludesSegmentIndex:
    """Every AIRED row must include segment_index=<int> in its notes."""

    def test_aired_with_segment_index_passes(self):
        rows = [
            _row(
                status="AIRED",
                notes="ontime=Y fallback=0 frames=675 segment_index=0",
            ),
        ]
        validate_aired_includes_segment_index(rows)

    def test_aired_missing_segment_index_raises(self):
        rows = [
            _row(
                status="AIRED",
                event_id="EVT-0001",
                notes="ontime=Y fallback=0 frames=675",
            ),
        ]
        with pytest.raises(AsRunArtifactError, match="AIRED missing segment_index.*EVT-0001"):
            validate_aired_includes_segment_index(rows)

    def test_non_aired_without_segment_index_passes(self):
        """Only AIRED rows require segment_index."""
        rows = [
            _row(status="TRUNCATED", notes="truncated_by_fence=Y frames=100"),
            _row(status="SKIPPED", notes="reason=missing_asset"),
        ]
        validate_aired_includes_segment_index(rows)

    def test_multiple_aired_all_with_segment_index_passes(self):
        rows = [
            _row(status="AIRED", event_id="EVT-0001", notes="frames=675 segment_index=0"),
            _row(status="AIRED", event_id="EVT-0002", notes="frames=30 segment_index=1"),
            _row(status="AIRED", event_id="EVT-0003", notes="frames=900 segment_index=2"),
        ]
        validate_aired_includes_segment_index(rows)

    def test_second_aired_missing_segment_index_raises(self):
        rows = [
            _row(status="AIRED", event_id="EVT-0001", notes="frames=675 segment_index=0"),
            _row(status="AIRED", event_id="EVT-0002", notes="frames=30"),
        ]
        with pytest.raises(AsRunArtifactError, match="AIRED missing segment_index.*EVT-0002"):
            validate_aired_includes_segment_index(rows)


# ---------------------------------------------------------------------------
# AR-ART-004 v0.2 — No Scheduled Fields in Text Log
# ---------------------------------------------------------------------------


class TestNoScheduledFieldsInTextLog:
    """AR-ART-004 v0.2: scheduled_duration_ms must not appear in .asrun file."""

    def test_scheduled_duration_ms_in_text_raises(self):
        asrun_text = (
            "# RETROVUE AS-RUN LOG\n"
            "# CHANNEL: test\n"
            "09:00:00 00:00:00 SEG_START  PROGRAM  EVT-0001                             "
            "scheduled_duration_ms=1350000\n"
        )
        with pytest.raises(AsRunArtifactError, match="AR-ART-004.*scheduled_duration_ms"):
            validate_no_scheduled_fields_in_text(asrun_text)

    def test_clean_text_passes(self):
        asrun_text = (
            "# RETROVUE AS-RUN LOG\n"
            "# CHANNEL: test\n"
            "09:00:00 00:00:00 SEG_START  PROGRAM  EVT-0001                             "
            "(segment begin)\n"
            "09:00:00 00:22:30 AIRED      PROGRAM  EVT-0001                             "
            "ontime=Y fallback=0 frames=675\n"
        )
        validate_no_scheduled_fields_in_text(asrun_text)

    def test_scheduled_start_utc_in_text_raises(self):
        asrun_text = (
            "# RETROVUE AS-RUN LOG\n"
            "09:00:00 00:00:00 SEG_START  PROGRAM  EVT-0001                             "
            "scheduled_start_utc=2026-02-13T14:00:00Z\n"
        )
        with pytest.raises(AsRunArtifactError, match="AR-ART-004.*scheduled_start_utc"):
            validate_no_scheduled_fields_in_text(asrun_text)


# ---------------------------------------------------------------------------
# Broadcast Day Midnight Format
# ---------------------------------------------------------------------------


class TestMidnightBroadcastFormatAllowed:
    """Broadcast-day rollover: ACTUAL > 23:59:59 must be accepted."""

    def test_actual_24_30_00_allowed(self):
        rows = [
            _row(actual="24:30:00", event_id="EVT-LATE"),
        ]
        validate_broadcast_day_time_format(rows)

    def test_actual_25_15_00_allowed(self):
        rows = [
            _row(actual="25:15:00", event_id="EVT-VERY-LATE"),
        ]
        validate_broadcast_day_time_format(rows)

    def test_normal_times_pass(self):
        rows = [
            _row(actual="09:00:00"),
            _row(actual="23:59:59", event_id="EVT-END"),
        ]
        validate_broadcast_day_time_format(rows)

    def test_invalid_minutes_raises(self):
        rows = [
            _row(actual="09:61:00", event_id="EVT-BAD"),
        ]
        with pytest.raises(AsRunArtifactError, match="minutes/seconds out of range"):
            validate_broadcast_day_time_format(rows)
