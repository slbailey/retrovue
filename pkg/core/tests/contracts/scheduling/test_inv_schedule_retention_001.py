"""
Contract tests for INV-SCHEDULE-RETENTION-001: Schedule data lifecycle and retention.

Tier 1 (CompiledProgramLog) retains only rows where broadcast_day >= today - 1.
Tier 2 (TransmissionLog) retains only rows where end_utc_ms > now - 4 hours.
_save_compiled_schedule correctly upserts on (channel_id, broadcast_day).
_hydrate_schedule slow path backfills segmented_blocks into the DB row.
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


# ---------------------------------------------------------------------------
# Hydrate Slow Path Backfill
# ---------------------------------------------------------------------------


class TestHydrateSlowPathBackfill:
    """INV-SCHEDULE-RETENTION-001: _hydrate_schedule slow path MUST backfill
    segmented_blocks into the Tier 1 DB row so the PlaylogHorizonDaemon
    can consume them for Tier 2 pre-fill."""

    def test_slow_path_saves_segmented_blocks_back_to_db(self):
        """When _hydrate_schedule takes the slow path (no segmented_blocks),
        it MUST serialize the expanded blocks and write them back to the DB
        via _save_compiled_schedule. Without this, the daemon can never
        pre-fill Tier 2 for stale Tier 1 rows."""
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        svc = _build_service_for_purge()
        svc._dsl_path = "/tmp/fake.yaml"
        svc._filler_path = "/tmp/filler.mp4"
        svc._filler_duration_ms = 3000
        svc._channel_type = "network"
        svc._day_start_hour = 6
        svc._resolver = None
        svc._resolver_built_at = 0.0
        svc._resolver_ttl_s = 60.0
        svc._uri_cache = {}

        # A cached schedule WITHOUT segmented_blocks (stale pre-enhancement row)
        stale_schedule = {
            "program_blocks": [
                {
                    "start_at": "2026-03-01T12:00:00+00:00",
                    "slot_duration_sec": 1800,
                    "episode_duration_sec": 1320,
                    "asset_id": "ep.test.s01e01",
                }
            ],
            # NO "segmented_blocks" key — this is the stale state
        }

        fake_block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=1740830400000,
            end_utc_ms=1740832200000,
            segments=(ScheduledSegment(
                segment_type="content",
                asset_uri="/test/asset.ts",
                asset_start_offset_ms=0,
                segment_duration_ms=1320000,
            ),),
        )

        with patch.object(svc, "_expand_schedule_to_blocks", return_value=[fake_block]), \
             patch.object(svc, "_get_resolver"), \
             patch.object(svc, "_resolve_uris"), \
             patch.object(svc, "_save_compiled_schedule") as mock_save, \
             patch("retrovue.runtime.dsl_schedule_service.Path") as mock_path:
            mock_path.return_value.read_text.return_value = "channel: test\n"

            svc._hydrate_schedule(stale_schedule, "test-channel", "2026-03-01")

        # _save_compiled_schedule MUST have been called to backfill
        mock_save.assert_called_once()
        # The schedule passed to save MUST now contain segmented_blocks
        saved_schedule = mock_save.call_args[0][2]
        assert "segmented_blocks" in saved_schedule, (
            "INV-SCHEDULE-RETENTION-001 violated: _hydrate_schedule slow path "
            "did not backfill segmented_blocks into the DB row. "
            "PlaylogHorizonDaemon cannot pre-fill Tier 2 without them."
        )
        assert len(saved_schedule["segmented_blocks"]) == 1
