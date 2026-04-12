"""
Contract tests for XMLTV export timeline invariants.

Verifies XMLTV Export Contract:
  - Programme entries sorted by start time
  - No overlaps, no gaps
  - Exactly one programme covering current time
  - Timeline extends >= 48 hours
  - Time format: YYYYMMDDHHMMSS ±HHMM with timezone offset
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from retrovue.web.iptv import generate_xmltv
from tests.contracts.utils.xmltv_parser import parse_xmltv, programmes_by_channel
from tests.contracts.utils.timeline_validator import (
    assert_chronological_order,
    assert_continuity,
    assert_no_gaps,
    assert_no_overlaps,
)


# ---------------------------------------------------------------------------
# Fixtures: contiguous EPG for one channel (no gaps/overlaps)
# ---------------------------------------------------------------------------

def _make_contiguous_epg(channel_id: str, start_iso: str, count: int, duration_minutes: int = 30):
    """Build contiguous programme entries for timeline tests."""
    entries = []
    dt = datetime.fromisoformat(start_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    for i in range(count):
        start = dt + timedelta(minutes=i * duration_minutes)
        end = start + timedelta(minutes=duration_minutes)
        entries.append({
            "channel_id": channel_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "title": f"Programme {i + 1}",
        })
    return entries


def _make_channels_with_ids(*pairs: tuple[str, int]):
    """pairs = (channel_id, channel_id_int)."""
    return [
        {
            "channel_id": cid,
            "channel_id_int": cint,
            "name": cid,
            "schedule_config": {"channel_type": "network"},
        }
        for cid, cint in pairs
    ]


# 48+ hours of 30-min programmes = 96+ entries
EPG_48H = _make_contiguous_epg(
    "101",
    "2026-03-14T12:00:00+00:00",
    count=100,
    duration_minutes=30,
)
CHANNELS_ONE = _make_channels_with_ids(("101", 101))


class TestXmltvTimeline:
    """XMLTV Export Contract: programme timeline and time format invariants."""

    def test_programme_entries_sorted_by_start_time(self):
        """XMLTV chronological ordering invariant: programmes MUST be in start-time order."""
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H)
        _, programmes = parse_xmltv(xml_str)
        by_ch = programmes_by_channel(programmes)
        for ch_id, progs in by_ch.items():
            assert_chronological_order(progs, channel_id=ch_id)

    def test_no_overlaps(self):
        """XMLTV overlap invariant: programme intervals MUST NOT overlap."""
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H)
        _, programmes = parse_xmltv(xml_str)
        by_ch = programmes_by_channel(programmes)
        for ch_id, progs in by_ch.items():
            assert_no_overlaps(progs, channel_id=ch_id)

    def test_no_gaps_between_adjacent_entries(self):
        """XMLTV gap invariant: programme intervals MUST be contiguous."""
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H)
        _, programmes = parse_xmltv(xml_str)
        by_ch = programmes_by_channel(programmes)
        for ch_id, progs in by_ch.items():
            assert_no_gaps(progs, channel_id=ch_id)

    def test_exactly_one_programme_covers_current_time(self):
        """XMLTV schedule continuity: exactly one programme MUST cover current MasterClock time.

        Uses a time inside the first programme window.
        """
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H)
        _, programmes = parse_xmltv(xml_str)
        # First programme: 2026-03-14T12:00:00+00:00 -> 12:30
        current = programmes[0].start_parsed + 60  # 1 min into first programme
        by_ch = programmes_by_channel(programmes)
        for ch_id, progs in by_ch.items():
            assert_continuity(progs, current, channel_id=ch_id)

    def test_timeline_extends_at_least_48_hours(self):
        """XMLTV horizon invariant: guide MUST extend at least 48 hours into the future."""
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H)
        _, programmes = parse_xmltv(xml_str)
        if not programmes:
            raise AssertionError(
                "XMLTV horizon invariant violated: no programme entries"
            )
        # Span from first start to last stop
        first_start = min(p.start_parsed for p in programmes)
        last_stop = max(p.stop_parsed for p in programmes)
        span_seconds = last_stop - first_start
        forty_eight_hours = 48 * 3600
        assert span_seconds >= forty_eight_hours, (
            f"XMLTV horizon invariant violated: timeline span {span_seconds / 3600:.1f}h "
            f"< 48 hours"
        )

    def test_time_format_includes_timezone_offset(self):
        """XMLTV time format invariant: timestamps MUST include timezone offset (not UTC-only)."""
        # generate_xmltv uses _xmltv_timestamp which adds +0000 for naive; so we get ±HHMM
        xml_str = generate_xmltv(CHANNELS_ONE, EPG_48H[:1])
        _, programmes = parse_xmltv(xml_str)
        assert programmes, "Need at least one programme"
        # Parser already rejects missing offset; check format explicitly
        prog = programmes[0]
        assert " " in prog.start and ("+" in prog.start or "-" in prog.start), (
            "XMLTV time format invariant violated: start timestamp must include timezone offset"
        )
        assert " " in prog.stop and ("+" in prog.stop or "-" in prog.stop), (
            "XMLTV time format invariant violated: stop timestamp must include timezone offset"
        )
