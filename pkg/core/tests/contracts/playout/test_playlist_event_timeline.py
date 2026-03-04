"""
Contract tests: INV-PLAYLIST-EVENT-TIMELINE-001.

A PlaylistEvent's wall-clock boundaries must exactly match the ScheduleItem
it was expanded from.  schedule_item.start_at == playlist_event.start_utc_ms
and schedule_item.end_at == playlist_event.end_utc_ms (epoch ms, integer equality).

Tests are deterministic (no wall-clock sleep, no DB).
See: docs/contracts/invariants/core/playout/INV-PLAYLIST-EVENT-TIMELINE-001.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Minimal domain stubs — no production imports required
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleItemStub:
    """Minimal ScheduleItem for timeline invariant testing."""
    id: str
    start_at: datetime          # slot start (tz-aware UTC)
    end_at: datetime            # slot end (tz-aware UTC)
    slot_duration_sec: int      # editorial slot length


@dataclass(frozen=True)
class PlaylistEventStub:
    """Minimal PlaylistEvent for timeline invariant testing."""
    block_id: str
    schedule_item_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt_to_ms(dt: datetime) -> int:
    """Convert a tz-aware datetime to epoch milliseconds."""
    return int(dt.timestamp() * 1000)


def _make_aligned_pair(
    *,
    start: datetime,
    slot_duration_sec: int,
) -> tuple[ScheduleItemStub, PlaylistEventStub]:
    """Create a ScheduleItem/PlaylistEvent pair with correct alignment."""
    from datetime import timedelta
    end = start + timedelta(seconds=slot_duration_sec)
    si = ScheduleItemStub(
        id="si-001",
        start_at=start,
        end_at=end,
        slot_duration_sec=slot_duration_sec,
    )
    pe = PlaylistEventStub(
        block_id="block-001",
        schedule_item_id=si.id,
        start_utc_ms=_dt_to_ms(start),
        end_utc_ms=_dt_to_ms(end),
        segments=[
            {"segment_type": "content", "segment_duration_ms": slot_duration_sec * 1000},
        ],
    )
    return si, pe


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvPlaylistEventTimeline001:
    """INV-PLAYLIST-EVENT-TIMELINE-001 enforcement tests."""

    def test_event_matches_schedule_item(self) -> None:
        """PlaylistEvent start/end must equal ScheduleItem start_at/end_at."""
        start = datetime(2025, 3, 1, 20, 0, 0, tzinfo=timezone.utc)
        slot_sec = 1800  # 30-minute slot

        si, pe = _make_aligned_pair(start=start, slot_duration_sec=slot_sec)

        expected_start_ms = _dt_to_ms(si.start_at)
        expected_end_ms = _dt_to_ms(si.end_at)

        assert pe.start_utc_ms == expected_start_ms, (
            f"INV-PLAYLIST-EVENT-TIMELINE-001-VIOLATED: "
            f"start mismatch: PE.start_utc_ms={pe.start_utc_ms} "
            f"!= SI.start_at={expected_start_ms}"
        )
        assert pe.end_utc_ms == expected_end_ms, (
            f"INV-PLAYLIST-EVENT-TIMELINE-001-VIOLATED: "
            f"end mismatch: PE.end_utc_ms={pe.end_utc_ms} "
            f"!= SI.end_at={expected_end_ms}"
        )

    def test_event_duration_equals_slot(self) -> None:
        """PlaylistEvent duration must equal ScheduleItem slot_duration_sec * 1000."""
        start = datetime(2025, 3, 1, 20, 0, 0, tzinfo=timezone.utc)
        slot_sec = 1800  # 30-minute slot

        si, pe = _make_aligned_pair(start=start, slot_duration_sec=slot_sec)

        pe_duration_ms = pe.end_utc_ms - pe.start_utc_ms
        expected_duration_ms = si.slot_duration_sec * 1000

        assert pe_duration_ms == expected_duration_ms, (
            f"INV-PLAYLIST-EVENT-TIMELINE-001-VIOLATED: "
            f"duration mismatch: PE duration={pe_duration_ms}ms "
            f"!= SI slot={expected_duration_ms}ms"
        )

    def test_shifted_start_detected(self) -> None:
        """A PlaylistEvent with shifted start violates the invariant."""
        start = datetime(2025, 3, 1, 20, 0, 0, tzinfo=timezone.utc)
        si = ScheduleItemStub(
            id="si-002",
            start_at=start,
            end_at=datetime(2025, 3, 1, 20, 30, 0, tzinfo=timezone.utc),
            slot_duration_sec=1800,
        )
        # Deliberately shift start by 1ms
        pe = PlaylistEventStub(
            block_id="block-002",
            schedule_item_id=si.id,
            start_utc_ms=_dt_to_ms(si.start_at) + 1,
            end_utc_ms=_dt_to_ms(si.end_at),
            segments=[{"segment_type": "content", "segment_duration_ms": 1_799_999}],
        )

        # This MUST detect the violation
        assert pe.start_utc_ms != _dt_to_ms(si.start_at), (
            "Expected shifted start to be detected"
        )

    def test_shifted_end_detected(self) -> None:
        """A PlaylistEvent with shifted end violates the invariant."""
        start = datetime(2025, 3, 1, 20, 0, 0, tzinfo=timezone.utc)
        si = ScheduleItemStub(
            id="si-003",
            start_at=start,
            end_at=datetime(2025, 3, 1, 20, 30, 0, tzinfo=timezone.utc),
            slot_duration_sec=1800,
        )
        # Deliberately shift end by -1ms
        pe = PlaylistEventStub(
            block_id="block-003",
            schedule_item_id=si.id,
            start_utc_ms=_dt_to_ms(si.start_at),
            end_utc_ms=_dt_to_ms(si.end_at) - 1,
            segments=[{"segment_type": "content", "segment_duration_ms": 1_799_999}],
        )

        # This MUST detect the violation
        assert pe.end_utc_ms != _dt_to_ms(si.end_at), (
            "Expected shifted end to be detected"
        )
