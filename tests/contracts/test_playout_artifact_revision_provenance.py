"""
Contract tests for playout artifact revision provenance.

Contract: docs/contracts/playout_artifact_revision_provenance.md
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
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
    PlaylistEvent,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run playout artifact provenance tests."
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
    slug = f"prov-{uuid_mod.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=slug,
        title="Playout Provenance Channel",
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
    dsl_path.write_text("# playout artifact provenance contract test dsl\n", encoding="utf-8")
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
            "transition_in": "TRANSITION_NONE",
            "transition_out": "TRANSITION_NONE",
            "transition_in_duration_ms": 0,
            "transition_out_duration_ms": 0,
            "gain_db": 0.0,
            "is_primary": True,
        }
    ]


def _block_id_for(asset_id_raw: str, start_time: datetime) -> str:
    start_ms = int(start_time.timestamp() * 1000)
    raw = f"{asset_id_raw}:{start_ms}"
    return f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


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
) -> tuple[ScheduleRevision, ScheduleItem]:
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status=status,
        activated_at=datetime.now(timezone.utc) if status == "active" else None,
        created_by="test_playout_artifact_revision_provenance",
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
    return rev, item


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


def _insert_playlist_event(
    db,
    *,
    channel_slug: str,
    broadcast_day: date,
    block_id: str,
    start_utc_ms: int,
    end_utc_ms: int,
    schedule_revision_id,
    asset_uri: str,
) -> None:
    row = PlaylistEvent(
        block_id=block_id,
        channel_slug=channel_slug,
        broadcast_day=broadcast_day,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=[
            {
                "segment_type": "content",
                "asset_uri": asset_uri,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": end_utc_ms - start_utc_ms,
                "transition_in": "TRANSITION_NONE",
                "transition_out": "TRANSITION_NONE",
                "transition_in_duration_ms": 0,
                "transition_out_duration_ms": 0,
                "gain_db": 0.0,
                "is_primary": True,
            }
        ],
        schedule_revision_id=schedule_revision_id,
    )
    db.add(row)
    db.flush()


def _load_and_get_current_block(
    svc: DslScheduleService,
    *,
    channel_slug: str,
    now: datetime,
    monkeypatch,
):
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel_slug)
    assert ok, err
    return svc.get_block_at(channel_slug, int(now.timestamp() * 1000))


@pytest.mark.contract
def test_playlist_event_requires_revision_provenance(db, channel, tmp_path, monkeypatch):
    """Authoritative runtime lookup must not accept PlaylistEvent with NULL revision provenance."""
    now = datetime(2026, 7, 10, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    canonical_asset = "asset-canonical"
    canonical_uri = "file:///canonical.mp4"
    wrong_uri = "file:///wrong-null-provenance.mp4"

    canonical_rev, _item = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Canonical Program",
        asset_id_raw=canonical_asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=canonical_rev)

    block_id = _block_id_for(canonical_asset, start)
    _insert_playlist_event(
        db,
        channel_slug=channel.slug,
        broadcast_day=day,
        block_id=block_id,
        start_utc_ms=int(start.timestamp() * 1000),
        end_utc_ms=int((start + timedelta(minutes=30)).timestamp() * 1000),
        schedule_revision_id=None,
        asset_uri=wrong_uri,
    )
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    block = _load_and_get_current_block(svc, channel_slug=channel.slug, now=now, monkeypatch=monkeypatch)
    assert block is not None
    assert block.segments
    assert block.segments[0].asset_uri == canonical_uri


@pytest.mark.contract
def test_runtime_selects_only_canonical_revision_artifacts(db, channel, tmp_path, monkeypatch):
    """Runtime lookup must not use filled artifact whose revision != canonical pointer revision."""
    now = datetime(2026, 7, 11, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    asset = "asset-shared"
    canonical_uri = "file:///canonical-shared.mp4"
    stale_uri = "file:///stale-shared.mp4"

    old_rev, _ = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Old Program",
        asset_id_raw=asset,
        status="superseded",
    )
    canonical_rev, _ = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Canonical Program",
        asset_id_raw=asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=canonical_rev)

    block_id = _block_id_for(asset, start)
    _insert_playlist_event(
        db,
        channel_slug=channel.slug,
        broadcast_day=day,
        block_id=block_id,
        start_utc_ms=int(start.timestamp() * 1000),
        end_utc_ms=int((start + timedelta(minutes=30)).timestamp() * 1000),
        schedule_revision_id=old_rev.id,
        asset_uri=stale_uri,
    )
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    block = _load_and_get_current_block(svc, channel_slug=channel.slug, now=now, monkeypatch=monkeypatch)
    assert block is not None
    assert block.segments[0].asset_uri == canonical_uri


@pytest.mark.contract
def test_stale_artifacts_are_ineligible_after_revision_change(db, channel, tmp_path, monkeypatch):
    """After revision switch, stale old-revision artifact for same block id must not be selected."""
    now = datetime(2026, 7, 12, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    asset = "asset-reused"
    stale_uri = "file:///stale-after-switch.mp4"
    canonical_uri = "file:///canonical-after-switch.mp4"

    old_rev, _ = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Old Canonical",
        asset_id_raw=asset,
        status="superseded",
    )
    new_rev, _ = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="New Canonical",
        asset_id_raw=asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=new_rev)

    block_id = _block_id_for(asset, start)
    _insert_playlist_event(
        db,
        channel_slug=channel.slug,
        broadcast_day=day,
        block_id=block_id,
        start_utc_ms=int(start.timestamp() * 1000),
        end_utc_ms=int((start + timedelta(minutes=30)).timestamp() * 1000),
        schedule_revision_id=old_rev.id,
        asset_uri=stale_uri,
    )
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    block = _load_and_get_current_block(svc, channel_slug=channel.slug, now=now, monkeypatch=monkeypatch)
    assert block is not None
    assert block.segments[0].asset_uri == canonical_uri


@pytest.mark.contract
def test_selected_block_is_traceable_to_schedule_source(db, channel, tmp_path, monkeypatch):
    """Runtime-selected current block must be traceable to schedule provenance identity."""
    now = datetime(2026, 7, 13, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    asset = "asset-traceable"

    rev, item = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Traceable Program",
        asset_id_raw=asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=rev)
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    block = _load_and_get_current_block(svc, channel_slug=channel.slug, now=now, monkeypatch=monkeypatch)
    assert block is not None

    expected_block_id = _block_id_for(asset, start)
    assert block.block_id == expected_block_id

    row = (
        db.query(PlaylistEvent)
        .filter(
            PlaylistEvent.channel_slug == channel.slug,
            PlaylistEvent.block_id == block.block_id,
        )
        .first()
    )
    assert row is not None
    assert row.schedule_revision_id == rev.id
    assert row.schedule_revision_id == item.schedule_revision_id


@pytest.mark.contract
def test_epg_and_runtime_content_share_revision_provenance(db, channel, tmp_path, monkeypatch):
    """EPG current item and runtime current block must share canonical revision provenance."""
    now = datetime(2026, 7, 14, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    asset = "asset-epg-runtime"

    rev, _item = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="EPG Runtime Same Program",
        asset_id_raw=asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=rev)
    db.commit()

    epg_blocks = DslScheduleService.get_canonical_epg(
        channel.slug,
        datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc),
    )
    assert epg_blocks
    current_epg = None
    for blk in epg_blocks:
        st = datetime.fromisoformat(blk["start_at"])
        en = st + timedelta(seconds=blk["slot_duration_sec"])
        if st <= now < en:
            current_epg = blk
            break
    assert current_epg is not None

    svc = _service_for_channel(channel.slug, tmp_path)
    block = _load_and_get_current_block(svc, channel_slug=channel.slug, now=now, monkeypatch=monkeypatch)
    assert block is not None

    row = (
        db.query(PlaylistEvent)
        .filter(
            PlaylistEvent.channel_slug == channel.slug,
            PlaylistEvent.block_id == block.block_id,
        )
        .first()
    )
    assert row is not None
    assert current_epg.get("schedule_revision_id") == str(row.schedule_revision_id)
    assert current_epg.get("title") == "EPG Runtime Same Program"


@pytest.mark.contract
def test_null_provenance_artifact_rejected_for_current_lookup(db, channel, tmp_path, monkeypatch):
    """Null-provenance PlaylistEvent must be ignored by current lookup helper."""
    now = datetime(2026, 7, 15, 12, 10, tzinfo=timezone.utc)
    start = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    day = start.date()
    asset = "asset-null-prov-helper"

    rev, _item = _insert_revision_with_item(
        db,
        channel=channel,
        broadcast_day=day,
        start_time=start,
        duration_sec=1800,
        title="Null Provenance Program",
        asset_id_raw=asset,
        status="active",
    )
    _set_pointer(db, channel=channel, broadcast_day=day, revision=rev)

    block_id = _block_id_for(asset, start)
    _insert_playlist_event(
        db,
        channel_slug=channel.slug,
        broadcast_day=day,
        block_id=block_id,
        start_utc_ms=int(start.timestamp() * 1000),
        end_utc_ms=int((start + timedelta(minutes=30)).timestamp() * 1000),
        schedule_revision_id=None,
        asset_uri="file:///null-helper.mp4",
    )
    db.commit()

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    ok, err = svc.load_schedule(channel.slug)
    assert ok, err

    filled = svc._get_filled_block_by_id(block_id)
    assert filled is None
