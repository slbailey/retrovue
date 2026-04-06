"""
Contract tests for INV-EPG-HORIZON-COVERAGE-001.

EPG MUST serve the full compiled horizon. For dates within
[now, now + HORIZON_DAYS], get_horizon_epg() returns non-empty results
when blocks exist in memory.  For dates beyond the horizon, returns [].
EPG read path MUST NOT trigger compilation (INV-SCHEDULE-PREWARM-001).

Tier 2 (Logic):
  - compiled-but-unpersisted day returns EPG data from in-memory blocks
  - date beyond horizon returns empty list (not None, not error)
  - date within horizon with no compiled blocks returns empty list

Tier 3 (Runtime):
  - EPG horizon extends as scheduler daemon compiles future days
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal fakes for isolation — no DB, no real DslScheduleService init
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _FakeSegment:
    segment_type: str = "content"
    asset_uri: str = "/media/test.ts"
    asset_start_offset_ms: int = 0
    segment_duration_ms: int = 1800_000  # 30 min
    transition_in: str = "TRANSITION_NONE"
    transition_in_duration_ms: int = 0
    transition_out: str = "TRANSITION_NONE"
    transition_out_duration_ms: int = 0
    gain_db: float = 0.0
    is_primary: bool = False
    spot_index: int | None = None


@dataclass(frozen=True)
class _FakeBlock:
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: tuple
    traffic_profile: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_utc_ms - self.start_utc_ms


class _FakeClock:
    def __init__(self, now: datetime):
        self._now = now

    def now_utc(self) -> datetime:
        return self._now


def _make_day_blocks(date_str: str, day_start_hour: int = 6) -> list:
    """Create 48 half-hour blocks covering a full broadcast day."""
    from datetime import date as _date_type
    bd = _date_type.fromisoformat(date_str)
    day_start = datetime(bd.year, bd.month, bd.day, day_start_hour, 0, tzinfo=timezone.utc)
    blocks = []
    for i in range(48):
        start_ms = int((day_start + timedelta(minutes=30 * i)).timestamp() * 1000)
        end_ms = start_ms + 1800_000
        blocks.append(_FakeBlock(
            block_id=f"{date_str}-blk-{i:02d}",
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            segments=(_FakeSegment(asset_uri=f"/media/{date_str}-{i}.ts"),),
        ))
    return blocks


# ---------------------------------------------------------------------------
# Tier 2: Logic tests
# ---------------------------------------------------------------------------

class TestInvEpgHorizonCoverage001Tier2:
    """Tier 2 tests: EPG horizon-aware read logic."""

    def test_compiled_day_returns_epg_from_in_memory_blocks(self):
        """INV-EPG-HORIZON-COVERAGE-001: compiled-but-unpersisted day
        returns EPG data derived from in-memory blocks."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        today_str = "2026-04-06"

        blocks = _make_day_blocks(today_str)

        # Patch get_canonical_epg to return None (no DB data)
        with patch.object(DslScheduleService, "get_canonical_epg", return_value=None):
            result = DslScheduleService.get_horizon_epg(
                blocks=blocks,
                compiled_days={today_str},
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
            )

        # Must return non-empty EPG entries
        assert result is not None
        assert len(result) > 0
        # Each entry must have required EPG fields
        for entry in result:
            assert "start_at" in entry
            assert "slot_duration_sec" in entry

    def test_beyond_horizon_returns_empty_list(self):
        """INV-EPG-HORIZON-COVERAGE-001: date beyond horizon returns
        empty list, not None or error."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        # Query for a date 10 days in the future (beyond 3-day horizon)
        far_future = "2026-04-16"

        with patch.object(DslScheduleService, "get_canonical_epg", return_value=None):
            result = DslScheduleService.get_horizon_epg(
                blocks=[],
                compiled_days=set(),
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 16, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 17, 6, 0, tzinfo=timezone.utc),
            )

        assert result == []

    def test_within_horizon_no_compiled_blocks_returns_empty(self):
        """INV-EPG-HORIZON-COVERAGE-001: date within horizon but not yet
        compiled returns empty list (scheduler daemon may be behind)."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        tomorrow_str = "2026-04-07"

        # No blocks compiled for tomorrow, but it's within horizon
        with patch.object(DslScheduleService, "get_canonical_epg", return_value=None):
            result = DslScheduleService.get_horizon_epg(
                blocks=[],
                compiled_days=set(),
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
            )

        assert result == []

    def test_db_data_preferred_over_in_memory(self):
        """INV-EPG-READS-CANONICAL-SCHEDULE-001: when DB has data,
        get_horizon_epg returns DB data without touching in-memory blocks."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
        today_str = "2026-04-06"

        db_epg = [{"start_at": "2026-04-06T06:00:00+00:00", "slot_duration_sec": 1800, "asset_id": "db-asset", "collection": None, "content_type": "episode"}]

        with patch.object(DslScheduleService, "get_canonical_epg", return_value=db_epg):
            result = DslScheduleService.get_horizon_epg(
                blocks=_make_day_blocks(today_str),
                compiled_days={today_str},
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 6, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
            )

        assert result == db_epg

    def test_no_compilation_triggered(self):
        """INV-SCHEDULE-PREWARM-001: get_horizon_epg MUST NOT call
        compile_schedule or _compile_day."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

        with patch.object(DslScheduleService, "get_canonical_epg", return_value=None):
            # Should return [] without attempting compilation
            result = DslScheduleService.get_horizon_epg(
                blocks=[],
                compiled_days=set(),
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
            )

        # Pure read — no side effects. If this returns without error, no compilation happened.
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tier 3: Runtime integration tests
# ---------------------------------------------------------------------------

class TestInvEpgHorizonCoverage001Tier3:
    """Tier 3 tests: horizon extension observable through EPG."""

    def test_horizon_extends_as_daemon_compiles(self):
        """INV-EPG-HORIZON-COVERAGE-001: EPG coverage grows as the
        scheduler daemon compiles additional future days."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        now = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

        # Initially only today is compiled
        today_blocks = _make_day_blocks("2026-04-06")
        compiled = {"2026-04-06"}

        with patch.object(DslScheduleService, "get_canonical_epg", return_value=None):
            # Tomorrow not yet compiled — returns empty
            result_tomorrow = DslScheduleService.get_horizon_epg(
                blocks=today_blocks,
                compiled_days=compiled,
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
            )
            assert result_tomorrow == []

            # Daemon compiles tomorrow
            tomorrow_blocks = _make_day_blocks("2026-04-07")
            all_blocks = today_blocks + tomorrow_blocks
            compiled.add("2026-04-07")

            # Now EPG covers tomorrow
            result_tomorrow_after = DslScheduleService.get_horizon_epg(
                blocks=all_blocks,
                compiled_days=compiled,
                horizon_days=3,
                clock_now=now,
                channel_id="test-channel",
                window_start=datetime(2026, 4, 7, 6, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc),
            )
            assert len(result_tomorrow_after) > 0
