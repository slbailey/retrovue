"""
Contract tests for revision authority consistency between EPG and runtime playout.

Contract: docs/contracts/revision_authority_consistency.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
import uuid as uuid_mod
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError


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
from retrovue.epg.read_path import resolve_epg_broadcast_day
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run revision authority consistency contract tests."
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
    slug = f"rev-auth-{uuid_mod.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=slug,
        title="Revision Authority Consistency Channel",
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
    dsl_path.write_text("# revision authority consistency contract test dsl\n", encoding="utf-8")
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
    duration_sec: int,
    title: str,
    asset_id_raw: str,
    status: str = "active",
) -> ScheduleRevision:
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status=status,
        activated_at=datetime.now(timezone.utc) if status == "active" else None,
        created_by="test_revision_authority_consistency",
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
            "title": title,
            "asset_id_raw": asset_id_raw,
            "compiled_segments": _compiled_segments(asset_id_raw, duration_sec),
            "episode_duration_sec": duration_sec,
        },
    )
    db.add(item)
    db.flush()
    return rev


def _set_pointer(db, *, channel: Channel, broadcast_day: date, revision: ScheduleRevision) -> None:
    pointer = (
        db.query(ChannelActiveRevision)
        .filter(
            ChannelActiveRevision.channel_id == channel.id,
            ChannelActiveRevision.broadcast_day == broadcast_day,
        )
        .first()
    )
    if pointer is None:
        pointer = ChannelActiveRevision(
            channel_id=channel.id,
            broadcast_day=broadcast_day,
            schedule_revision_id=revision.id,
        )
        db.add(pointer)
    else:
        pointer.schedule_revision_id = revision.id
    db.flush()


def _block_id_for(asset_id_raw: str, start_time: datetime) -> str:
    start_ms = int(start_time.timestamp() * 1000)
    raw = f"{asset_id_raw}:{start_ms}"
    return f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _current_epg_block(channel_slug: str, *, now: datetime, tz_name: str = "UTC", day_start_hour: int = 6):
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    if local_now.hour < day_start_hour:
        bd = (local_now - timedelta(days=1)).date()
    else:
        bd = local_now.date()
    window_start = datetime(bd.year, bd.month, bd.day, day_start_hour, 0, tzinfo=tz)
    window_end = window_start + timedelta(hours=24)
    blocks = DslScheduleService.get_canonical_epg(channel_slug, window_start, window_end) or []
    for block in blocks:
        start_dt = datetime.fromisoformat(block["start_at"])
        end_dt = start_dt + timedelta(seconds=block["slot_duration_sec"])
        if start_dt <= now < end_dt:
            return block
    return None


@pytest.mark.contract
def test_epg_and_runtime_resolve_same_revision_for_now(db, channel, tmp_path, monkeypatch):
    """EPG and runtime lookup for now must resolve one canonical revision identity."""
    now = datetime(2026, 7, 1, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 7, 1)
    start = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    canonical = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Canonical Program",
        asset_id_raw="asset-canonical",
    )
    _set_pointer(db, channel=channel, broadcast_day=broadcast_day, revision=canonical)
    db.commit()

    epg_block = _current_epg_block(channel.slug, now=now, tz_name="UTC", day_start_hour=6)
    assert epg_block is not None

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    block = svc.get_block_at(channel.slug, int(now.timestamp() * 1000))
    assert block is not None

    runtime_rev = svc._query_active_revision_id_for_channel(channel.slug, int(now.timestamp() * 1000))
    assert runtime_rev is not None
    assert epg_block["schedule_revision_id"] == str(runtime_rev)


@pytest.mark.contract
def test_runtime_ignores_stale_active_revision_not_pointed(db, channel, tmp_path, monkeypatch):
    """Runtime current block must come from ChannelActiveRevision-selected revision."""
    now = datetime(2026, 7, 2, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 7, 2)
    start = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

    stale = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Stale Program",
        asset_id_raw="asset-stale",
        status="superseded",
    )
    canonical = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Canonical Program",
        asset_id_raw="asset-canonical",
    )
    _set_pointer(db, channel=channel, broadcast_day=broadcast_day, revision=canonical)
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    block = svc.get_block_at(channel.slug, int(now.timestamp() * 1000))
    assert block is not None

    expected_block_id = _block_id_for("asset-canonical", start)
    stale_block_id = _block_id_for("asset-stale", start)
    assert block.block_id == expected_block_id
    assert block.block_id != stale_block_id
    assert stale.id != canonical.id


@pytest.mark.contract
def test_runtime_current_content_matches_epg_current_content(db, channel, tmp_path, monkeypatch):
    """EPG current content identity and runtime current block identity must match."""
    now = datetime(2026, 7, 3, 12, 10, tzinfo=timezone.utc)
    broadcast_day = date(2026, 7, 3)
    start = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)

    stale = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="A Bug's Life",
        asset_id_raw="asset-bugs-life",
        status="superseded",
    )
    canonical = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Beauty and the Beast",
        asset_id_raw="asset-beauty-beast",
    )
    _set_pointer(db, channel=channel, broadcast_day=broadcast_day, revision=canonical)
    db.commit()

    epg_block = _current_epg_block(channel.slug, now=now, tz_name="UTC", day_start_hour=6)
    assert epg_block is not None
    assert epg_block["asset_id"] == "asset-beauty-beast"
    assert epg_block["schedule_revision_id"] == str(canonical.id)

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    runtime_block = svc.get_block_at(channel.slug, int(now.timestamp() * 1000))
    assert runtime_block is not None

    expected_runtime_block_id = _block_id_for("asset-beauty-beast", start)
    stale_runtime_block_id = _block_id_for("asset-bugs-life", start)
    assert runtime_block.block_id == expected_runtime_block_id
    assert runtime_block.block_id != stale_runtime_block_id
    assert stale.id != canonical.id


@pytest.mark.contract
def test_duplicate_active_revisions_same_day_are_rejected(db, channel, tmp_path, monkeypatch):
    """Duplicate active revisions for one day must be rejected at persistence layer."""
    broadcast_day = date(2026, 7, 4)
    start = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)

    _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Program A",
        asset_id_raw="asset-a",
    )
    with pytest.raises(IntegrityError):
        _insert_revision_with_item(
            db,
            channel=channel,
            broadcast_day=broadcast_day,
            start_time=start,
            duration_sec=1800,
            title="Program B",
            asset_id_raw="asset-b",
        )
        db.flush()
    db.rollback()
    db.add(channel)
    db.flush()

    # Control check: legal state (single active revision) still loads successfully.
    now = datetime(2026, 7, 4, 12, 10, tzinfo=timezone.utc)
    canonical = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        start_time=start,
        duration_sec=1800,
        title="Program A",
        asset_id_raw="asset-a",
    )
    _set_pointer(
        db,
        channel=channel,
        broadcast_day=broadcast_day,
        revision=canonical,
    )
    db.commit()
    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    block = svc.get_block_at(channel.slug, int(now.timestamp() * 1000))
    assert block is not None


@pytest.mark.contract
def test_boundary_derivation_matches_between_epg_and_runtime(db, channel, tmp_path, monkeypatch):
    """EPG and runtime must derive same broadcast day/revision around day boundary."""
    tz = ZoneInfo("America/New_York")
    now_local = datetime(2026, 7, 2, 5, 30, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    now_ms = int(now_utc.timestamp() * 1000)

    prev_day = date(2026, 7, 1)
    curr_day = date(2026, 7, 2)

    prev_rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=prev_day,
        start_time=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
        duration_sec=3600,
        title="Prev-Day Program",
        asset_id_raw="asset-prev-day",
    )
    curr_rev = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=curr_day,
        start_time=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        duration_sec=3600,
        title="Curr-Day Program",
        asset_id_raw="asset-curr-day",
    )
    _set_pointer(db, channel=channel, broadcast_day=prev_day, revision=prev_rev)
    _set_pointer(db, channel=channel, broadcast_day=curr_day, revision=curr_rev)
    db.commit()

    channels_payload = [
        {
            "channel_id": channel.slug,
            "schedule_config": {
                "channel_tz": "America/New_York",
                "broadcast_day_start_hour": 6,
            },
        }
    ]
    epg_day = resolve_epg_broadcast_day(
        channels_payload,
        None,
        now_utc=now_utc,
    )

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "America/New_York"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now_utc)
    runtime_day = svc._derive_broadcast_day_for_utc(now_utc).isoformat()
    assert runtime_day == epg_day

    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    runtime_block = svc.get_block_at(channel.slug, now_ms)
    assert runtime_block is not None

    epg_block = _current_epg_block(
        channel.slug,
        now=now_utc,
        tz_name="America/New_York",
        day_start_hour=6,
    )
    assert epg_block is not None
    runtime_rev = svc._query_active_revision_id_for_channel(channel.slug, now_ms)
    assert runtime_rev is not None
    assert epg_block["schedule_revision_id"] == str(runtime_rev)
