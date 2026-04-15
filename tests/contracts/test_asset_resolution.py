"""
Contract tests for asset resolution behavior.

Contract: docs/contracts/asset_resolution.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import logging
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
from retrovue.infra import db as db_module
from retrovue.infra.settings import settings
from retrovue.runtime import dsl_schedule_service as dsl_mod
from retrovue.runtime.dsl_schedule_service import DslScheduleService
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


@pytest.fixture(autouse=True)
def _force_test_db(monkeypatch):
    if not settings.test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. Refusing to run asset resolution contract tests."
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


class _FakeResolver:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def lookup(self, asset_id: str):
        if asset_id not in self._mapping:
            raise KeyError(f"Asset not found: {asset_id}")
        return SimpleNamespace(file_uri=self._mapping[asset_id])


def _service_for_channel(channel_slug: str, tmp_path: Path) -> DslScheduleService:
    dsl_path = tmp_path / f"{channel_slug}.dsl"
    dsl_path.write_text("# asset resolution contract dsl\n", encoding="utf-8")
    return DslScheduleService(
        dsl_path=str(dsl_path),
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_ms=3_650_000,
        channel_slug=channel_slug,
        resolved_config=load_defaults(),
    )


def _schedule_for_asset(asset_id: str, *, start: datetime, duration_sec: int = 1800) -> dict:
    return {
        "version": "program-schedule.v2",
        "source": {"compiler_version": "contract"},
        "hash": f"sha256:{uuid_mod.uuid4().hex}",
        "program_blocks": [
            {
                "title": "Asset Resolution Test Block",
                "asset_id": asset_id,
                "start_at": start.isoformat(),
                "slot_duration_sec": duration_sec,
                "episode_duration_sec": duration_sec,
                "compiled_segments": [
                    {
                        "segment_type": "content",
                        "asset_id": asset_id,
                        "duration_ms": duration_sec * 1000,
                        "asset_start_offset_ms": 0,
                    }
                ],
            }
        ],
    }


def _expand_to_scheduled_blocks(self, schedule: dict, _resolver) -> list[ScheduledBlock]:
    out: list[ScheduledBlock] = []
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
        out.append(
            ScheduledBlock(
                block_id=f"asset-resolution-{idx}",
                start_utc_ms=start_ms,
                end_utc_ms=end_ms,
                segments=(seg,),
            )
        )
    return out


def _compile_with_mode(
    svc: DslScheduleService,
    monkeypatch,
    *,
    mode: str,
    schedule: dict,
    resolver: _FakeResolver,
) -> list[ScheduledBlock]:
    setattr(svc, "_asset_resolution_mode", mode)
    monkeypatch.setattr(dsl_mod, "parse_dsl", lambda _text: {"timezone": "UTC"})
    monkeypatch.setattr(dsl_mod, "compile_schedule", lambda *_args, **_kwargs: schedule)
    monkeypatch.setattr(DslScheduleService, "_expand_schedule_to_blocks", _expand_to_scheduled_blocks)
    monkeypatch.setattr(DslScheduleService, "_save_compiled_schedule", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(svc, "_get_resolver", lambda: resolver)
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(svc._clock, "now_utc", lambda: now)
    return svc._compile_day(svc._channel_slug or "asset-resolution", "2026-07-01", effective_day_open_ms=0)


@pytest.mark.contract
def test_strict_mode_rejects_unknown_asset(tmp_path, monkeypatch):
    """Strict mode must fail on unknown required assets."""
    channel_slug = f"asset-strict-{uuid_mod.uuid4().hex[:8]}"
    unknown_asset_id = str(uuid_mod.uuid4())
    schedule = _schedule_for_asset(
        unknown_asset_id,
        start=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    svc = _service_for_channel(channel_slug, tmp_path)

    with pytest.raises(RuntimeError):
        _compile_with_mode(
            svc,
            monkeypatch,
            mode="strict",
            schedule=schedule,
            resolver=_FakeResolver(mapping={}),
        )


@pytest.mark.contract
def test_tolerant_mode_allows_unknown_asset(tmp_path, monkeypatch):
    """Tolerant mode may continue and return a block."""
    channel_slug = f"asset-tolerant-{uuid_mod.uuid4().hex[:8]}"
    unknown_asset_id = str(uuid_mod.uuid4())
    schedule = _schedule_for_asset(
        unknown_asset_id,
        start=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    svc = _service_for_channel(channel_slug, tmp_path)

    blocks = _compile_with_mode(
        svc,
        monkeypatch,
        mode="tolerant",
        schedule=schedule,
        resolver=_FakeResolver(mapping={}),
    )
    assert blocks, "Expected tolerant mode to keep timeline continuity by returning a block."


@pytest.mark.contract
def test_degraded_block_is_flagged(tmp_path, monkeypatch):
    """Tolerant-mode block with unresolved assets must be explicitly degraded."""
    channel_slug = f"asset-degraded-{uuid_mod.uuid4().hex[:8]}"
    unknown_asset_id = str(uuid_mod.uuid4())
    schedule = _schedule_for_asset(
        unknown_asset_id,
        start=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    svc = _service_for_channel(channel_slug, tmp_path)

    blocks = _compile_with_mode(
        svc,
        monkeypatch,
        mode="tolerant",
        schedule=schedule,
        resolver=_FakeResolver(mapping={}),
    )
    assert blocks
    assert getattr(blocks[0], "is_degraded", False) is True, (
        "Unresolved asset in tolerant mode was not marked degraded."
    )


@pytest.mark.contract
def test_no_silent_skip_emits_degradation_signal(tmp_path, monkeypatch, caplog):
    """Skipping unresolved assets must emit an explicit degradation signal."""
    channel_slug = f"asset-nosilent-{uuid_mod.uuid4().hex[:8]}"
    unknown_asset_id = str(uuid_mod.uuid4())
    schedule = _schedule_for_asset(
        unknown_asset_id,
        start=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    svc = _service_for_channel(channel_slug, tmp_path)

    with caplog.at_level(logging.WARNING):
        blocks = _compile_with_mode(
            svc,
            monkeypatch,
            mode="tolerant",
            schedule=schedule,
            resolver=_FakeResolver(mapping={}),
        )

    assert blocks
    has_degraded_log = any("degraded" in rec.getMessage().lower() for rec in caplog.records)
    has_degraded_marker = getattr(blocks[0], "is_degraded", False) is True
    assert has_degraded_log or has_degraded_marker, (
        "Asset skip occurred without explicit degradation log or degraded marker."
    )


@pytest.mark.contract
def test_playable_block_passes_without_degraded_flag(tmp_path, monkeypatch):
    """Fully resolvable block should remain playable and non-degraded."""
    channel_slug = f"asset-playable-{uuid_mod.uuid4().hex[:8]}"
    playable_asset_id = str(uuid_mod.uuid4())
    schedule = _schedule_for_asset(
        playable_asset_id,
        start=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    svc = _service_for_channel(channel_slug, tmp_path)

    blocks = _compile_with_mode(
        svc,
        monkeypatch,
        mode="strict",
        schedule=schedule,
        resolver=_FakeResolver(mapping={playable_asset_id: "/media/playable.mp4"}),
    )
    assert blocks
    assert getattr(blocks[0], "is_degraded", False) is False
