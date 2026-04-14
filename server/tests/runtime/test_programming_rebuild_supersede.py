"""
Regression: programming rebuild --channel must supersede active ScheduleRevision rows.

SQLAlchemy rejects Query.update() after join(); filter by channel via subquery instead.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from typer.testing import CliRunner

from retrovue.cli.commands.programming import app as programming_app
from retrovue.domain.entities import Channel, ChannelActiveRevision, ScheduleRevision
from retrovue.infra.uow import session as db_session

try:
    from sqlalchemy import inspect as sa_inspect
    from retrovue.infra.db import engine

    _inspector = sa_inspect(engine)
    _required_tables = {"channels", "schedule_revisions", "channel_active_revisions"}
    _existing = set(_inspector.get_table_names())
    if not _required_tables.issubset(_existing):
        pytest.skip(
            f"DB tables missing ({_required_tables - _existing}); run alembic upgrade head",
            allow_module_level=True,
        )
except Exception:
    pytest.skip("Cannot inspect DB for required tables", allow_module_level=True)


def _cleanup_channel(db, slug: str) -> None:
    ch = db.query(Channel).filter(Channel.slug == slug).first()
    if ch:
        db.delete(ch)
        db.flush()


@pytest.mark.contract
def test_programming_rebuild_with_channel_supersedes_without_join_update_error():
    """Rebuild with --channel runs bulk update; must not use join (InvalidRequestError)."""
    slug = "test-prog-rebuild-supersede"
    broadcast_day = date(2026, 4, 13)
    runner = CliRunner()

    with db_session() as db:
        _cleanup_channel(db, slug)
        ch = Channel(
            slug=slug,
            title="Rebuild Supersede Test",
            grid_block_minutes=30,
            kind="network",
            programming_day_start=time(6, 0),
            block_start_offsets_minutes=[0],
        )
        db.add(ch)
        db.flush()
        rev = ScheduleRevision(
            channel_id=ch.id,
            broadcast_day=broadcast_day,
            status="active",
            activated_at=datetime.now(timezone.utc),
            created_by="test_rebuild_supersede",
        )
        db.add(rev)
        db.flush()
        db.add(
            ChannelActiveRevision(
                channel_id=ch.id,
                broadcast_day=broadcast_day,
                schedule_revision_id=rev.id,
            )
        )

    result = runner.invoke(
        programming_app,
        ["rebuild", broadcast_day.isoformat(), "--channel", slug],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    with db_session() as db:
        ch2 = db.query(Channel).filter(Channel.slug == slug).one()
        updated = (
            db.query(ScheduleRevision)
            .filter(
                ScheduleRevision.channel_id == ch2.id,
                ScheduleRevision.broadcast_day == broadcast_day,
            )
            .one()
        )
        assert updated.status == "superseded"
        ptr = (
            db.query(ChannelActiveRevision)
            .filter(
                ChannelActiveRevision.channel_id == ch2.id,
                ChannelActiveRevision.broadcast_day == broadcast_day,
            )
            .first()
        )
        assert ptr is None, "rebuild must clear ChannelActiveRevision so timeline can recompile"

        _cleanup_channel(db, slug)
