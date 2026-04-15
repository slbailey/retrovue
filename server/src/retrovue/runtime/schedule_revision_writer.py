"""Helpers for writing ScheduleRevision + ScheduleItem from compiler output.

Time-splice authority (INV-SCHEDULE-SPLICE-001, INV-SCHEDULE-FUTURE-ONLY-MUTATION-001):
- Preserves prefix P (items with start_time <= now) as copies into a new revision.
- Replaces pending tail with S_new from program_blocks (all starts strictly > now).
- Cold start (no active revision): persists all program_blocks (backfill-friendly).

INV-SCHEDULE-JOIN-INTEGRITY-001: after P is fixed, first S_new.start must equal the join
anchor (end of last item in P, or first pending old start when P is empty).

INV-SINGLE-ACTIVE-REVISION-001 / INV-SCHEDULE-ATOMIC-PUBLISH-001: insert R_new as draft,
materialize items, supersede every active revision for the channel, then activate R_new
in the same transaction (no commit until all steps succeed).

INV-SCHEDULE-TIME-IMMUTABILITY-001: SQL UPDATE/DELETE on sealed or live rows is blocked
via engine-level guards (see _register_schedule_item_immutability_guards).

INV-PLAYLOG-SUPERSEDED-REVISION-001: after publish, delete PlaylistEvent rows for this
channel with start_utc_ms >= publish boundary so Tier-2 future tail cannot reference
superseded editorial state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import logging
import uuid as uuid_mod
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.dml import Delete, Update

from retrovue.domain.entities import (
    Channel,
    ChannelActiveRevision,
    PlaylistEvent,
    ScheduleItem,
    ScheduleRevision,
)
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.schedule_cache_monotonicity import (
    bump_channel_schedule_revision_head,
)

logger = logging.getLogger(__name__)

# LAW-CLOCK: Single time authority for all scheduling decisions.
_clock = MasterClock()

# Engines that have schedule_item immutability listeners attached (id(engine)).
_GUARDED_ENGINE_IDS: set[int] = set()


def _parse_uuid(value: Any) -> uuid_mod.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid_mod.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid_mod.UUID(value)
        except ValueError:
            return None
    return None


def _infer_content_type(block: dict[str, Any]) -> str:
    """Infer ScheduleItem.content_type from V2 compiler block metadata."""
    selector = block.get("selector")
    if isinstance(selector, dict):
        if any(k in selector for k in ("rating_include", "rating_exclude", "max_duration_sec")):
            return "movie"

    ep_dur = block.get("episode_duration_sec", 0)
    if ep_dur and ep_dur > 3600:
        return "movie"

    title = str(block.get("title") or "").lower()
    if "movie" in title:
        return "movie"
    if "filler" in title:
        return "filler"
    if "bumper" in title:
        return "bumper"
    if "promo" in title:
        return "promo"
    if "station" in title and "id" in title:
        return "station_id"
    return "episode"


def _item_end_utc(start: datetime, duration_sec: int) -> datetime:
    return start + timedelta(seconds=int(duration_sec))


def _is_sealed(start: datetime, duration_sec: int, now: datetime) -> bool:
    return _item_end_utc(start, duration_sec) <= now


def _is_live(start: datetime, duration_sec: int, now: datetime) -> bool:
    end = _item_end_utc(start, duration_sec)
    return start <= now < end


def _coerce_execute_params(multiparams: Any, params: Any) -> dict[str, Any]:
    if multiparams:
        if isinstance(multiparams, (list, tuple)) and len(multiparams) > 0:
            first = multiparams[0]
            if isinstance(first, dict):
                return first
        if isinstance(multiparams, dict):
            return multiparams
    if isinstance(params, dict):
        return params
    if params is not None:
        try:
            return dict(params)
        except Exception:
            pass
    return {}


def _guard_schedule_items_sql(
    conn: Connection,
    clauseelement: Any,
    multiparams: Any,
    params: Any,
    execution_options: Any,
) -> None:
    """Block UPDATE/DELETE on sealed or live schedule_items (INV-SCHEDULE-TIME-IMMUTABILITY-001)."""
    if not isinstance(clauseelement, (Update, Delete)):
        return
    tbl = clauseelement.table
    if tbl is None or getattr(tbl, "name", None) != "schedule_items":
        return
    wc = clauseelement.whereclause
    if wc is None:
        raise ValueError(
            "INV-SCHEDULE-TIME-IMMUTABILITY-001: schedule_items UPDATE/DELETE must "
            "target specific rows (WHERE clause required)"
        )
    stmt = select(
        ScheduleItem.id,
        ScheduleItem.start_time,
        ScheduleItem.duration_sec,
    ).where(wc)
    now = _clock.now_utc()
    op = "update" if isinstance(clauseelement, Update) else "delete"

    param_sets: list[dict[str, Any]]
    if isinstance(multiparams, list) and multiparams:
        param_sets = [x for x in multiparams if isinstance(x, dict)]
        if not param_sets:
            param_sets = [_coerce_execute_params(multiparams, params)]
    else:
        param_sets = [_coerce_execute_params(multiparams, params)]

    for bind in param_sets:
        try:
            result = conn.execute(stmt, bind)
        except Exception as exc:
            raise ValueError(
                "INV-SCHEDULE-TIME-IMMUTABILITY-001: failed to validate schedule_items "
                f"mutation target: {exc}"
            ) from exc
        rows = result.fetchall()
        for row in rows:
            rid, st, dur = row[0], row[1], int(row[2])
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            else:
                st = st.astimezone(timezone.utc)
            if _is_sealed(st, dur, now) or _is_live(st, dur, now):
                raise ValueError(
                    f"INV-SCHEDULE-TIME-IMMUTABILITY-001: cannot {op} sealed or live "
                    f"schedule_item id={rid}"
                )


def _register_schedule_item_immutability_guards(engine: Engine) -> None:
    eid = id(engine)
    if eid in _GUARDED_ENGINE_IDS:
        return
    event.listen(engine, "before_execute", _guard_schedule_items_sql)
    _GUARDED_ENGINE_IDS.add(eid)


def _ensure_guards_for_session_bind(db: Any) -> None:
    try:
        bind = db.get_bind()
        if isinstance(bind, Engine):
            _register_schedule_item_immutability_guards(bind)
    except Exception:
        pass


def _schedule_item_from_block(
    revision_id: uuid_mod.UUID,
    slot_index: int,
    block: dict[str, Any],
) -> ScheduleItem:
    start_at = datetime.fromisoformat(block["start_at"])
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    else:
        start_at = start_at.astimezone(timezone.utc)
    return ScheduleItem(
        schedule_revision_id=revision_id,
        start_time=start_at,
        duration_sec=int(block["slot_duration_sec"]),
        asset_id=_parse_uuid(block.get("asset_id")),
        container_id=_parse_uuid(block.get("collection")),
        content_type=_infer_content_type(block),
        window_uuid=_parse_uuid(block.get("window_uuid")),
        slot_index=slot_index,
        metadata_={
            "title": block.get("title"),
            "asset_id_raw": block.get("asset_id"),
            "collection_raw": block.get("collection"),
            "selector": block.get("selector"),
            "episode_duration_sec": block.get("episode_duration_sec"),
            "compiled_segments": block.get("compiled_segments"),
        },
    )


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _join_anchor_from_old_items(
    old_items: list[ScheduleItem], now: datetime
) -> datetime | None:
    """Point in time (UTC) where the first S_new block must start when contiguity is required.

    - If prefix P is non-empty: end time of the last item in P (start_time <= now).
    - If P is empty but a pending tail exists: start_time of the first pending item.
    - If there are no items: no anchor (cold tail within an empty revision).
    """
    prefix = [it for it in old_items if _normalize_utc(it.start_time) <= now]
    pending = [it for it in old_items if _normalize_utc(it.start_time) > now]
    if prefix:
        last = prefix[-1]
        return _item_end_utc(_normalize_utc(last.start_time), int(last.duration_sec))
    if pending:
        return _normalize_utc(pending[0].start_time)
    return None


def _assert_join_contiguous(first_start: datetime, join_point: datetime) -> None:
    fs = _normalize_utc(first_start)
    jp = _normalize_utc(join_point)
    delta = (fs - jp).total_seconds()
    if abs(delta) < 1e-6:
        return
    if delta < 0:
        raise ValueError(
            "INV-SCHEDULE-JOIN-INTEGRITY-001: join|last_end|suffix|S_new "
            f"overlap first={fs.isoformat()} last_end={jp.isoformat()}"
        )
    raise ValueError(
        "INV-SCHEDULE-JOIN-INTEGRITY-001: join|gap|last_end|contig "
        f"gap first={fs.isoformat()} last_end={jp.isoformat()}"
    )


def _invalidate_future_playlist_events_for_channel(
    db: Any,
    *,
    channel_slug: str,
    boundary_utc: datetime,
) -> int:
    """Remove Tier-2 playlog plan rows from the publish instant forward (same transaction).

    Rows with start_utc_ms strictly before the boundary are retained (sealed / historical
    materialization). Rows starting at or after the boundary are removed so no future
    instant can read a PlaylistEvent tied to a superseded revision's tail.
    """
    ms = int(_normalize_utc(boundary_utc).timestamp() * 1000)
    deleted = (
        db.query(PlaylistEvent)
        .filter(
            PlaylistEvent.channel_slug == channel_slug,
            PlaylistEvent.start_utc_ms >= ms,
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        logger.debug(
            "playlog_future_invalidate channel_slug=%s boundary_utc_ms=%s deleted=%s",
            channel_slug,
            ms,
            deleted,
        )
    return int(deleted or 0)


def _copy_preserved_item(
    src: ScheduleItem,
    revision_id: uuid_mod.UUID,
    slot_index: int,
) -> ScheduleItem:
    meta = deepcopy(src.metadata_) if src.metadata_ is not None else None
    return ScheduleItem(
        schedule_revision_id=revision_id,
        start_time=src.start_time,
        duration_sec=int(src.duration_sec),
        asset_id=src.asset_id,
        container_id=src.container_id,
        content_type=src.content_type,
        window_uuid=src.window_uuid,
        slot_index=slot_index,
        metadata_=meta,
    )


def write_active_revision_from_compiled_schedule(
    db,
    *,
    channel_slug: str,
    broadcast_day: date,
    schedule: dict[str, Any],
    created_by: str = "dsl_schedule_service",
) -> bool:
    """Write relational schedule rows from compiled schedule output (time-splice).

    Raises:
        ValueError: empty program_blocks, invalid S_new times, or splice validation failure.

    Returns:
        True when relational rows were written.

    Unknown channel: returns False (backward compatible with callers that skip silently).
    """
    _ensure_guards_for_session_bind(db)

    channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
    if channel is None:
        logger.warning(
            "ScheduleRevision dual-write skipped: unknown channel slug=%s",
            channel_slug,
        )
        return False

    blocks = schedule.get("program_blocks", [])
    if not blocks:
        raise ValueError(
            "INV-PERSISTENCE-GUARD-NONEMPTY-001: program_blocks must not be empty "
            f"for {channel_slug}/{broadcast_day}"
        )

    now = _clock.now_utc()

    # Serialize publishes per channel (all active rows for this channel).
    _lock_actives = db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.status == "active",
    )
    if hasattr(_lock_actives, "with_for_update"):
        _lock_actives = _lock_actives.with_for_update()
    _lock_actives.all()

    _rev_q = db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.broadcast_day == broadcast_day,
        ScheduleRevision.status == "active",
    )
    existing_active = _rev_q.first()

    # Parse and normalize all incoming block starts
    parsed_blocks: list[tuple[datetime, dict[str, Any]]] = []
    for block in blocks:
        start_at = datetime.fromisoformat(block["start_at"])
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        else:
            start_at = start_at.astimezone(timezone.utc)
        parsed_blocks.append((start_at, block))

    if existing_active is None:
        # Cold start: compiler is authoritative for the requested broadcast_day.
        # Blocks may lie entirely in the past relative to wall clock (backfill / late materialize).
        pass
    else:
        # Splice: S_new must be strictly future-only (pending tail)
        for start_at, _block in parsed_blocks:
            if start_at <= now:
                raise ValueError(
                    "INV-SCHEDULE-FUTURE-ONLY-MUTATION-001: S_new items must have "
                    f"start_time > now (got start={start_at.isoformat()}, now={now.isoformat()})"
                )

    old_items_snapshot: list[ScheduleItem] = []
    if existing_active is not None:
        old_items_snapshot = (
            db.query(ScheduleItem)
            .filter(ScheduleItem.schedule_revision_id == existing_active.id)
            .order_by(ScheduleItem.slot_index)
            .all()
        )

    if existing_active is not None and parsed_blocks:
        join_point = _join_anchor_from_old_items(old_items_snapshot, now)
        if join_point is not None:
            _assert_join_contiguous(parsed_blocks[0][0], join_point)

    publish_ts = _clock.now_utc()

    revision = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=broadcast_day,
        status="draft",
        activated_at=None,
        created_by=created_by,
        metadata_={
            "source": schedule.get("source"),
            "hash": schedule.get("hash"),
            "version": schedule.get("version"),
        },
    )
    db.add(revision)
    db.flush()

    slot = 0
    if existing_active is not None:
        prefix = [it for it in old_items_snapshot if _normalize_utc(it.start_time) <= now]
        for src in prefix:
            db.add(_copy_preserved_item(src, revision.id, slot))
            slot += 1

    for start_at, block in parsed_blocks:
        db.add(_schedule_item_from_block(revision.id, slot, block))
        slot += 1

    # Supersede every active revision for this channel, then activate the new row in one txn.
    db.query(ScheduleRevision).filter(
        ScheduleRevision.channel_id == channel.id,
        ScheduleRevision.status == "active",
    ).update(
        {"status": "superseded", "superseded_at": publish_ts},
        synchronize_session=False,
    )

    revision.status = "active"
    revision.activated_at = publish_ts
    db.flush()

    upsert_stmt = (
        pg_insert(ChannelActiveRevision.__table__)
        .values(
            channel_id=channel.id,
            broadcast_day=broadcast_day,
            schedule_revision_id=revision.id,
            updated_at=publish_ts,
        )
        .on_conflict_do_update(
            index_elements=["channel_id", "broadcast_day"],
            set_={
                "schedule_revision_id": revision.id,
                "updated_at": publish_ts,
            },
        )
    )
    db.execute(upsert_stmt)

    _invalidate_future_playlist_events_for_channel(
        db,
        channel_slug=channel_slug,
        boundary_utc=publish_ts,
    )

    bump_channel_schedule_revision_head(channel_slug, str(revision.id))

    return True


# Register immutability guards on the default app engine at import (production).
try:
    from retrovue.infra import db as _db_mod

    _register_schedule_item_immutability_guards(_db_mod.engine)
except Exception:
    # Tests or minimal imports may not have DB configured yet.
    pass
