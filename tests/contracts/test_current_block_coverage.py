"""
Contract tests for current block coverage at runtime startup.

Contract: docs/contracts/current_block_coverage.md
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
from retrovue.domain.entities import Channel, ScheduleRevision
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService
from retrovue.runtime.schedule_revision_writer import (
    write_active_revision_from_compiled_schedule,
)
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run current block coverage contract tests."
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
    slug = f"coverage-{uuid_mod.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid_mod.uuid4(),
        slug=slug,
        title="Current Block Coverage Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start="06:00",
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _schedule_with_blocks(starts: list[datetime], duration_sec: int = 1800) -> dict:
    blocks = []
    for start_dt in starts:
        blocks.append(
            {
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
        )
    return {
        "version": "program-schedule.v2",
        "source": {"compiler_version": "contract"},
        "hash": f"sha256:{uuid_mod.uuid4().hex}",
        "program_blocks": blocks,
    }


def _write_day_schedule(db, *, channel_slug: str, broadcast_day: date, starts: list[datetime]) -> bool:
    schedule = _schedule_with_blocks(starts)
    return write_active_revision_from_compiled_schedule(
        db,
        channel_slug=channel_slug,
        broadcast_day=broadcast_day,
        schedule=schedule,
        created_by="test_current_block_coverage",
    )


def _service_for_channel(channel_slug: str, tmp_path: Path) -> DslScheduleService:
    dsl_path = tmp_path / f"{channel_slug}.dsl"
    dsl_path.write_text("# current block coverage contract test dsl\n", encoding="utf-8")
    return DslScheduleService(
        dsl_path=str(dsl_path),
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_ms=3_650_000,
        channel_slug=channel_slug,
        resolved_config=load_defaults(),
    )


def _mock_compiler(schedule: dict):
    def _compile_schedule(*_args, **_kwargs):
        return schedule

    return _compile_schedule


def _expand_to_scheduled_blocks(self, schedule: dict, _resolver) -> list[ScheduledBlock]:
    result: list[ScheduledBlock] = []
    for idx, pb in enumerate(schedule.get("program_blocks", [])):
        start_dt = datetime.fromisoformat(pb["start_at"]).astimezone(timezone.utc)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = start_ms + int(pb["slot_duration_sec"] * 1000)
        seg = ScheduledSegment(
            segment_type="content",
            asset_uri=f"/assets/{idx}.mp4",
            asset_start_offset_ms=0,
            segment_duration_ms=end_ms - start_ms,
        )
        result.append(
            ScheduledBlock(
                block_id=f"blk-{channel_slug_hash(self._channel_slug)}-{idx}",
                start_utc_ms=start_ms,
                end_utc_ms=end_ms,
                segments=(seg,),
            )
        )
    return result


def channel_slug_hash(channel_slug: str) -> str:
    return uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, channel_slug).hex[:12]


@pytest.mark.contract
def test_in_progress_block_is_preserved(channel, tmp_path, monkeypatch):
    """Current block overlapping now must survive forward-only filtering."""
    now = datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc)
    overlapping_start = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    schedule = _schedule_with_blocks([overlapping_start])
    svc = _service_for_channel(channel.slug, tmp_path)

    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(dsl_mod, "compile_schedule", _mock_compiler(schedule))
    monkeypatch.setattr(DslScheduleService, "_expand_schedule_to_blocks", _expand_to_scheduled_blocks)
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)

    blocks = svc._compile_day(channel.slug, "2026-06-01", effective_day_open_ms=0)
    assert any(b.start_utc_ms <= int(now.timestamp() * 1000) < b.end_utc_ms for b in blocks), (
        "In-progress block was dropped despite overlapping now."
    )


@pytest.mark.contract
def test_fully_past_block_is_excluded(channel, tmp_path, monkeypatch):
    """Blocks fully in the past may be dropped under forward-only behavior."""
    now = datetime(2026, 6, 1, 12, 15, tzinfo=timezone.utc)
    past_start = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)  # ends 11:30
    schedule = _schedule_with_blocks([past_start])
    svc = _service_for_channel(channel.slug, tmp_path)

    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(dsl_mod, "compile_schedule", _mock_compiler(schedule))
    monkeypatch.setattr(DslScheduleService, "_expand_schedule_to_blocks", _expand_to_scheduled_blocks)
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)

    blocks = svc._compile_day(channel.slug, "2026-06-01", effective_day_open_ms=0)
    assert blocks == [], "Fully past block was not excluded."


@pytest.mark.contract
def test_get_block_at_returns_current_block(db, channel, tmp_path, monkeypatch):
    """Runtime lookup must return a block that contains now."""
    now = datetime(2026, 6, 2, 12, 15, tzinfo=timezone.utc)
    starts = [
        datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 2, 12, 30, tzinfo=timezone.utc),
    ]
    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=date(2026, 6, 2),
        starts=starts,
    )

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)

    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    now_ms = int(now.timestamp() * 1000)
    block = svc.get_block_at(channel.slug, now_ms)
    assert block is not None
    assert block.start_utc_ms <= now_ms < block.end_utc_ms


@pytest.mark.contract
def test_runtime_resolution_is_broadcast_day_aware(db, channel, tmp_path, monkeypatch):
    """Lookup at now must resolve the block from the correct broadcast day."""
    day_1 = date(2026, 6, 3)
    day_2 = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 7, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=day_1,
        starts=[datetime(2026, 6, 3, 6, 0, tzinfo=timezone.utc)],
    )
    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=day_2,
        starts=[datetime(2026, 6, 4, 6, 30, tzinfo=timezone.utc)],
    )

    svc = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)

    ok, err = svc.load_schedule(channel.slug)
    assert ok, err
    block = svc.get_block_at(channel.slug, now_ms)
    assert block is not None
    assert block.start_utc_ms <= now_ms < block.end_utc_ms
    # Day-2 block starts at 06:30 UTC and must be selected for 07:00 UTC.
    expected_start_ms = int(datetime(2026, 6, 4, 6, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert block.start_utc_ms == expected_start_ms


@pytest.mark.contract
def test_restart_preserves_current_coverage(db, channel, tmp_path, monkeypatch):
    """Reloading schedule service must preserve resolvability of current block."""
    now = datetime(2026, 6, 5, 12, 10, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    starts = [datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)]
    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=date(2026, 6, 5),
        starts=starts,
    )

    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})

    svc_1 = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(svc_1._clock, "now_utc", lambda: now)
    ok_1, err_1 = svc_1.load_schedule(channel.slug)
    assert ok_1, err_1
    block_1 = svc_1.get_block_at(channel.slug, now_ms)
    assert block_1 is not None

    svc_2 = _service_for_channel(channel.slug, tmp_path)
    monkeypatch.setattr(svc_2._clock, "now_utc", lambda: now)
    ok_2, err_2 = svc_2.load_schedule(channel.slug)
    assert ok_2, err_2
    block_2 = svc_2.get_block_at(channel.slug, now_ms)
    assert block_2 is not None
    assert block_1.block_id == block_2.block_id
    assert block_2.start_utc_ms <= now_ms < block_2.end_utc_ms


@pytest.mark.contract
def test_runtime_does_not_depend_on_single_active_revision_per_channel(db, channel):
    """Sanity guard: test setup requires multiple active revisions for one channel."""
    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=date(2026, 6, 6),
        starts=[datetime(2026, 6, 6, 6, 0, tzinfo=timezone.utc)],
    )
    assert _write_day_schedule(
        db,
        channel_slug=channel.slug,
        broadcast_day=date(2026, 6, 7),
        starts=[datetime(2026, 6, 7, 6, 0, tzinfo=timezone.utc)],
    )

    active = (
        db.query(ScheduleRevision)
        .filter(
            ScheduleRevision.channel_id == channel.id,
            ScheduleRevision.status == "active",
        )
        .all()
    )
    assert len(active) >= 2, (
        "Expected multiple active revisions across broadcast days for a single channel."
    )
