"""
Contract tests for INV-SCHEDULE-RETENTION-001: Schedule data lifecycle and retention.

Tier 1 (CompiledProgramLog) retains only rows where broadcast_day >= today - 1.
Tier 2 (TransmissionLog) retains only rows where end_utc_ms > now - 4 hours.
_save_compiled_schedule correctly upserts on (channel_id, broadcast_day).
"""

import threading
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from retrovue.runtime.dsl_schedule_service import DslScheduleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_service_for_purge() -> DslScheduleService:
    """Create a DslScheduleService with minimal init for purge testing."""
    svc = DslScheduleService.__new__(DslScheduleService)
    svc._blocks = []
    svc._lock = threading.Lock()
    svc._compiled_days = set()
    svc._extending = False
    svc._channel_slug = "test-channel"
    svc._last_tier1_purge_utc_ms = 0
    return svc


# ---------------------------------------------------------------------------
# Tier 1 Purge
# ---------------------------------------------------------------------------


class TestPurgeExpiredTier1:
    """INV-SCHEDULE-RETENTION-001: Tier 1 purge deletes stale broadcast days."""

    def test_deletes_rows_older_than_cutoff(self):
        """Rows with broadcast_day < today - 1 MUST be deleted."""
        svc = _build_service_for_purge()

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_filtered = MagicMock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.delete.return_value = 5  # 5 rows purged

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            count = svc._purge_expired_tier1()

        assert count == 5, (
            "INV-SCHEDULE-RETENTION-001 violated: purge should return count of deleted rows"
        )
        mock_db.query.assert_called_once()
        mock_filtered.delete.assert_called_once()

    def test_respects_hourly_throttle(self):
        """Purge MUST NOT run more than once per hour."""
        svc = _build_service_for_purge()

        # Simulate last purge was 30 minutes ago
        now_ms = int(datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        thirty_min_ago_ms = now_ms - (30 * 60 * 1000)
        svc._last_tier1_purge_utc_ms = thirty_min_ago_ms

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            count = svc._purge_expired_tier1(now_utc_ms=now_ms)

        assert count == 0, (
            "INV-SCHEDULE-RETENTION-001 violated: purge fired within throttle window"
        )
        # session() should NOT have been called
        mock_session.assert_not_called()

    def test_runs_after_throttle_expires(self):
        """Purge MUST run after the 1-hour throttle window expires."""
        svc = _build_service_for_purge()

        now_ms = int(datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        two_hours_ago_ms = now_ms - (2 * 3600 * 1000)
        svc._last_tier1_purge_utc_ms = two_hours_ago_ms

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_filtered = MagicMock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.delete.return_value = 0

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            count = svc._purge_expired_tier1(now_utc_ms=now_ms)

        mock_db.query.assert_called_once()


# ---------------------------------------------------------------------------
# Tier 2 Purge
# ---------------------------------------------------------------------------


class TestPurgeExpiredTier2:
    """INV-SCHEDULE-RETENTION-001: Tier 2 purge deletes stale transmission log rows."""

    def test_deletes_rows_older_than_4h(self):
        """Rows with end_utc_ms <= now - 4h MUST be deleted."""
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        daemon = PlaylogHorizonDaemon.__new__(PlaylogHorizonDaemon)
        daemon._channel_id = "test-channel"
        daemon._last_tier2_purge_utc_ms = 0
        daemon._lock = threading.Lock()
        daemon._clock = None

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_filtered = MagicMock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.delete.return_value = 10

        with patch("retrovue.infra.uow.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            count = daemon._purge_expired_tier2()

        assert count == 10, (
            "INV-SCHEDULE-RETENTION-001 violated: purge should return count of deleted rows"
        )
        mock_db.query.assert_called_once()
        mock_filtered.delete.assert_called_once()

    def test_respects_hourly_throttle(self):
        """Purge MUST NOT run more than once per hour."""
        from retrovue.runtime.playlog_horizon_daemon import PlaylogHorizonDaemon

        daemon = PlaylogHorizonDaemon.__new__(PlaylogHorizonDaemon)
        daemon._channel_id = "test-channel"
        daemon._lock = threading.Lock()

        now_ms = int(datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
        daemon._last_tier2_purge_utc_ms = now_ms - (30 * 60 * 1000)

        with patch("retrovue.infra.uow.session") as mock_session:
            count = daemon._purge_expired_tier2(now_utc_ms=now_ms)

        assert count == 0
        mock_session.assert_not_called()


# ---------------------------------------------------------------------------
# Upsert Correctness
# ---------------------------------------------------------------------------


class TestSaveCompiledScheduleUpsert:
    """INV-SCHEDULE-RETENTION-001: _save_compiled_schedule correctly upserts."""

    def test_updates_existing_row_on_conflict(self):
        """When a row already exists for (channel_id, broadcast_day),
        _save_compiled_schedule MUST update it, not silently fail."""
        svc = _build_service_for_purge()

        existing_row = MagicMock()
        existing_row.compiled_json = {"old": True}
        existing_row.schedule_hash = "old-hash"

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_filtered = MagicMock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = existing_row

        new_schedule = {
            "program_blocks": [
                {
                    "start_at": "2026-03-01T12:00:00+00:00",
                    "slot_duration_sec": 1800,
                    "asset_id": "test-asset",
                }
            ],
        }

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            svc._save_compiled_schedule(
                "test-channel", "2026-03-01", new_schedule, "new-hash"
            )

        # Existing row should be UPDATED, not a new row added
        assert existing_row.compiled_json == new_schedule
        assert existing_row.schedule_hash == "new-hash"
        mock_db.add.assert_not_called()

    def test_inserts_new_row_when_none_exists(self):
        """When no row exists for (channel_id, broadcast_day),
        _save_compiled_schedule MUST insert a new one."""
        svc = _build_service_for_purge()

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_filtered = MagicMock()
        mock_query.filter.return_value = mock_filtered
        mock_filtered.first.return_value = None  # No existing row

        new_schedule = {
            "program_blocks": [
                {
                    "start_at": "2026-03-01T12:00:00+00:00",
                    "slot_duration_sec": 1800,
                    "asset_id": "test-asset",
                }
            ],
        }

        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)

            svc._save_compiled_schedule(
                "test-channel", "2026-03-01", new_schedule, "new-hash"
            )

        # A new row should be added
        mock_db.add.assert_called_once()
