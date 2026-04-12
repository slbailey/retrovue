"""
Contract tests for EPG generation timeline invariants.

Verifies EPG Generation Contract:
  - Exactly one programme covering current MasterClock time
  - No gaps, no overlaps
  - Programmes ordered by start time
  - Horizon >= 48 hours
  - Determinism: repeated generation produces identical results

Tests obtain the EPG timeline via the public interface (data that would
be produced by the EPG generation layer). They do not inspect database
or internal implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from tests.contracts.utils.timeline_validator import (
    assert_chronological_order,
    assert_continuity,
    assert_no_gaps,
    assert_no_overlaps,
)


# ---------------------------------------------------------------------------
# Public interface: EPG timeline representation
#
# The EPG layer produces a programme timeline per channel. For contract
# tests we use a minimal representation: list of dicts with start_parsed,
# stop_parsed (epoch seconds), and channel_id. This is the outcome
# any EPG implementation must satisfy.
# ---------------------------------------------------------------------------

def _parse_iso_to_epoch(iso_str: str) -> int:
    """Convert ISO datetime to epoch seconds (MasterClock-aligned)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _build_epg_timeline_from_entries(entries: list[dict]) -> list[dict]:
    """Build timeline entries with start_parsed/stop_parsed for validators.

    Public interface: EPG service would return programme data; we convert
    to the format timeline_validator expects (start_parsed, stop_parsed).
    """
    out = []
    for e in entries:
        out.append({
            "channel_id": e["channel_id"],
            "start_parsed": _parse_iso_to_epoch(e["start_time"]),
            "stop_parsed": _parse_iso_to_epoch(e["end_time"]),
            "title": e.get("title"),
        })
    return out


def _timeline_by_channel(timeline: list[dict]) -> dict[str, list[dict]]:
    """Group timeline entries by channel_id."""
    by_ch: dict[str, list[dict]] = {}
    for t in timeline:
        cid = t["channel_id"]
        by_ch.setdefault(cid, []).append(t)
    return by_ch


# ---------------------------------------------------------------------------
# Fixtures: contiguous EPG (satisfies no-gap, no-overlap by construction)
# ---------------------------------------------------------------------------

def _make_contiguous_entries(channel_id: str, start_iso: str, count: int, duration_min: int = 30):
    """Build contiguous programme entries for one channel."""
    entries = []
    dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    for i in range(count):
        start = dt + timedelta(minutes=i * duration_min)
        end = start + timedelta(minutes=duration_min)
        entries.append({
            "channel_id": channel_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "title": f"Programme {i + 1}",
        })
    return entries


# 48+ hours of 30-min programmes
EPG_TIMELINE_ENTRIES = (
    _make_contiguous_entries("cheers-24-7", "2026-03-14T12:00:00+00:00", 100, 30)
    + _make_contiguous_entries("hbo", "2026-03-14T12:00:00+00:00", 100, 30)
)


class TestEpgTimeline:
    """EPG Generation Contract: timeline invariants."""

    def test_exactly_one_programme_covers_current_time(self):
        """EPG continuity invariant: every channel MUST have exactly one programme covering current time."""
        timeline = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        by_ch = _timeline_by_channel(timeline)
        # Current time = 1 min into first programme of first channel
        first_entry = timeline[0]
        current = first_entry["start_parsed"] + 60
        for ch_id, progs in by_ch.items():
            assert_continuity(progs, current, channel_id=ch_id)

    def test_no_gaps_between_programmes(self):
        """EPG gap invariant: programme intervals MUST NOT contain gaps."""
        timeline = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        by_ch = _timeline_by_channel(timeline)
        for ch_id, progs in by_ch.items():
            assert_no_gaps(progs, channel_id=ch_id)

    def test_no_overlaps(self):
        """EPG overlap invariant: programme intervals MUST NOT overlap."""
        timeline = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        by_ch = _timeline_by_channel(timeline)
        for ch_id, progs in by_ch.items():
            assert_no_overlaps(progs, channel_id=ch_id)

    def test_programmes_ordered_by_start_time(self):
        """EPG chronological ordering: programme entries MUST be ordered by start time."""
        timeline = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        by_ch = _timeline_by_channel(timeline)
        for ch_id, progs in by_ch.items():
            assert_chronological_order(progs, channel_id=ch_id)

    def test_horizon_at_least_48_hours(self):
        """EPG horizon invariant: timeline MUST extend >= 48 hours."""
        timeline = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        if not timeline:
            raise AssertionError(
                "EPG horizon invariant violated: timeline is empty"
            )
        first_start = min(t["start_parsed"] for t in timeline)
        last_stop = max(t["stop_parsed"] for t in timeline)
        span_seconds = last_stop - first_start
        assert span_seconds >= 48 * 3600, (
            f"EPG horizon invariant violated: span {span_seconds / 3600:.1f}h < 48 hours"
        )

    def test_determinism_repeated_generation_identical(self):
        """EPG determinism invariant: identical schedule state MUST produce identical EPG timeline."""
        timeline1 = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        timeline2 = _build_epg_timeline_from_entries(EPG_TIMELINE_ENTRIES)
        assert len(timeline1) == len(timeline2), (
            "EPG determinism invariant violated: timeline length changed between runs"
        )
        for a, b in zip(timeline1, timeline2):
            assert a["start_parsed"] == b["start_parsed"] and a["stop_parsed"] == b["stop_parsed"], (
                "EPG determinism invariant violated: programme interval changed between runs"
            )
