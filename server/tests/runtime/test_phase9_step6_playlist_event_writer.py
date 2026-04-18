"""
Phase 9 Step 6 — PlaylistBuilderDaemon is the sole writer of PlaylistEvent.

Invariants proven by this file:

1. `playlist_builder_daemon` exposes the three public migration
   functions: ``invalidate_future_for_channel``, ``purge_for_channels``,
   ``purge_all``.

2. No production module outside
   ``runtime/playlist_builder_daemon.py`` contains an ORM insert, ORM
   delete, or raw SQL mutation against ``PlaylistEvent`` /
   ``playlist_events``. That includes ``schedule_revision_writer.py``,
   ``channel_reconciliation.py``, ``channel_purge.py``, and every
   other production file.

3. Contract preservation for INV-PLAYLOG-SUPERSEDED-REVISION-001:
   ``invalidate_future_for_channel`` deletes rows with
   ``start_utc_ms >= boundary`` in the caller's session — same
   transaction, zero latency window. Historical rows are retained.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from uuid import uuid4

import pytest


_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "retrovue"
_DAEMON_PATH = _SRC_ROOT / "runtime" / "playlist_builder_daemon.py"

# -- Files intentionally skipped --------------------------------------------
#
# Files that cannot currently be parsed (pre-existing bug unrelated to
# this step). The IndentationError in ``cli/main.py:182-184`` was flagged
# in the Phase 9 Step 5 report and still exists; the guard cannot reason
# about it until the unrelated fix lands. When the file parses cleanly
# again, simply remove this entry.
_UNPARSEABLE = {
    _SRC_ROOT / "cli" / "main.py",
}

# Phase 9 Step 6 follow-up cleared this allow-list. The three modules
# (dsl_schedule_service, schedule_rebuild, schedule_reschedule) now route
# all PlaylistEvent mutations through the daemon module's public API.
# The empty set is intentional — re-adding an entry here should require
# an explicit architectural decision and a follow-up migration.
_ALLOW_LISTED_PENDING_MIGRATION: set[Path] = set()


# ---------------------------------------------------------------------------
# Daemon surface
# ---------------------------------------------------------------------------

def test_daemon_module_exposes_invalidate_future_for_channel():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "invalidate_future_for_channel", None)), (
        "Phase 9 Step 6 Stage B1: playlist_builder_daemon must expose "
        "invalidate_future_for_channel(db, *, channel_slug, boundary_utc)."
    )


def test_daemon_module_exposes_purge_for_channels():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "purge_for_channels", None)), (
        "Phase 9 Step 6 Stage B2: playlist_builder_daemon must expose "
        "purge_for_channels(db, channel_slugs)."
    )


def test_daemon_module_exposes_purge_all():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "purge_all", None)), (
        "Phase 9 Step 6 Stage B3: playlist_builder_daemon must expose "
        "purge_all(db)."
    )


# ---------------------------------------------------------------------------
# AST guard: no ORM writes on PlaylistEvent outside the daemon
# ---------------------------------------------------------------------------

def _iter_prod_modules() -> list[Path]:
    """All production .py files under `server/src/retrovue/` except:
    - the daemon itself (the owner),
    - files known-unparseable (pre-existing bugs unrelated to Step 6),
    - the three Phase 9 Step 6 *pending-migration* files.

    The guard enforces single-writer for every remaining module; adding a
    new writer in any of them fails CI.
    """
    out: list[Path] = []
    for p in _SRC_ROOT.rglob("*.py"):
        if p == _DAEMON_PATH:
            continue
        if p in _UNPARSEABLE:
            continue
        if p in _ALLOW_LISTED_PENDING_MIGRATION:
            continue
        out.append(p)
    return sorted(out)


_PROD_MODULES = _iter_prod_modules()


def _parse(path: Path) -> tuple[str, ast.AST]:
    src = path.read_text()
    return src, ast.parse(src, filename=str(path))


def _refers_to_playlist_event(node: ast.AST) -> bool:
    """True if the subtree references the `PlaylistEvent` Name or the
    `playlist_events` table via a string literal on `PlaylistEvent.__table__`.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == "PlaylistEvent":
            return True
    return False


def _orm_insert_or_delete_on_playlist_event(tree: ast.AST) -> list[tuple[int, str]]:
    """Catch:
       - db.add(PlaylistEvent(...))
       - db.merge(PlaylistEvent(...))
       - db.delete(<obj referencing PlaylistEvent>)
       - db.query(PlaylistEvent).filter(...).delete()
       - pg_insert(PlaylistEvent.__table__) / sa_insert(PlaylistEvent) / sa_delete(PlaylistEvent)
       - db.execute(sa_delete(PlaylistEvent)) / db.execute(sa_update(PlaylistEvent))
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # Case A: db.add / db.merge / db.delete (method-call shape) with
        # an argument referencing PlaylistEvent.
        if isinstance(func, ast.Attribute) and func.attr in {"add", "merge", "delete"}:
            if any(_refers_to_playlist_event(arg) for arg in node.args):
                hits.append((node.lineno, f".{func.attr}(PlaylistEvent...)"))
                continue

        # Case B: <chain>.delete() where the chain references PlaylistEvent
        # (covers db.query(PlaylistEvent).filter(...).delete() without args).
        if isinstance(func, ast.Attribute) and func.attr == "delete":
            if _refers_to_playlist_event(func.value):
                hits.append((node.lineno, ".delete()  chain(PlaylistEvent)"))
                continue

        # Case C: free-function forms. pg_insert / sa_insert / sa_delete /
        # sa_update / insert / delete / update — argument is
        # PlaylistEvent or PlaylistEvent.__table__.
        if isinstance(func, ast.Name) and func.id in {
            "pg_insert", "insert", "delete", "update",
        }:
            if any(_refers_to_playlist_event(arg) for arg in node.args):
                hits.append((node.lineno, f"{func.id}(PlaylistEvent...)"))
                continue

        # Case D: aliased (`from sqlalchemy import delete as sa_delete`)
        # — same Name.id check for known aliases.
        if isinstance(func, ast.Name) and func.id in {
            "sa_delete", "sa_update", "sa_insert",
        }:
            if any(_refers_to_playlist_event(arg) for arg in node.args):
                hits.append((node.lineno, f"{func.id}(PlaylistEvent...)"))
                continue
    return hits


@pytest.mark.parametrize("path", _PROD_MODULES, ids=lambda p: p.relative_to(_SRC_ROOT).as_posix())
def test_no_external_orm_mutation_on_playlist_event(path: Path):
    _src, tree = _parse(path)
    hits = _orm_insert_or_delete_on_playlist_event(tree)
    assert not hits, (
        f"{path.relative_to(_SRC_ROOT)} contains ORM mutation(s) on "
        f"PlaylistEvent at {hits}. Route through "
        "retrovue.runtime.playlist_builder_daemon (invalidate_future_for_channel "
        "/ purge_for_channels / purge_all)."
    )


# ---------------------------------------------------------------------------
# Raw SQL guard: no playlist_events mutation outside the daemon
# ---------------------------------------------------------------------------

_RAW_SQL_PATTERNS = (
    re.compile(r"INSERT\s+INTO\s+playlist_events\b", re.IGNORECASE),
    re.compile(r"UPDATE\s+playlist_events\b", re.IGNORECASE),
    re.compile(r"DELETE\s+FROM\s+playlist_events\b", re.IGNORECASE),
)


@pytest.mark.parametrize("path", _PROD_MODULES, ids=lambda p: p.relative_to(_SRC_ROOT).as_posix())
def test_no_external_raw_sql_on_playlist_events(path: Path):
    src = path.read_text()
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        for pat in _RAW_SQL_PATTERNS:
            if pat.search(line):
                offenders.append((i, line.strip()))
                break
    assert not offenders, (
        f"{path.relative_to(_SRC_ROOT)} contains raw SQL mutation(s) on "
        f"playlist_events at {offenders}. Route through the daemon module's "
        "public functions."
    )


# ---------------------------------------------------------------------------
# Contract: invalidate_future_for_channel preserves INV-PLAYLOG-SUPERSEDED-REVISION-001
# ---------------------------------------------------------------------------

def _mk_channel(db, slug: str):
    from retrovue.domain.entities import Channel
    db.add(Channel(
        slug=slug,
        title=slug,
        grid_block_minutes=30,
        kind="network",
        programming_day_start=__import__("datetime").time(6, 0),
        block_start_offsets_minutes=[0],
    ))


def _mk_playlist_event(db, slug: str, *, start_utc_ms: int, end_utc_ms: int):
    """Add one PlaylistEvent row. `block_id` is the composite PK; we make
    it unique per call so a single channel can own many rows."""
    from retrovue.domain.entities import PlaylistEvent
    from datetime import datetime, timezone
    block_id = f"phase9-{slug}-{start_utc_ms}"
    start_dt = datetime.fromtimestamp(start_utc_ms / 1000, tz=timezone.utc)
    db.add(PlaylistEvent(
        block_id=block_id,
        channel_slug=slug,
        broadcast_day=start_dt.date(),
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=[],
    ))


def test_invalidate_future_for_channel_removes_future_tail_and_retains_history():
    """INV-PLAYLOG-SUPERSEDED-REVISION-001: rows with start_utc_ms >= boundary
    are deleted; rows with start_utc_ms strictly before are retained.

    Runs in the caller's session (same transaction) — no latency window.
    """
    from datetime import datetime, timezone
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import invalidate_future_for_channel

    slug = f"phase9-step6-{uuid4().hex[:8]}"
    boundary = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    boundary_ms = int(boundary.timestamp() * 1000)
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()

            # Four rows: two historical (< boundary), two at/after (≥ boundary).
            for offset_ms in (-3_600_000, -1, 0, 3_600_000):
                _mk_playlist_event(
                    db, slug,
                    start_utc_ms=boundary_ms + offset_ms,
                    end_utc_ms=boundary_ms + offset_ms + 1_000,
                )
            db.flush()

            deleted = invalidate_future_for_channel(
                db, channel_slug=slug, boundary_utc=boundary,
            )
            assert deleted == 2, (
                f"expected 2 rows deleted (boundary-exact + future), got {deleted}"
            )

            remaining = (
                db.query(PlaylistEvent)
                .filter(PlaylistEvent.channel_slug == slug)
                .order_by(PlaylistEvent.start_utc_ms.asc())
                .all()
            )
            assert len(remaining) == 2, (
                f"two historical rows must remain, got {len(remaining)}"
            )
            assert all(r.start_utc_ms < boundary_ms for r in remaining)

            # Cleanup
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


def test_purge_window_for_channel_overlap_semantics():
    """Stage-follow-up contract: purge_window_for_channel deletes rows
    that *overlap* [start, end), including edge cases (boundary-start,
    boundary-end). Non-overlapping rows are preserved."""
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import purge_window_for_channel

    slug = f"phase9-rebuild-{uuid4().hex[:8]}"
    base_ms = 3_000_000_000_000
    win_start = base_ms + 1_000
    win_end = base_ms + 2_000
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()
            # Row A: entirely before window — keep
            _mk_playlist_event(db, slug, start_utc_ms=base_ms, end_utc_ms=base_ms + 500)
            # Row B: starts before, ends inside — overlap → delete
            _mk_playlist_event(db, slug, start_utc_ms=base_ms + 500, end_utc_ms=base_ms + 1_500)
            # Row C: entirely inside — delete
            _mk_playlist_event(db, slug, start_utc_ms=base_ms + 1_200, end_utc_ms=base_ms + 1_800)
            # Row D: starts inside, ends after — overlap → delete
            _mk_playlist_event(db, slug, start_utc_ms=base_ms + 1_900, end_utc_ms=base_ms + 2_500)
            # Row E: entirely after — keep
            _mk_playlist_event(db, slug, start_utc_ms=base_ms + 3_000, end_utc_ms=base_ms + 3_500)
            db.flush()

            deleted = purge_window_for_channel(
                db, channel_slug=slug,
                start_utc_ms=win_start, end_utc_ms=win_end,
            )
            assert deleted == 3

            remaining = (
                db.query(PlaylistEvent)
                .filter(PlaylistEvent.channel_slug == slug)
                .order_by(PlaylistEvent.start_utc_ms.asc())
                .all()
            )
            assert len(remaining) == 2
            assert remaining[0].start_utc_ms == base_ms
            assert remaining[1].start_utc_ms == base_ms + 3_000

            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


def test_purge_future_in_broadcast_day_for_channel_day_scope():
    """Stage-follow-up contract: purge_future_in_broadcast_day_for_channel
    deletes only rows (a) for this channel, (b) on this broadcast_day,
    (c) whose start_utc_ms is strictly greater than the threshold.
    Rows in other broadcast_days are preserved.
    """
    from datetime import date as date_type
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import (
        purge_future_in_broadcast_day_for_channel,
    )

    slug = f"phase9-resched-{uuid4().hex[:8]}"
    base_ms = 4_000_000_000_000
    today = date_type(2030, 6, 1)
    tomorrow = date_type(2030, 6, 2)
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()

            def _mk(day, start):
                from retrovue.domain.entities import PlaylistEvent as _PE
                db.add(_PE(
                    block_id=f"blk-{slug}-{day}-{start}",
                    channel_slug=slug,
                    broadcast_day=day,
                    start_utc_ms=start,
                    end_utc_ms=start + 500,
                    segments=[],
                ))

            # today past — keep
            _mk(today, base_ms + 0)
            # today at threshold — keep (strictly greater only)
            _mk(today, base_ms + 1_000)
            # today future — delete
            _mk(today, base_ms + 2_000)
            _mk(today, base_ms + 3_000)
            # tomorrow future — keep (different day)
            _mk(tomorrow, base_ms + 5_000)
            db.flush()

            deleted = purge_future_in_broadcast_day_for_channel(
                db,
                channel_slug=slug,
                broadcast_day=today,
                after_utc_ms=base_ms + 1_000,
            )
            assert deleted == 2

            remaining = (
                db.query(PlaylistEvent)
                .filter(PlaylistEvent.channel_slug == slug)
                .order_by(PlaylistEvent.broadcast_day.asc(), PlaylistEvent.start_utc_ms.asc())
                .all()
            )
            assert len(remaining) == 3
            assert [r.broadcast_day for r in remaining] == [today, today, tomorrow]

            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


def test_delete_block_by_id_and_idempotent_when_missing():
    """Stage-follow-up contract: delete_block removes the row with the
    given block_id and returns True. A second call returns False
    (idempotent on missing).
    """
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import delete_block

    slug = f"phase9-delblk-{uuid4().hex[:8]}"
    base_ms = 5_000_000_000_000
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()
            _mk_playlist_event(db, slug, start_utc_ms=base_ms, end_utc_ms=base_ms + 500)
            db.flush()
            block_id = f"phase9-{slug}-{base_ms}"

            first = delete_block(db, block_id=block_id)
            assert first is True

            db.flush()  # make the delete visible to subsequent queries

            second = delete_block(db, block_id=block_id)
            assert second is False

            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


def test_upsert_block_if_missing_preserves_existing_row():
    """Stage-follow-up contract: upsert_block_if_missing inserts a new
    row (returns True), or skips when the block_id already exists
    (returns False) and does NOT overwrite the existing row
    (INV-PLAYOUT-WRITE-ONCE-001).
    """
    from datetime import date as date_type
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import upsert_block_if_missing

    slug = f"phase9-upsert-{uuid4().hex[:8]}"
    base_ms = 6_000_000_000_000
    bday = date_type(2030, 6, 1)
    block_id = f"phase9-{slug}-keep-me"
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()
            inserted = upsert_block_if_missing(
                db,
                block_id=block_id,
                channel_slug=slug,
                broadcast_day=bday,
                start_utc_ms=base_ms,
                end_utc_ms=base_ms + 500,
                segments=[{"keep": "me"}],
            )
            assert inserted is True
            db.flush()

            # Second attempt with different segments must be skipped.
            inserted_again = upsert_block_if_missing(
                db,
                block_id=block_id,
                channel_slug=slug,
                broadcast_day=bday,
                start_utc_ms=base_ms,
                end_utc_ms=base_ms + 500,
                segments=[{"overwrite": "me"}],
            )
            assert inserted_again is False
            db.flush()

            row = db.query(PlaylistEvent).filter(PlaylistEvent.block_id == block_id).first()
            assert row is not None
            assert row.segments == [{"keep": "me"}]

            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


def test_upsert_block_merge_updates_existing_row():
    """Stage-follow-up contract: upsert_block_merge INSERTs or
    UPDATE-ALL-FIELDs — opposite semantic to upsert_block_if_missing.
    This matches the pre-migration ``db.merge`` semantic in
    ``rebuild_playlog_plan``.
    """
    from datetime import date as date_type
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import upsert_block_merge

    slug = f"phase9-mrg-{uuid4().hex[:8]}"
    base_ms = 7_000_000_000_000
    bday = date_type(2030, 6, 1)
    block_id = f"phase9-{slug}-merge-me"
    try:
        with session() as db:
            _mk_channel(db, slug)
            db.flush()
            upsert_block_merge(
                db,
                block_id=block_id,
                channel_slug=slug,
                broadcast_day=bday,
                start_utc_ms=base_ms,
                end_utc_ms=base_ms + 500,
                segments=[{"v": 1}],
            )
            db.flush()

            # Second call with different segments MUST overwrite.
            upsert_block_merge(
                db,
                block_id=block_id,
                channel_slug=slug,
                broadcast_day=bday,
                start_utc_ms=base_ms,
                end_utc_ms=base_ms + 500,
                segments=[{"v": 2}],
            )
            db.flush()

            row = db.query(PlaylistEvent).filter(PlaylistEvent.block_id == block_id).first()
            assert row is not None
            assert row.segments == [{"v": 2}]

            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug == slug).delete()
        raise


# ---------------------------------------------------------------------------
# Daemon follow-up API presence
# ---------------------------------------------------------------------------

def test_daemon_module_exposes_purge_window_for_channel():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "purge_window_for_channel", None))


def test_daemon_module_exposes_purge_future_in_broadcast_day_for_channel():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "purge_future_in_broadcast_day_for_channel", None))


def test_daemon_module_exposes_delete_block():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "delete_block", None))


def test_daemon_module_exposes_upsert_block_if_missing():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "upsert_block_if_missing", None))


def test_daemon_module_exposes_upsert_block_merge():
    from retrovue.runtime import playlist_builder_daemon as mod
    assert callable(getattr(mod, "upsert_block_merge", None))


def test_phase9_step6_followup_allow_list_is_empty():
    """No production module outside the daemon may retain exceptions
    for ``PlaylistEvent`` writes."""
    assert _ALLOW_LISTED_PENDING_MIGRATION == set(), (
        "The Phase 9 Step 6 follow-up cleared this allow-list. If you are "
        "re-adding an entry, make the architectural decision explicit and "
        "file a follow-up migration."
    )


def test_purge_for_channels_removes_only_listed_channels():
    """Stage B2 contract: purge_for_channels removes PlaylistEvent rows
    for the listed slugs and leaves other channels alone.
    """
    from retrovue.domain.entities import Channel, PlaylistEvent
    from retrovue.infra.uow import session
    from retrovue.runtime.playlist_builder_daemon import purge_for_channels

    slug_a = f"phase9-purge-a-{uuid4().hex[:8]}"
    slug_b = f"phase9-purge-b-{uuid4().hex[:8]}"
    base_ms = 2_000_000_000_000
    try:
        with session() as db:
            for slug in (slug_a, slug_b):
                _mk_channel(db, slug)
            db.flush()
            for slug in (slug_a, slug_b):
                for offset in range(2):
                    _mk_playlist_event(
                        db, slug,
                        start_utc_ms=base_ms + offset * 1000,
                        end_utc_ms=base_ms + offset * 1000 + 500,
                    )
            db.flush()

            deleted = purge_for_channels(db, [slug_a])
            assert deleted == 2

            a_rows = db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug_a).count()
            b_rows = db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug == slug_b).count()
            assert a_rows == 0
            assert b_rows == 2

            # Empty-list short-circuit: no-op.
            deleted_empty = purge_for_channels(db, [])
            assert deleted_empty == 0

            # Cleanup
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug.in_([slug_a, slug_b])).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug.in_([slug_a, slug_b])).delete(
                synchronize_session=False
            )
    except Exception:
        with session() as db:
            db.query(PlaylistEvent).filter(PlaylistEvent.channel_slug.in_([slug_a, slug_b])).delete(
                synchronize_session=False
            )
            db.query(Channel).filter(Channel.slug.in_([slug_a, slug_b])).delete(
                synchronize_session=False
            )
        raise
