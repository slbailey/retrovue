"""
Target behavior for Scheduling Invariants v1.0 (time-splice model).

These tests encode INV-SCHEDULE-* and related IDs from docs/contracts/scheduling/.
They are expected to FAIL until splice persistence, single-channel active head,
overlap constraints, join validation, and cache versioning are implemented.

Tier 3 | PostgreSQL + MasterClock patches — deterministic, no wall-clock sleep.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    PlaylistEvent,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.infra import db as db_module
from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.schedule_revision_writer import (
    write_active_revision_from_compiled_schedule,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BDAY = date(2026, 6, 15)
_ANCHOR = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _slug(prefix: str = "inv") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_channel(db: Session, slug: str) -> Channel:
    ch = Channel(
        slug=slug,
        title=f"Inv Test {slug}",
        grid_block_minutes=30,
        kind="network",
        programming_day_start=time(6, 0),
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _cleanup_channel_slug(db: Session, slug: str) -> None:
    """Remove test channel and dependent rows (slug-scoped)."""
    try:
        db.rollback()
    except Exception:
        pass
    try:
        db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
            synchronize_session=False
        )
        ch = db.query(Channel).filter(Channel.slug == slug).first()
        if ch is not None:
            db.delete(ch)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _item_end_utc(it: ScheduleItem) -> datetime:
    return it.start_time + timedelta(seconds=int(it.duration_sec))


def _schedule_block(
    start: datetime,
    duration_sec: int,
    *,
    title: str = "block",
) -> dict:
    return {
        "title": title,
        "asset_id": str(uuid.uuid4()),
        "start_at": start.isoformat(),
        "slot_duration_sec": duration_sec,
        "episode_duration_sec": min(duration_sec, 1320),
        "content_type": "episode",
    }


def _open_raw_session() -> Session:
    """Session without auto-commit (for rollback proofs)."""
    engine = db_module.get_engine(for_test=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL required")
    return sessionmaker(bind=engine, future=True)()


# =============================================================================
# Group 1 — INV-SCHEDULE-TIME-IMMUTABILITY-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleTimeImmutability001:
    """Past and live ScheduleItem rows must not be mutated in place."""

    def test_direct_update_of_past_item_must_be_rejected(
        self, pg_session: Session
    ) -> None:
        slug = _slug("t1past")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            t_past = _ANCHOR - timedelta(hours=3)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=clock.now_utc(),
                created_by="test",
            )
            pg_session.add(rev)
            pg_session.flush()
            it = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=t_past,
                duration_sec=3600,
                content_type="episode",
                slot_index=0,
                metadata_={"title": "past"},
            )
            pg_session.add(it)
            pg_session.flush()

            # Target: DB or domain guard must reject mutating editorial fields
            # on sealed rows (end <= now when now is after item end).
            clock.advance(10_000.0)  # well past item end
            assert clock.now_utc() > _item_end_utc(it)

            try:
                pg_session.execute(
                    update(ScheduleItem)
                    .where(ScheduleItem.id == it.id)
                    .values(
                        duration_sec=7200,
                        metadata_={"title": "tampered"},
                    )
                )
                pg_session.commit()
            except Exception:
                pg_session.rollback()
                return

            pytest.fail(
                "INV-SCHEDULE-TIME-IMMUTABILITY-001: in-place update of sealed "
                "ScheduleItem must be rejected (trigger or guard missing)"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)

    def test_direct_update_of_live_item_must_be_rejected(
        self, pg_session: Session
    ) -> None:
        slug = _slug("t1live")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            t_live_start = _ANCHOR - timedelta(minutes=30)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=clock.now_utc(),
                created_by="test",
            )
            pg_session.add(rev)
            pg_session.flush()
            it = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=t_live_start,
                duration_sec=7200,
                content_type="episode",
                slot_index=0,
                metadata_={"title": "live"},
            )
            pg_session.add(it)
            pg_session.flush()

            clock.advance(60.0)  # inside [start, end)
            assert it.start_time <= clock.now_utc() < _item_end_utc(it)

            try:
                pg_session.execute(
                    update(ScheduleItem)
                    .where(ScheduleItem.id == it.id)
                    .values(metadata_={"title": "cut_live"})
                )
                pg_session.commit()
            except Exception:
                pg_session.rollback()
                return

            pytest.fail(
                "INV-SCHEDULE-TIME-IMMUTABILITY-001: in-place update of live "
                "ScheduleItem must be rejected"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)

    def test_future_item_may_be_updated_in_place_until_splice_locks_writer(
        self, pg_session: Session
    ) -> None:
        """Pending-only row: mutation may succeed today; documents mutable tail."""
        slug = _slug("t1fut")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            t_future = _ANCHOR + timedelta(hours=2)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=clock.now_utc(),
                created_by="test",
            )
            pg_session.add(rev)
            pg_session.flush()
            it = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=t_future,
                duration_sec=1800,
                content_type="episode",
                slot_index=0,
                metadata_={"title": "future"},
            )
            pg_session.add(it)
            pg_session.flush()

            assert clock.now_utc() < it.start_time
            pg_session.execute(
                update(ScheduleItem)
                .where(ScheduleItem.id == it.id)
                .values(metadata_={"title": "edited_future"})
            )
            pg_session.commit()
            pg_session.refresh(it)
            assert it.metadata_["title"] == "edited_future"
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 2 — INV-SCHEDULE-SPLICE-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleSplice001:
    """T_new = P ∥ S_new with exact preservation of P."""

    def test_splice_preserves_prefix_and_replaces_pending_suffix(
        self, pg_session: Session
    ) -> None:
        slug = _slug("spl")
        try:
            ch = _make_channel(pg_session, slug)
            # First write: all blocks start at/after anchor (future relative to boundary=anchor)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            b0 = _schedule_block(_ANCHOR, 1800, title="A")
            b1 = _schedule_block(_ANCHOR + timedelta(minutes=30), 1800, title="B")
            b2 = _schedule_block(_ANCHOR + timedelta(hours=1), 1800, title="C")
            sched = {
                "version": "program-schedule.v2",
                "source": {"compiler_version": "test"},
                "hash": "sha256:splice1",
                "program_blocks": [b0, b1, b2],
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                ok = write_active_revision_from_compiled_schedule(
                    pg_session,
                    channel_slug=slug,
                    broadcast_day=_BDAY,
                    schedule=sched,
                    created_by="test",
                )
            assert ok is True
            pg_session.commit()

            rev1 = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.broadcast_day == _BDAY,
                    ScheduleRevision.status == "active",
                )
                .one()
            )
            items_before = (
                pg_session.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev1.id)
                .order_by(ScheduleItem.slot_index)
                .all()
            )
            assert len(items_before) == 3

            # 12:00 A, 12:30 B, 13:00 C — at 12:45: A sealed, B live, C pending
            clock.advance(45 * 60.0)
            assert clock.now_utc() < _item_end_utc(items_before[1])
            assert clock.now_utc() < items_before[2].start_time, (
                "test setup: third block must still be pending"
            )
            last_end = _item_end_utc(items_before[1])

            # S_new: single future block starting exactly at last_end (replace C)
            s_new_only = [
                _schedule_block(last_end, 1800, title="C_replaced"),
            ]
            sched2 = {
                "version": "program-schedule.v2",
                "source": {"compiler_version": "test"},
                "hash": "sha256:splice2",
                "program_blocks": s_new_only,
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                ok2 = write_active_revision_from_compiled_schedule(
                    pg_session,
                    channel_slug=slug,
                    broadcast_day=_BDAY,
                    schedule=sched2,
                    created_by="test",
                )

            # Target: splice succeeds and T_new has 3 items: A,B unchanged editorially, new C
            assert ok2 is True, (
                "INV-SCHEDULE-SPLICE-001: splice publish must succeed when only "
                "pending tail is replaced (current writer refuses whole day)"
            )
            pg_session.commit()

            rev2 = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.broadcast_day == _BDAY,
                    ScheduleRevision.status == "active",
                )
                .one()
            )
            items_after = (
                pg_session.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev2.id)
                .order_by(ScheduleItem.slot_index)
                .all()
            )
            assert len(items_after) == 3
            assert items_after[0].metadata_["title"] == "A"
            assert items_after[1].metadata_["title"] == "B"
            assert items_after[2].metadata_["title"] == "C_replaced"
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 3 — INV-SINGLE-ACTIVE-REVISION-001
# =============================================================================


@pytest.mark.contract
class TestInvSingleActiveRevision001:
    """At most one active ScheduleRevision per channel (global)."""

    def test_only_one_active_revision_per_channel_globally(
        self, pg_session: Session
    ) -> None:
        slug = _slug("oneact")
        try:
            ch = _make_channel(pg_session, slug)
            d1 = date(2026, 7, 1)
            d2 = date(2026, 7, 2)
            now = datetime.now(timezone.utc)
            r1 = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=d1,
                status="active",
                activated_at=now,
                created_by="test",
            )
            r2 = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=d2,
                status="active",
                activated_at=now,
                created_by="test",
            )
            pg_session.add(r1)
            pg_session.add(r2)
            try:
                pg_session.commit()
            except Exception:
                pg_session.rollback()
                return

            n_active = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.status == "active",
                )
                .count()
            )
            assert n_active == 1, (
                "INV-SINGLE-ACTIVE-REVISION-001: must allow at most one active "
                f"revision per channel (found {n_active})"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 4 — INV-SCHEDULE-NO-OVERLAP-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleNoOverlap001:
    def test_overlapping_items_same_revision_rejected(
        self, pg_session: Session
    ) -> None:
        slug = _slug("overlap")
        try:
            ch = _make_channel(pg_session, slug)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=_ANCHOR,
                created_by="test",
            )
            pg_session.add(rev)
            pg_session.flush()
            t0 = _ANCHOR
            a = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=t0,
                duration_sec=3600,
                content_type="episode",
                slot_index=0,
                metadata_={},
            )
            b = ScheduleItem(
                schedule_revision_id=rev.id,
                start_time=t0 + timedelta(minutes=30),
                duration_sec=3600,
                content_type="episode",
                slot_index=1,
                metadata_={},
            )
            pg_session.add(a)
            pg_session.flush()
            try:
                pg_session.add(b)
                pg_session.flush()
                pg_session.commit()
            except Exception:
                pg_session.rollback()
                return

            pytest.fail(
                "INV-SCHEDULE-NO-OVERLAP-001: overlapping intervals must be rejected "
                "at flush (EXCLUDE or trigger)"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 5 — INV-SCHEDULE-ATOMIC-PUBLISH-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleAtomicPublish001:
    def test_mid_write_abort_leaves_no_new_active_revision(
        self, pg_session: Session
    ) -> None:
        slug = _slug("atomic")
        try:
            ch = _make_channel(pg_session, slug)
            pg_session.commit()
            db = _open_raw_session()
            try:
                ch2 = db.query(Channel).filter(Channel.slug == slug).one()
                before = (
                    db.query(ScheduleRevision)
                    .filter(ScheduleRevision.channel_id == ch2.id)
                    .count()
                )
                rev = ScheduleRevision(
                    channel_id=ch2.id,
                    broadcast_day=_BDAY,
                    status="active",
                    activated_at=_ANCHOR,
                    created_by="test",
                )
                db.add(rev)
                db.flush()
                raise RuntimeError("simulated failure before commit")
            except RuntimeError:
                db.rollback()
            finally:
                db.close()

            after = (
                pg_session.query(ScheduleRevision)
                .filter(ScheduleRevision.channel_id == ch.id)
                .count()
            )
            pg_session.expire_all()
            assert after == before, (
                "INV-SCHEDULE-ATOMIC-PUBLISH-001: rolled-back transaction must "
                "not leave ScheduleRevision rows visible"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 6 — INV-SCHEDULE-JOIN-INTEGRITY-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleJoinIntegrity001:
    def test_s_new_starting_before_last_end_rejected(
        self, pg_session: Session
    ) -> None:
        slug = _slug("join1")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            blocks = [
                _schedule_block(_ANCHOR, 1800, title="j1"),
                _schedule_block(_ANCHOR + timedelta(minutes=45), 1800, title="j2"),
            ]
            sched = {
                "version": "program-schedule.v2",
                "hash": "h",
                "program_blocks": blocks,
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                ok = write_active_revision_from_compiled_schedule(
                    pg_session,
                    channel_slug=slug,
                    broadcast_day=_BDAY,
                    schedule=sched,
                    created_by="test",
                )
            assert ok is True
            pg_session.commit()

            rev = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.status == "active",
                )
                .one()
            )
            items = (
                pg_session.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev.id)
                .order_by(ScheduleItem.slot_index)
                .all()
            )
            last_end = _item_end_utc(items[0])
            # Advance so item0 is committed, item1 pending
            clock.advance(4000.0)
            bad_start = last_end - timedelta(minutes=5)
            sched_bad = {
                "version": "program-schedule.v2",
                "hash": "h2",
                "program_blocks": [
                    _schedule_block(bad_start, 1800, title="bad"),
                ],
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                with pytest.raises(
                    (ValueError, RuntimeError),
                    match="join|last_end|suffix|S_new",
                ):
                    write_active_revision_from_compiled_schedule(
                        pg_session,
                        channel_slug=slug,
                        broadcast_day=_BDAY,
                        schedule=sched_bad,
                        created_by="test",
                    )
        finally:
            _cleanup_channel_slug(pg_session, slug)

    def test_gap_after_last_end_rejected_when_contiguity_required(
        self, pg_session: Session
    ) -> None:
        slug = _slug("join2")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            blocks = [
                _schedule_block(_ANCHOR, 1800, title="g1"),
                _schedule_block(_ANCHOR + timedelta(minutes=30), 1800, title="g2"),
            ]
            sched = {
                "version": "program-schedule.v2",
                "hash": "h",
                "program_blocks": blocks,
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                ok = write_active_revision_from_compiled_schedule(
                    pg_session,
                    channel_slug=slug,
                    broadcast_day=_BDAY,
                    schedule=sched,
                    created_by="test",
                )
            assert ok is True
            pg_session.commit()

            rev = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.status == "active",
                )
                .one()
            )
            items = (
                pg_session.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev.id)
                .order_by(ScheduleItem.slot_index)
                .all()
            )
            last_end = _item_end_utc(items[1])
            clock.advance(5000.0)
            gap_start = last_end + timedelta(minutes=10)
            sched_gap = {
                "version": "program-schedule.v2",
                "hash": "h3",
                "program_blocks": [
                    _schedule_block(gap_start, 1800, title="gap"),
                ],
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                with pytest.raises(
                    (ValueError, RuntimeError),
                    match="join|gap|last_end|contig",
                ):
                    write_active_revision_from_compiled_schedule(
                        pg_session,
                        channel_slug=slug,
                        broadcast_day=_BDAY,
                        schedule=sched_gap,
                        created_by="test",
                    )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 7 — INV-SCHEDULE-FUTURE-ONLY-MUTATION-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleFutureOnlyMutation001:
    def test_s_new_must_not_include_starts_at_or_before_boundary(
        self, pg_session: Session
    ) -> None:
        slug = _slug("futonly")
        try:
            ch = _make_channel(pg_session, slug)
            clock = ControllableMasterClock(epoch=_ANCHOR)
            boundary = clock.now_utc()
            past_block = _schedule_block(
                boundary - timedelta(minutes=1), 600, title="past_in_snew"
            )
            sched = {
                "version": "program-schedule.v2",
                "hash": "h",
                "program_blocks": [past_block],
            }
            with patch(
                "retrovue.runtime.schedule_revision_writer._clock", clock
            ):
                ok = write_active_revision_from_compiled_schedule(
                    pg_session,
                    channel_slug=slug,
                    broadcast_day=_BDAY,
                    schedule=sched,
                    created_by="test",
                )
            assert ok is True
            pg_session.commit()
            rev = (
                pg_session.query(ScheduleRevision)
                .filter(
                    ScheduleRevision.channel_id == ch.id,
                    ScheduleRevision.status == "active",
                )
                .one()
            )
            it = (
                pg_session.query(ScheduleItem)
                .filter(ScheduleItem.schedule_revision_id == rev.id)
                .one()
            )
            assert it.start_time > boundary, (
                "INV-SCHEDULE-FUTURE-ONLY-MUTATION-001: S_new must not persist "
                "items with start_time <= boundary"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 8 — INV-PLAYLOG-SUPERSEDED-REVISION-001
# =============================================================================


@pytest.mark.contract
class TestInvPlaylogSupersededRevision001:
    def test_future_playlist_events_from_superseded_revision_removed_on_splice(
        self, pg_session: Session
    ) -> None:
        slug = _slug("pl")
        try:
            ch = _make_channel(pg_session, slug)
            old_rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="superseded",
                activated_at=_ANCHOR,
                created_by="test",
            )
            pg_session.add(old_rev)
            pg_session.flush()
            future_ms = int((_ANCHOR + timedelta(hours=5)).timestamp() * 1000)
            pe = PlaylistEvent(
                block_id=f"{slug}_oldblk",
                channel_slug=slug,
                broadcast_day=_BDAY,
                start_utc_ms=future_ms,
                end_utc_ms=future_ms + 1_800_000,
                segments=[{"kind": "primary"}],
            )
            pg_session.add(pe)
            pg_session.commit()

            # Simulate successful splice to new revision (not implemented): expect cleanup
            new_rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=_ANCHOR,
                created_by="test2",
            )
            pg_session.add(new_rev)
            pg_session.commit()

            stale = (
                pg_session.query(PlaylistEvent)
                .filter(
                    PlaylistEvent.channel_slug == slug,
                    PlaylistEvent.start_utc_ms >= int(_ANCHOR.timestamp() * 1000),
                )
                .count()
            )
            assert stale == 0, (
                "INV-PLAYLOG-SUPERSEDED-REVISION-001: future playlog rows tied to "
                "superseded editorial state must be deleted or invalidated on splice"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 9 — INV-SCHEDULE-CANONICAL-DERIVATION-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleCanonicalDerivation001:
    def test_epg_playlog_playout_share_active_revision_id(
        self, pg_session: Session
    ) -> None:
        """Single editorial head: all read paths must agree on revision identity."""
        slug = _slug("canon")
        try:
            ch = _make_channel(pg_session, slug)
            rev = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=_ANCHOR,
                created_by="test",
            )
            pg_session.add(rev)
            pg_session.flush()
            ptr = ChannelActiveRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                schedule_revision_id=rev.id,
            )
            pg_session.add(ptr)
            pg_session.commit()

            pytest.fail(
                "INV-SCHEDULE-CANONICAL-DERIVATION-001: implement cross-read of "
                "schedule_revision_id from EPG, playlog horizon, and runtime plan"
            )
        finally:
            _cleanup_channel_slug(pg_session, slug)


# =============================================================================
# Group 10 — INV-SCHEDULE-REVISION-MONOTONICITY-001
# =============================================================================


@pytest.mark.contract
class TestInvScheduleRevisionMonotonicity001:
    def test_stale_cache_without_revision_must_not_win_after_publish(
        self, pg_session: Session
    ) -> None:
        slug = _slug("mono")
        try:
            ch = _make_channel(pg_session, slug)
            r1 = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="superseded",
                activated_at=_ANCHOR,
                created_by="a",
            )
            r2 = ScheduleRevision(
                channel_id=ch.id,
                broadcast_day=_BDAY,
                status="active",
                activated_at=_ANCHOR,
                created_by="b",
            )
            pg_session.add(r1)
            pg_session.add(r2)
            pg_session.flush()
            fake_cache = {"channel": slug, "blocks": [{"id": "stale"}]}
            active_id = (
                pg_session.execute(
                    select(ScheduleRevision.id).where(
                        ScheduleRevision.channel_id == ch.id,
                        ScheduleRevision.status == "active",
                    )
                )
                .scalar_one()
            )
            assert "revision_id" in fake_cache or "revision_seq" in fake_cache, (
                "INV-SCHEDULE-REVISION-MONOTONICITY-001: timeline cache must "
                "carry revision identity; stale dict must not serve future tail"
            )
            assert fake_cache.get("revision_id") == active_id
        finally:
            _cleanup_channel_slug(pg_session, slug)
