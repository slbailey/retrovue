"""
Contract tests for schedule revision scope and restart behavior.

Contract: docs/contracts/schedule_revision_scope.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import uuid as uuid_mod

import pytest
from sqlalchemy import and_
from sqlalchemy.orm import sessionmaker


# Keep imports stable regardless of pytest cwd.
_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[2]
SERVER_SRC = REPO_ROOT / "server" / "src"
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from retrovue.config import load_defaults
from retrovue.domain.entities import Channel, ScheduleItem, ScheduleRevision
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService
from retrovue.runtime.schedule_revision_writer import (
    write_active_revision_from_compiled_schedule,
)


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    """Mirror server test behavior: always bind SessionLocal to TEST DB."""
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run schedule revision scope contract tests."
        )
    if settings.test_database_url == settings.database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL equals DATABASE_URL. Refusing to run against non-isolated database."
        )

    engine = db_module.get_engine(for_test=True)
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
    )
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(db_module, "get_engine", lambda for_test=False, db_url=None: engine)


@pytest.fixture()
def db():
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def channel(db):
    slug = f"scope-{uuid_mod.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=slug,
        title="Schedule Scope Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start="06:00",
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _block(start_dt: datetime, duration_sec: int = 1800) -> dict:
    return {
        "title": f"Block {start_dt.isoformat()}",
        "asset_id": "not-a-uuid",
        "start_at": start_dt.isoformat(),
        "slot_duration_sec": duration_sec,
        "episode_duration_sec": duration_sec,
        "compiled_segments": [
            {
                "segment_type": "content",
                "asset_id": "not-a-uuid",
                "duration_ms": duration_sec * 1000,
                "asset_start_offset_ms": 0,
            }
        ],
    }


def _schedule_with_blocks(blocks: list[dict]) -> dict:
    return {
        "version": "program-schedule.v2",
        "source": {"compiler_version": "contract"},
        "hash": f"sha256:{uuid_mod.uuid4().hex}",
        "program_blocks": blocks,
    }


def _write_day_schedule(db, *, channel_slug: str, broadcast_day: date, starts: list[datetime]) -> bool:
    schedule = _schedule_with_blocks([_block(start_dt) for start_dt in starts])
    return write_active_revision_from_compiled_schedule(
        db,
        channel_slug=channel_slug,
        broadcast_day=broadcast_day,
        schedule=schedule,
        created_by="test_schedule_revision_scope",
    )


def _active_revisions_for_channel(db, channel_id):
    return (
        db.query(ScheduleRevision)
        .filter(
            ScheduleRevision.channel_id == channel_id,
            ScheduleRevision.status == "active",
        )
        .order_by(ScheduleRevision.broadcast_day.asc())
        .all()
    )


def _service_for_channel(channel_slug: str, tmp_path: Path) -> DslScheduleService:
    dsl_path = tmp_path / f"{channel_slug}.dsl"
    dsl_path.write_text("# schedule revision scope contract test dsl\n", encoding="utf-8")
    svc = DslScheduleService(
        dsl_path=str(dsl_path),
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_ms=3_650_000,
        channel_slug=channel_slug,
        resolved_config=load_defaults(),
    )
    return svc


@pytest.mark.contract
class TestScheduleRevisionScopeContract:
    # Test 1 — Per-day revision scope
    def test_multiple_active_days_persist(self, db, channel):
        base = datetime(2026, 4, 10, 6, 0, tzinfo=timezone.utc)
        for offset in range(3):
            day = (base + timedelta(days=offset)).date()
            starts = [base + timedelta(days=offset), base + timedelta(days=offset, minutes=30)]
            assert _write_day_schedule(
                db,
                channel_slug=channel.slug,
                broadcast_day=day,
                starts=starts,
            )

        active = _active_revisions_for_channel(db, channel.id)
        assert len(active) == 3
        assert len({rev.broadcast_day for rev in active}) == 3

    # Test 2 — Restart idempotency
    def test_restart_does_not_rebuild_existing_days(self, db, channel, tmp_path, monkeypatch):
        base = datetime(2026, 4, 20, 6, 0, tzinfo=timezone.utc)
        days = []
        for offset in range(3):
            day = (base + timedelta(days=offset)).date()
            days.append(day)
            starts = [base + timedelta(days=offset), base + timedelta(days=offset, minutes=30)]
            assert _write_day_schedule(
                db,
                channel_slug=channel.slug,
                broadcast_day=day,
                starts=starts,
            )

        initial = _active_revisions_for_channel(db, channel.id)
        initial_ids = {rev.broadcast_day: rev.id for rev in initial}
        assert len(initial_ids) == 3

        compile_calls: list[str] = []

        def _fake_parse_dsl(_text: str):
            return {"timezone": "UTC"}

        def _fake_compile_day(self, channel_id: str, broadcast_day: str, effective_day_open_ms: int = 0):
            compile_calls.append(broadcast_day)
            return []

        monkeypatch.setattr(dsl_mod, "parse_dsl", _fake_parse_dsl)
        monkeypatch.setattr(DslScheduleService, "_compile_day", _fake_compile_day)

        svc_1 = _service_for_channel(channel.slug, tmp_path)
        ok_1, err_1 = svc_1.load_schedule(channel.slug)
        assert ok_1, err_1

        svc_2 = _service_for_channel(channel.slug, tmp_path)
        ok_2, err_2 = svc_2.load_schedule(channel.slug)
        assert ok_2, err_2

        after = _active_revisions_for_channel(db, channel.id)
        after_ids = {rev.broadcast_day: rev.id for rev in after}

        assert after_ids == initial_ids
        assert compile_calls == []

    # Test 3 — Past immutability
    def test_past_immutability(self, db, channel, monkeypatch):
        now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(dsl_mod, "parse_dsl", lambda text: {"timezone": "UTC"})
        from retrovue.runtime import schedule_revision_writer as writer_mod

        monkeypatch.setattr(writer_mod._clock, "now_utc", lambda: now)

        day = date(2026, 4, 30)
        original_starts = [
            datetime(2026, 4, 30, 6, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 30, 6, 30, tzinfo=timezone.utc),
            datetime(2026, 4, 30, 13, 0, tzinfo=timezone.utc),
        ]
        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day,
            starts=original_starts,
        )

        rev_before = _active_revisions_for_channel(db, channel.id)[0]
        past_items_before = (
            db.query(ScheduleItem)
            .filter(
                ScheduleItem.schedule_revision_id == rev_before.id,
                ScheduleItem.start_time < now,
            )
            .order_by(ScheduleItem.start_time.asc())
            .all()
        )
        before_snapshot = [(it.start_time, it.duration_sec, it.slot_index) for it in past_items_before]
        assert before_snapshot

        replacement_starts = [
            datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 30, 14, 30, tzinfo=timezone.utc),
        ]
        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day,
            starts=replacement_starts,
        )

        rev_after = _active_revisions_for_channel(db, channel.id)[0]
        past_items_after = (
            db.query(ScheduleItem)
            .filter(
                ScheduleItem.schedule_revision_id == rev_after.id,
                ScheduleItem.start_time < now,
            )
            .order_by(ScheduleItem.start_time.asc())
            .all()
        )
        after_snapshot = [(it.start_time, it.duration_sec, it.slot_index) for it in past_items_after]
        assert after_snapshot == before_snapshot

    # Test 4 — Forward-only generation
    def test_forward_only_generation(self, db, channel, monkeypatch):
        now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        from retrovue.runtime import schedule_revision_writer as writer_mod

        monkeypatch.setattr(writer_mod._clock, "now_utc", lambda: now)

        day = date(2026, 5, 1)
        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day,
            starts=[
                datetime(2026, 5, 1, 6, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc),
            ],
        )
        active_before = _active_revisions_for_channel(db, channel.id)
        assert len(active_before) == 1
        rev_id_before = active_before[0].id

        mixed_starts = [
            datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc),  # invalid past relative to now
            datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
        ]
        with pytest.raises(ValueError, match="INV-SCHEDULE-FUTURE-ONLY-MUTATION-001"):
            _write_day_schedule(
                db,
                channel_slug=channel.slug,
                broadcast_day=day,
                starts=mixed_starts,
            )

        active_after = _active_revisions_for_channel(db, channel.id)
        assert len(active_after) == 1
        assert active_after[0].id == rev_id_before

    # Test 5 — Revision replacement scope
    def test_revision_replacement_scope(self, db, channel):
        day_a = date(2026, 5, 10)
        day_b = date(2026, 5, 11)

        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day_a,
            starts=[datetime(2026, 5, 10, 6, 0, tzinfo=timezone.utc)],
        )
        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day_b,
            starts=[datetime(2026, 5, 11, 6, 0, tzinfo=timezone.utc)],
        )

        active_before = _active_revisions_for_channel(db, channel.id)
        assert len(active_before) == 2
        ids_before = {rev.broadcast_day: rev.id for rev in active_before}

        assert _write_day_schedule(
            db,
            channel_slug=channel.slug,
            broadcast_day=day_a,
            starts=[datetime(2026, 5, 10, 7, 0, tzinfo=timezone.utc)],
        )

        active_after = _active_revisions_for_channel(db, channel.id)
        assert len(active_after) == 2
        ids_after = {rev.broadcast_day: rev.id for rev in active_after}

        assert ids_after[day_a] != ids_before[day_a]
        assert ids_after[day_b] == ids_before[day_b]

        superseded_day_b = (
            db.query(ScheduleRevision)
            .filter(
                and_(
                    ScheduleRevision.channel_id == channel.id,
                    ScheduleRevision.broadcast_day == day_b,
                    ScheduleRevision.status == "superseded",
                )
            )
            .all()
        )
        assert superseded_day_b == []
