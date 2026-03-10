import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from retrovue.runtime.dsl_schedule_service import DslScheduleService


def _build_service_for_purge() -> DslScheduleService:
    svc = DslScheduleService.__new__(DslScheduleService)
    svc._blocks = []
    svc._lock = threading.Lock()
    svc._compiled_days = set()
    svc._extending = False
    svc._channel_slug = "test-channel"
    svc._last_tier1_purge_utc_ms = 0
    return svc


class TestPurgeExpiredTier1:
    # Tier: 2 | Scheduling logic invariant
    def test_deletes_rows_older_than_cutoff(self):
        svc = _build_service_for_purge()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 5
        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            count = svc._purge_expired_tier1()
        assert count == 5


class TestPurgeExpiredTier2:
    # Tier: 2 | Scheduling logic invariant
    def test_deletes_rows_older_than_4h(self):
        from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
        daemon = PlaylistBuilderDaemon.__new__(PlaylistBuilderDaemon)
        daemon._channel_id = "test-channel"
        daemon._last_tier2_purge_utc_ms = 0
        daemon._lock = threading.Lock()
        daemon._clock = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 10
        with patch("retrovue.infra.uow.session") as mock_session:
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            count = daemon._purge_expired_tier2()
        assert count == 10


class TestSaveCompiledScheduleUpsert:
    # Tier: 2 | Scheduling logic invariant
    def test_writes_relational_revision(self):
        svc = _build_service_for_purge()
        new_schedule = {"program_blocks": [{"start_at": "2026-03-01T12:00:00+00:00", "slot_duration_sec": 1800, "asset_id": "test-asset"}]}
        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session, \
             patch("retrovue.runtime.schedule_revision_writer.write_active_revision_from_compiled_schedule") as mock_write:
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            svc._save_compiled_schedule("test-channel", "2026-03-01", new_schedule, "new-hash")
        mock_write.assert_called_once()

    # Tier: 2 | Scheduling logic invariant
    def test_no_program_log_day_add(self):
        svc = _build_service_for_purge()
        with patch("retrovue.runtime.dsl_schedule_service.session") as mock_session, \
             patch("retrovue.runtime.schedule_revision_writer.write_active_revision_from_compiled_schedule"):
            mock_db = MagicMock()
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            svc._save_compiled_schedule("test-channel", "2026-03-01", {"program_blocks": []}, "h")
        from retrovue.domain.entities import ProgramLogDay
        assert [c for c in mock_db.add.call_args_list if c.args and isinstance(c.args[0], ProgramLogDay)] == []
