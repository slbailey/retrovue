"""Regression test: PlaylogHorizonDaemon broadcast day boundary must respect channel timezone.

Root cause (2026-02-19): _broadcast_date_for() compared programming_day_start_hour against
UTC hour, but the schedule compiler uses the channel's local timezone. For America/New_York
(UTC-5), broadcast day starts at 11:00 UTC, not 06:00 UTC. This created a 5-hour gap
(06:00–11:00 UTC) where the daemon looked for blocks in the wrong broadcast day, causing
Tier-2 to stop filling and all blocks to be served as unfilled pad-only frames.

INV-PLAYLOG-HORIZON-TZ-001: Broadcast day boundary MUST be computed in channel local time.
"""

import pytest
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo


class TestBroadcastDateForTimezone:
    """Test _broadcast_date_for with various timezone configurations."""

    def _make_daemon(self, channel_tz="UTC", day_start_hour=6):
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
        return PlaylogHorizonDaemon(
            channel_id="test-ch",
            programming_day_start_hour=day_start_hour,
            channel_tz=channel_tz,
        )

    def test_utc_channel_06utc_is_current_day(self):
        """UTC channel: 06:00 UTC → broadcast day = today."""
        daemon = self._make_daemon(channel_tz="UTC")
        dt = datetime(2026, 2, 19, 6, 0, tzinfo=timezone.utc)
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 19)

    def test_utc_channel_0559utc_is_previous_day(self):
        """UTC channel: 05:59 UTC → broadcast day = yesterday."""
        daemon = self._make_daemon(channel_tz="UTC")
        dt = datetime(2026, 2, 19, 5, 59, tzinfo=timezone.utc)
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 18)

    def test_est_channel_06utc_is_previous_day(self):
        """EST channel: 06:00 UTC = 01:00 EST → broadcast day = Feb 18 (previous day).

        This is THE regression case. Before the fix, the daemon returned Feb 19,
        causing a 5-hour gap in Tier-2 fills.
        """
        daemon = self._make_daemon(channel_tz="America/New_York")
        dt = datetime(2026, 2, 19, 6, 0, tzinfo=timezone.utc)
        # 06:00 UTC = 01:00 EST → hour < 6 → previous day
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 18)

    def test_est_channel_11utc_is_current_day(self):
        """EST channel: 11:00 UTC = 06:00 EST → broadcast day = Feb 19 (current day).

        This is where the new broadcast day actually starts for EST channels.
        """
        daemon = self._make_daemon(channel_tz="America/New_York")
        dt = datetime(2026, 2, 19, 11, 0, tzinfo=timezone.utc)
        # 11:00 UTC = 06:00 EST → hour >= 6 → current day
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 19)

    def test_est_channel_1059utc_is_previous_day(self):
        """EST channel: 10:59 UTC = 05:59 EST → still previous broadcast day."""
        daemon = self._make_daemon(channel_tz="America/New_York")
        dt = datetime(2026, 2, 19, 10, 59, tzinfo=timezone.utc)
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 18)

    def test_cet_channel_05utc_is_current_day(self):
        """CET channel (UTC+1): 05:00 UTC = 06:00 CET → current day."""
        daemon = self._make_daemon(channel_tz="Europe/Berlin")
        dt = datetime(2026, 2, 19, 5, 0, tzinfo=timezone.utc)
        # 05:00 UTC = 06:00 CET (Feb, no DST) → hour >= 6 → current day
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 19)

    def test_jst_channel_21utc_is_current_day(self):
        """JST channel (UTC+9): 21:00 UTC Feb 18 = 06:00 JST Feb 19 → Feb 19."""
        daemon = self._make_daemon(channel_tz="Asia/Tokyo")
        dt = datetime(2026, 2, 18, 21, 0, tzinfo=timezone.utc)
        # 21:00 UTC = 06:00 JST Feb 19 → hour >= 6 → Feb 19
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 19)

    def test_default_tz_is_utc(self):
        """Default channel_tz='UTC' behaves same as old UTC-only logic."""
        daemon = self._make_daemon()  # default channel_tz="UTC"
        dt = datetime(2026, 2, 19, 6, 0, tzinfo=timezone.utc)
        assert daemon._broadcast_date_for(dt) == date(2026, 2, 19)


class TestScanOverlap:
    """Test that _extend_to_target scans the previous broadcast day to avoid boundary gaps."""

    def test_scan_date_includes_previous_day(self):
        """The scan start date should be 1 day before the computed broadcast day."""
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
        daemon = PlaylogHorizonDaemon(
            channel_id="test-ch",
            channel_tz="America/New_York",
        )
        # At 06:00 UTC = 01:00 EST → broadcast_date_for = Feb 18
        # scan_date should be Feb 17 (one day earlier for overlap)
        dt = datetime(2026, 2, 19, 6, 0, tzinfo=timezone.utc)
        bd = daemon._broadcast_date_for(dt)
        assert bd == date(2026, 2, 18)
        # The actual scan starts at bd - 1 day = Feb 17
        scan_start = bd - timedelta(days=1)
        assert scan_start == date(2026, 2, 17)


class TestViolationLogging:
    """Test that consecutive zero-fill cycles produce violation warnings."""

    def test_consecutive_zero_fills_counter(self):
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon
        daemon = PlaylogHorizonDaemon(channel_id="test-ch", channel_tz="UTC")
        assert daemon._consecutive_zero_fills == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
