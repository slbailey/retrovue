"""
Contract tests for ChannelActiveRevision pointer integrity.

Contract: docs/contracts/channel_active_revision_integrity.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import uuid as uuid_mod

import pytest
from sqlalchemy.orm import sessionmaker


_THIS_FILE = Path(__file__).resolve()
REPO_ROOT = _THIS_FILE.parents[2]
SERVER_SRC = REPO_ROOT / "server" / "src"
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from retrovue.config import load_defaults
from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService
from retrovue.runtime.schedule_revision_writer import (
    write_active_revision_from_compiled_schedule,
)


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run ChannelActiveRevision integrity tests."
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
    slug = f"car-int-{uuid_mod.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=slug,
        title="ChannelActiveRevision Integrity Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start="06:00",
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _service_for_channel(channel_slug: str, tmp_path: Path) -> DslScheduleService:
    dsl_path = tmp_path / f"{channel_slug}.dsl"
    dsl_path.write_text("# channel active revision integrity contract test dsl\n", encoding="utf-8")
    return DslScheduleService(
        dsl_path=str(dsl_path),
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_ms=3_650_000,
        channel_slug=channel_slug,
        resolved_config=load_defaults(),
    )


def _compiled_segments(asset_id_raw: str, duration_sec: int) -> list[dict]:
    return [
        {
            "segment_type": "content",
            "asset_id": asset_id_raw,
            "duration_ms": duration_sec * 1000,
            "asset_start_offset_ms": 0,
        }
    ]


def _insert_revision_with_item(
    db,
    *,
    channel: Channel,
    broadcast_day: date,
    start_time: datetime,
    duration_sec: int = 1800,
    asset_id_raw: str = "asset-a",
    status: str = "active",
) -> ScheduleRevision:
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status=status,
        activated_at=datetime.now(timezone.utc) if status == "active" else None,
        created_by="test_channel_active_revision_integrity",
    )
    db.add(rev)
    db.flush()

    item = ScheduleItem(
        schedule_revision_id=rev.id,
        start_time=start_time,
        duration_sec=duration_sec,
        content_type="episode",
        slot_index=0,
        metadata_={
            "title": "Contract Test Block",
            "asset_id_raw": asset_id_raw,
            "compiled_segments": _compiled_segments(asset_id_raw, duration_sec),
            "episode_duration_sec": duration_sec,
        },
    )
    db.add(item)
    db.flush()
    return rev


def _set_pointer(
    db,
    *,
    channel_id,
    broadcast_day: date,
    schedule_revision_id,
) -> ChannelActiveRevision:
    pointer = (
        db.query(ChannelActiveRevision)
        .filter(
            ChannelActiveRevision.channel_id == channel_id,
            ChannelActiveRevision.broadcast_day == broadcast_day,
        )
        .first()
    )
    if pointer is None:
        pointer = ChannelActiveRevision(
            channel_id=channel_id,
            broadcast_day=broadcast_day,
            schedule_revision_id=schedule_revision_id,
        )
        db.add(pointer)
    else:
        pointer.schedule_revision_id = schedule_revision_id
    db.flush()
    return pointer


def _canonical_schedule(start_at: datetime, duration_sec: int = 1800) -> dict:
    return {
        "version": "program-schedule.v2",
        "source": {"compiler_version": "contract"},
        "hash": f"sha256:{uuid_mod.uuid4().hex}",
        "program_blocks": [
            {
                "title": "Canonical Program",
                "asset_id": "not-a-uuid",
                "start_at": start_at.isoformat(),
                "slot_duration_sec": duration_sec,
                "episode_duration_sec": duration_sec,
                "compiled_segments": _compiled_segments("not-a-uuid", duration_sec),
            }
        ],
    }


def _load_runtime_authority(
    channel_slug: str,
    tmp_path: Path,
    now: datetime,
    monkeypatch,
) -> tuple[DslScheduleService, bool, str | None]:
    svc = _service_for_channel(channel_slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel_slug)
    return svc, ok, err


@pytest.mark.contract
def test_pointer_targets_active_revision(db, channel):
    broadcast_day = date(2026, 4, 15)
    start_time = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start_time,
        status="active",
    )
    pointer = _set_pointer(
        db,
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=rev.id,
    )
    db.commit()

    pointed = db.query(ScheduleRevision).filter(ScheduleRevision.id == pointer.schedule_revision_id).first()
    assert pointed is not None
    assert pointed.status == "active"
    assert pointed.channel_id == channel.id
    assert pointed.broadcast_day == broadcast_day


@pytest.mark.contract
def test_pointer_to_superseded_revision_is_rejected(db, channel, tmp_path, monkeypatch):
    now = datetime(2026, 4, 15, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 4, 15)
    start_time = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    bad_rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start_time,
        status="superseded",
    )
    _set_pointer(
        db,
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=bad_rev.id,
    )
    db.commit()

    _svc, ok, err = _load_runtime_authority(channel.slug, tmp_path, now, monkeypatch)
    assert not ok
    assert err is not None
    assert "INV-REVISION-AUTHORITY-CONSISTENCY-001" in err


@pytest.mark.contract
def test_publish_transition_keeps_pointer_canonical(db, channel):
    broadcast_day = date(2026, 4, 15)
    day_start = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    old_schedule = _canonical_schedule(day_start)
    wrote_old = write_active_revision_from_compiled_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=broadcast_day,
        schedule=old_schedule,
        created_by="test_channel_active_revision_integrity_old",
    )
    assert wrote_old
    db.commit()

    old_active = (
        db.query(ScheduleRevision)
        .filter(
            ScheduleRevision.channel_id == channel.id,
            ScheduleRevision.broadcast_day == broadcast_day,
            ScheduleRevision.status == "active",
        )
        .first()
    )
    assert old_active is not None

    new_schedule = _canonical_schedule(day_start + timedelta(hours=1))
    wrote_new = write_active_revision_from_compiled_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=broadcast_day,
        schedule=new_schedule,
        created_by="test_channel_active_revision_integrity_new",
    )
    assert wrote_new
    db.commit()

    active_revs = (
        db.query(ScheduleRevision)
        .filter(
            ScheduleRevision.channel_id == channel.id,
            ScheduleRevision.broadcast_day == broadcast_day,
            ScheduleRevision.status == "active",
        )
        .all()
    )
    assert len(active_revs) == 1
    new_active = active_revs[0]
    assert new_active.id != old_active.id

    old_after = db.query(ScheduleRevision).filter(ScheduleRevision.id == old_active.id).first()
    assert old_after is not None
    assert old_after.status == "superseded"

    pointer = (
        db.query(ChannelActiveRevision)
        .filter(
            ChannelActiveRevision.channel_id == channel.id,
            ChannelActiveRevision.broadcast_day == broadcast_day,
        )
        .first()
    )
    assert pointer is not None
    assert pointer.schedule_revision_id == new_active.id


@pytest.mark.contract
def test_prewarm_succeeds_with_canonical_pointer(db, channel, tmp_path, monkeypatch):
    now = datetime(2026, 4, 15, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 4, 15)
    start_time = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start_time,
        status="active",
    )
    _set_pointer(
        db,
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=rev.id,
    )
    db.commit()

    svc, ok, err = _load_runtime_authority(channel.slug, tmp_path, now, monkeypatch)
    assert ok, err
    assert svc._blocks


@pytest.mark.contract
def test_restart_preserves_canonical_pointer_resolution(db, channel, tmp_path, monkeypatch):
    now = datetime(2026, 4, 15, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 4, 15)
    start_time = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start_time,
        status="active",
    )
    _set_pointer(
        db,
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=rev.id,
    )
    db.commit()

    svc_1, ok_1, err_1 = _load_runtime_authority(channel.slug, tmp_path, now, monkeypatch)
    assert ok_1, err_1
    rev_id_1 = svc_1._query_active_revision_id_for_channel(channel.slug, int(now.timestamp() * 1000))
    assert rev_id_1 is not None

    svc_2, ok_2, err_2 = _load_runtime_authority(channel.slug, tmp_path, now, monkeypatch)
    assert ok_2, err_2
    rev_id_2 = svc_2._query_active_revision_id_for_channel(channel.slug, int(now.timestamp() * 1000))
    assert rev_id_2 is not None

    assert rev_id_2 == rev_id_1 == rev.id


@pytest.mark.contract
def test_pointer_channel_or_day_mismatch_is_rejected(db, channel, tmp_path, monkeypatch):
    now = datetime(2026, 4, 15, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 4, 15)
    start_time = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)

    other_channel = Channel(
        id=uuid_mod.uuid4(),
        slug=f"car-other-{uuid_mod.uuid4().hex[:8]}",
        title="Other Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start="06:00",
        block_start_offsets_minutes=[0],
    )
    db.add(other_channel)
    db.flush()

    foreign_rev = _insert_revision_with_item(
        db,
        channel=other_channel,
        broadcast_day=broadcast_day + timedelta(days=1),
        start_time=start_time + timedelta(days=1),
        status="active",
    )
    _set_pointer(
        db,
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        schedule_revision_id=foreign_rev.id,
    )
    db.commit()

    _svc, ok, err = _load_runtime_authority(channel.slug, tmp_path, now, monkeypatch)
    assert not ok
    assert err is not None
    assert "INV-REVISION-AUTHORITY-CONSISTENCY-001" in err
