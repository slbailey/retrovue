"""
Contract tests: Channel Reconciliation — INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH,
INV-CHANNEL-RECONCILE-DELETE, INV-CHANNEL-RECONCILE-IDEMPOTENT

Validates that reconciling channels against a YAML slug set creates missing
channels, deletes removed channels (with all derived state), and is idempotent.

Contract: docs/contracts/channel_reconciliation.md

These tests require a live Postgres database. Each test uses a SAVEPOINT so
the database is unchanged after the test run.

The reconcile implementation does not exist yet. These tests import
`reconcile_channels` from `retrovue.runtime.channel_reconciliation` and will
skip at collection time until that module is created.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import text

try:
    from retrovue.runtime.channel_reconciliation import reconcile_channels
except ImportError:
    pytest.skip(
        "retrovue.runtime.channel_reconciliation not yet implemented",
        allow_module_level=True,
    )

from retrovue.domain.entities import (
    Asset,
    Channel,
    ChannelActiveRevision,
    Collection,
    PlaylistEvent,
    Program,
    ProgramLogDay,
    ScheduleItem,
    SchedulePlan,
    ScheduleRevision,
    SerialRun,
    Source,
    TrafficPlayLog,
    Zone,
)
from retrovue.infra.uow import session as db_session

# ---------------------------------------------------------------------------
# Canonical list of channel-scoped tables removed on channel deletion.
# Must match docs/contracts/channel_purge.md § Tables Removed.
# ---------------------------------------------------------------------------
CHANNEL_SCOPED_TABLES = [
    "channels",
    "programs",
    "schedule_plans",
    "zones",
    "schedule_revisions",
    "schedule_items",
    "channel_active_revisions",
    "serial_runs",
    "program_log_days",
    "traffic_play_log",
    "playlist_events",
]

# Non-FK tables that require explicit deletion (string-keyed, no CASCADE).
NON_FK_TABLES = [
    "program_log_days",
    "traffic_play_log",
    "playlist_events",
]


# ---------------------------------------------------------------------------
# Helpers — same patterns as test_channel_purge.py
# ---------------------------------------------------------------------------

def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_source(db) -> Source:
    src = Source(
        external_id=f"test-source-{_uid().hex[:8]}",
        name="Test Source",
        type="filesystem",
    )
    db.add(src)
    db.flush()
    return src


def _make_collection(db, source: Source) -> Collection:
    coll = Collection(
        source_id=source.id,
        external_id=f"test-coll-{_uid().hex[:8]}",
        name="Test Collection",
    )
    db.add(coll)
    db.flush()
    return coll


def _make_asset(db, collection: Collection) -> Asset:
    asset = Asset(
        collection_uuid=collection.uuid,
        canonical_key=f"test/{_uid().hex[:8]}.mp4",
        canonical_key_hash=_uid().hex[:64],
        uri=f"/media/test/{_uid().hex[:8]}.mp4",
        size=1024,
        state="ready",
        discovered_at=_now(),
    )
    db.add(asset)
    db.flush()
    return asset


def _make_channel(db, slug: str | None = None) -> Channel:
    ch = Channel(
        slug=slug or f"test-ch-{_uid().hex[:8]}",
        title="Test Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start=time(6, 0),
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    return ch


def _make_full_broadcast_state(db, channel: Channel, asset: Asset) -> None:
    """Create one row in every channel-scoped table for the given channel."""
    plan = SchedulePlan(channel_id=channel.id, name=f"plan-{_uid().hex[:8]}")
    db.add(plan)
    db.flush()

    db.add(Zone(plan_id=plan.id, name="Zone", start_time=time(6, 0), end_time=time(12, 0)))

    db.add(Program(
        channel_id=channel.id, plan_id=plan.id, start_time="08:00",
        duration=60, content_type="asset", content_ref=str(asset.uuid),
    ))

    rev = ScheduleRevision(channel_id=channel.id, broadcast_day=date.today(), status="active")
    db.add(rev)
    db.flush()

    db.add(ScheduleItem(
        schedule_revision_id=rev.id, start_time=_now(),
        duration_sec=3600, content_type="episode", slot_index=0,
    ))

    db.add(ChannelActiveRevision(
        channel_id=channel.id, broadcast_day=date.today(), schedule_revision_id=rev.id,
    ))

    db.add(SerialRun(
        run_name=f"run-{_uid().hex[:8]}", channel_id=channel.id,
        placement_time=time(20, 0), placement_days=127,
        content_source_id=str(asset.uuid), content_source_type="program",
        anchor_datetime=_now(), anchor_episode_index=0,
    ))

    # Non-FK tables (string-keyed)
    db.add(ProgramLogDay(
        channel_id=channel.slug, broadcast_day=date.today(),
        schedule_hash="abc123", program_log_json={"items": []},
    ))
    db.add(TrafficPlayLog(
        channel_slug=channel.slug, asset_uuid=asset.uuid,
        asset_uri=asset.uri, asset_type="commercial", duration_ms=30_000,
    ))
    db.add(PlaylistEvent(
        block_id=f"block-{_uid().hex[:8]}", channel_slug=channel.slug,
        broadcast_day=date.today(), start_utc_ms=1_700_000_000_000,
        end_utc_ms=1_700_001_800_000, segments=[{"segment_type": "content"}],
    ))
    db.flush()


def _count(db, table_name: str) -> int:
    result = db.execute(text(f"SELECT count(*) FROM {table_name}"))
    return result.scalar()


def _count_where(db, table_name: str, column: str, value: str) -> int:
    result = db.execute(
        text(f"SELECT count(*) FROM {table_name} WHERE {column} = :v"),
        {"v": value},
    )
    return result.scalar()


def _channel_slugs(db) -> set[str]:
    rows = db.execute(text("SELECT slug FROM channels")).fetchall()
    return {r[0] for r in rows}


# ===========================================================================
# INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH — YAML is authoritative
# ===========================================================================


class TestChannelConfigSourceOfTruth:
    """INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH: DB channel set equals YAML set after reconcile."""

    def test_yaml_channel_added(self):
        """Channel in YAML but not in DB is created."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                yaml_slugs = {"new-channel-alpha"}
                reconcile_channels(db, yaml_slugs)

                assert _channel_slugs(db) == yaml_slugs, (
                    "INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH: DB must contain "
                    "exactly the channels declared in YAML"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e) or "no such table" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_yaml_channel_removed(self):
        """Channel in DB but not in YAML is deleted."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                ch = _make_channel(db, slug="doomed-channel")

                # YAML set does not include the DB channel
                yaml_slugs: set[str] = set()
                reconcile_channels(db, yaml_slugs)

                assert _count(db, "channels") == 0, (
                    "INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH: channel absent from "
                    "YAML must be deleted"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_mixed_add_and_remove(self):
        """Reconcile adds missing channels and removes extra channels."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                # Pre-existing channels
                _make_channel(db, slug="keep-me")
                _make_channel(db, slug="remove-me")

                yaml_slugs = {"keep-me", "add-me"}
                reconcile_channels(db, yaml_slugs)

                db_slugs = _channel_slugs(db)
                assert db_slugs == yaml_slugs, (
                    f"INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH: expected {yaml_slugs}, "
                    f"got {db_slugs}"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise


# ===========================================================================
# INV-CHANNEL-RECONCILE-DELETE — Removed channels lose all derived state
# ===========================================================================


class TestChannelReconcileDelete:
    """INV-CHANNEL-RECONCILE-DELETE: Deleted channels lose all derived broadcast state."""

    def test_removed_channel_derived_state_deleted(self):
        """All channel-scoped tables emptied for a removed channel."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                ch = _make_channel(db, slug="to-remove")
                _make_full_broadcast_state(db, ch, asset)

                # Verify broadcast state exists
                assert _count(db, "channels") >= 1
                assert _count(db, "programs") >= 1
                assert _count(db, "zones") >= 1

                # Reconcile with empty YAML — channel removed
                reconcile_channels(db, set())

                for table in CHANNEL_SCOPED_TABLES:
                    assert _count(db, table) == 0, (
                        f"INV-CHANNEL-RECONCILE-DELETE: {table} must be empty "
                        f"after removing last channel"
                    )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_surviving_channel_state_preserved(self):
        """Channels still in YAML retain all their derived state."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                keep = _make_channel(db, slug="survivor")
                remove = _make_channel(db, slug="condemned")
                _make_full_broadcast_state(db, keep, asset)
                _make_full_broadcast_state(db, remove, asset)

                # Snapshot survivor's state
                survivor_programs = _count_where(db, "programs", "channel_id", str(keep.id))
                survivor_plans = _count_where(db, "schedule_plans", "channel_id", str(keep.id))
                survivor_pld = _count_where(db, "program_log_days", "channel_id", keep.slug)
                survivor_tpl = _count_where(db, "traffic_play_log", "channel_slug", keep.slug)
                survivor_pe = _count_where(db, "playlist_events", "channel_slug", keep.slug)
                assert survivor_programs >= 1
                assert survivor_plans >= 1

                # Remove only condemned
                reconcile_channels(db, {"survivor"})

                # Condemned is gone
                assert _count_where(db, "channels", "slug", "condemned") == 0

                # Survivor state intact
                assert _count_where(db, "programs", "channel_id", str(keep.id)) == survivor_programs
                assert _count_where(db, "schedule_plans", "channel_id", str(keep.id)) == survivor_plans
                assert _count_where(db, "program_log_days", "channel_id", keep.slug) == survivor_pld
                assert _count_where(db, "traffic_play_log", "channel_slug", keep.slug) == survivor_tpl
                assert _count_where(db, "playlist_events", "channel_slug", keep.slug) == survivor_pe

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_catalog_tables_preserved(self):
        """Reconcile MUST NOT modify media catalog tables."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                sources_before = _count(db, "sources")
                collections_before = _count(db, "collections")
                assets_before = _count(db, "assets")

                ch = _make_channel(db, slug="will-die")
                _make_full_broadcast_state(db, ch, asset)

                reconcile_channels(db, set())

                assert _count(db, "sources") == sources_before
                assert _count(db, "collections") == collections_before
                assert _count(db, "assets") == assets_before

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_non_fk_tables_cleaned_for_removed_channel(self):
        """Non-FK tables (string-keyed) are explicitly cleaned for removed channels."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                ch = _make_channel(db, slug="non-fk-test")
                _make_full_broadcast_state(db, ch, asset)

                # Verify non-FK rows exist
                assert _count_where(db, "program_log_days", "channel_id", ch.slug) >= 1
                assert _count_where(db, "traffic_play_log", "channel_slug", ch.slug) >= 1
                assert _count_where(db, "playlist_events", "channel_slug", ch.slug) >= 1

                reconcile_channels(db, set())

                for table in NON_FK_TABLES:
                    assert _count(db, table) == 0, (
                        f"INV-CHANNEL-RECONCILE-DELETE: {table} must be empty — "
                        f"Postgres CASCADE does not reach string-keyed tables"
                    )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise


# ===========================================================================
# INV-CHANNEL-RECONCILE-IDEMPOTENT — Reconciliation is idempotent
# ===========================================================================


class TestChannelReconcileIdempotent:
    """INV-CHANNEL-RECONCILE-IDEMPOTENT: Running reconcile twice is a no-op."""

    def test_double_reconcile_no_error(self):
        """Running reconcile twice with the same set must not raise."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                _make_channel(db, slug="stable")
                yaml_slugs = {"stable"}

                reconcile_channels(db, yaml_slugs)
                reconcile_channels(db, yaml_slugs)

                assert _channel_slugs(db) == yaml_slugs

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_double_reconcile_unchanged_counts(self):
        """Row counts unchanged after second reconcile with same input."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                ch = _make_channel(db, slug="steady")
                _make_full_broadcast_state(db, ch, asset)

                yaml_slugs = {"steady"}
                reconcile_channels(db, yaml_slugs)

                # Snapshot after first reconcile
                counts_after_first = {
                    t: _count(db, t) for t in CHANNEL_SCOPED_TABLES
                }
                assets_after_first = _count(db, "assets")

                reconcile_channels(db, yaml_slugs)

                # All counts unchanged
                for t in CHANNEL_SCOPED_TABLES:
                    assert _count(db, t) == counts_after_first[t], (
                        f"INV-CHANNEL-RECONCILE-IDEMPOTENT: {t} count changed "
                        f"on second reconcile"
                    )
                assert _count(db, "assets") == assets_after_first

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_reconcile_empty_system_no_error(self):
        """Reconcile on an empty system with empty YAML must succeed."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                reconcile_channels(db, set())
                assert _count(db, "channels") == 0

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise


# ===========================================================================
# Transaction isolation
# ===========================================================================
#
# Each test wraps its work in a SAVEPOINT (db.begin_nested()) and rolls it
# back at the end, so tests never commit rows to the real database. The
# outer db_session() context manager sees no pending changes and its
# commit is a no-op.
