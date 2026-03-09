"""
Contract tests: Channel Purge — INV-CHANNEL-PURGE-001, 002, 003

Validates that purging all channels removes all channel-scoped broadcast
state while preserving media catalog data.

Contract: docs/contracts/channel_purge.md

These tests require a live Postgres database. They create real rows,
invoke purge, and verify post-state. Each test uses a SAVEPOINT so the
database is unchanged after the test run.

The purge implementation does not exist yet. These tests import
`purge_all_channels` from `retrovue.runtime.channel_purge` and will
skip at collection time until that module is created.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import text

try:
    from retrovue.runtime.channel_purge import purge_all_channels
except ImportError:
    pytest.skip(
        "retrovue.runtime.channel_purge not yet implemented",
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
# Canonical list of channel-scoped tables removed by purge.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_source(db) -> Source:
    """Create a minimal Source (preserved table) and flush."""
    src = Source(
        external_id=f"test-source-{_uid().hex[:8]}",
        name="Test Source",
        type="filesystem",
    )
    db.add(src)
    db.flush()
    return src


def _make_collection(db, source: Source) -> Collection:
    """Create a minimal Collection (preserved table) and flush."""
    coll = Collection(
        source_id=source.id,
        external_id=f"test-coll-{_uid().hex[:8]}",
        name="Test Collection",
    )
    db.add(coll)
    db.flush()
    return coll


def _make_asset(db, collection: Collection) -> Asset:
    """Create a minimal Asset (preserved table) and flush."""
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
    """Create a minimal Channel and flush."""
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


def _make_full_broadcast_state(db, channel: Channel, asset: Asset) -> dict:
    """Create one row in every channel-scoped table. Returns IDs for verification."""
    ids: dict[str, list] = {
        "programs": [],
        "schedule_plans": [],
        "zones": [],
        "schedule_revisions": [],
        "schedule_items": [],
        "channel_active_revisions": [],
        "serial_runs": [],
        "program_log_days": [],
        "traffic_play_log": [],
        "playlist_events": [],
    }

    # SchedulePlan (FK cascade from channel)
    plan = SchedulePlan(
        channel_id=channel.id,
        name=f"plan-{_uid().hex[:8]}",
    )
    db.add(plan)
    db.flush()
    ids["schedule_plans"].append(plan.id)

    # Zone (FK cascade from plan)
    zone = Zone(
        plan_id=plan.id,
        name="Test Zone",
        start_time=time(6, 0),
        end_time=time(12, 0),
    )
    db.add(zone)
    db.flush()
    ids["zones"].append(zone.id)

    # Program (FK cascade from channel + plan)
    prog = Program(
        channel_id=channel.id,
        plan_id=plan.id,
        start_time="08:00",
        duration=60,
        content_type="asset",
        content_ref=str(asset.uuid),
    )
    db.add(prog)
    db.flush()
    ids["programs"].append(prog.id)

    # ScheduleRevision (FK cascade from channel)
    rev = ScheduleRevision(
        channel_id=channel.id,
        broadcast_day=date.today(),
        status="active",
    )
    db.add(rev)
    db.flush()
    ids["schedule_revisions"].append(rev.id)

    # ScheduleItem (FK cascade from revision)
    item = ScheduleItem(
        schedule_revision_id=rev.id,
        start_time=_now(),
        duration_sec=3600,
        content_type="episode",
        slot_index=0,
    )
    db.add(item)
    db.flush()
    ids["schedule_items"].append(item.id)

    # ChannelActiveRevision (FK cascade from channel)
    car = ChannelActiveRevision(
        channel_id=channel.id,
        broadcast_day=date.today(),
        schedule_revision_id=rev.id,
    )
    db.add(car)
    db.flush()
    ids["channel_active_revisions"].append(car.id)

    # SerialRun (FK cascade from channel)
    sr = SerialRun(
        run_name=f"run-{_uid().hex[:8]}",
        channel_id=channel.id,
        placement_time=time(20, 0),
        placement_days=127,  # daily
        content_source_id=str(asset.uuid),
        content_source_type="program",
        anchor_datetime=_now(),
        anchor_episode_index=0,
    )
    db.add(sr)
    db.flush()
    ids["serial_runs"].append(sr.id)

    # --- Non-FK tables (INV-CHANNEL-PURGE-003) ---

    # ProgramLogDay (string channel_id, no FK)
    pld = ProgramLogDay(
        channel_id=str(channel.slug),
        broadcast_day=date.today(),
        schedule_hash="abc123",
        program_log_json={"items": []},
    )
    db.add(pld)
    db.flush()
    ids["program_log_days"].append(pld.id)

    # TrafficPlayLog (string channel_slug, no FK)
    tpl = TrafficPlayLog(
        channel_slug=channel.slug,
        asset_uuid=asset.uuid,
        asset_uri=asset.uri,
        asset_type="commercial",
        duration_ms=30_000,
    )
    db.add(tpl)
    db.flush()
    ids["traffic_play_log"].append(tpl.id)

    # PlaylistEvent (string channel_slug, no FK)
    pe = PlaylistEvent(
        block_id=f"block-{_uid().hex[:8]}",
        channel_slug=channel.slug,
        broadcast_day=date.today(),
        start_utc_ms=1_700_000_000_000,
        end_utc_ms=1_700_001_800_000,
        segments=[{"segment_type": "content", "asset_uri": asset.uri}],
    )
    db.add(pe)
    db.flush()
    ids["playlist_events"].append(pe.block_id)

    return ids


# ---------------------------------------------------------------------------
# Count helpers — raw SQL to avoid ORM caching
# ---------------------------------------------------------------------------

def _count(db, table_name: str) -> int:
    """Count rows in a table using raw SQL."""
    result = db.execute(text(f"SELECT count(*) FROM {table_name}"))
    return result.scalar()


# ===========================================================================
# INV-CHANNEL-PURGE-001 — Full broadcast state removal
# ===========================================================================


class TestChannelPurge001:
    """INV-CHANNEL-PURGE-001: Purge removes all channel-scoped broadcast state."""

    def test_all_channel_scoped_tables_emptied(self):
        """Create a channel with full derived state, purge, assert all empty."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                # Preserved catalog state
                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                # Channel + full broadcast state
                channel = _make_channel(db)
                _make_full_broadcast_state(db, channel, asset)

                # Verify rows exist before purge
                assert _count(db, "channels") >= 1
                assert _count(db, "programs") >= 1
                assert _count(db, "schedule_plans") >= 1
                assert _count(db, "zones") >= 1
                assert _count(db, "schedule_revisions") >= 1
                assert _count(db, "schedule_items") >= 1
                assert _count(db, "channel_active_revisions") >= 1
                assert _count(db, "serial_runs") >= 1
                assert _count(db, "program_log_days") >= 1
                assert _count(db, "traffic_play_log") >= 1
                assert _count(db, "playlist_events") >= 1

                # Purge
                purge_all_channels(db)

                # Assert all channel-scoped tables are empty
                for table in CHANNEL_SCOPED_TABLES:
                    assert _count(db, table) == 0, (
                        f"INV-CHANNEL-PURGE-001: {table} must be empty after purge, "
                        f"found {_count(db, table)} rows"
                    )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e) or "no such table" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_multiple_channels_all_removed(self):
        """Purge removes state for all channels, not just one."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                ch1 = _make_channel(db, slug="purge-ch1")
                ch2 = _make_channel(db, slug="purge-ch2")
                _make_full_broadcast_state(db, ch1, asset)
                _make_full_broadcast_state(db, ch2, asset)

                assert _count(db, "channels") >= 2

                purge_all_channels(db)

                for table in CHANNEL_SCOPED_TABLES:
                    assert _count(db, table) == 0, (
                        f"INV-CHANNEL-PURGE-001: {table} not empty after multi-channel purge"
                    )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_preserved_catalog_tables_unchanged(self):
        """Purge MUST NOT modify media catalog tables."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                # Snapshot catalog counts before channel creation
                sources_before = _count(db, "sources")
                collections_before = _count(db, "collections")
                assets_before = _count(db, "assets")

                channel = _make_channel(db)
                _make_full_broadcast_state(db, channel, asset)

                purge_all_channels(db)

                # Catalog tables must be unchanged.
                # We verify a representative subset of the 17 preserved tables
                # listed in the contract. The guarantee is that purge only
                # deletes from the channel-scoped tables listed in
                # CHANNEL_SCOPED_TABLES, so verifying the primary catalog
                # tables suffices.
                assert _count(db, "sources") == sources_before, (
                    "INV-CHANNEL-PURGE-001: sources must be preserved"
                )
                assert _count(db, "collections") == collections_before, (
                    "INV-CHANNEL-PURGE-001: collections must be preserved"
                )
                assert _count(db, "assets") == assets_before, (
                    "INV-CHANNEL-PURGE-001: assets must be preserved"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise


# ===========================================================================
# INV-CHANNEL-PURGE-002 — Idempotency
# ===========================================================================


class TestChannelPurge002:
    """INV-CHANNEL-PURGE-002: Purge is idempotent."""

    def test_double_purge_no_error(self):
        """Running purge twice must not raise."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                channel = _make_channel(db)
                _make_full_broadcast_state(db, channel, asset)

                purge_all_channels(db)
                # Second purge on empty state must not raise
                purge_all_channels(db)

                assert _count(db, "channels") == 0

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_purge_empty_system_no_error(self):
        """Purge on a system with no channels must succeed."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                # No channels created — purge should be a no-op
                purge_all_channels(db)
                assert _count(db, "channels") == 0

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_double_purge_preserves_catalog(self):
        """Catalog tables unchanged after two sequential purges."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)

                assets_before = _count(db, "assets")
                collections_before = _count(db, "collections")

                channel = _make_channel(db)
                _make_full_broadcast_state(db, channel, asset)

                purge_all_channels(db)
                purge_all_channels(db)

                assert _count(db, "assets") == assets_before
                assert _count(db, "collections") == collections_before

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise


# ===========================================================================
# INV-CHANNEL-PURGE-003 — Non-cascaded tables require explicit cleanup
# ===========================================================================


class TestChannelPurge003:
    """INV-CHANNEL-PURGE-003: Non-FK tables are explicitly cleaned."""

    def test_program_log_days_cleaned(self):
        """program_log_days (string channel_id, no FK) must be emptied."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                channel = _make_channel(db)
                pld = ProgramLogDay(
                    channel_id=channel.slug,
                    broadcast_day=date.today(),
                    schedule_hash="test-hash",
                    program_log_json={"items": []},
                )
                db.add(pld)
                db.flush()

                assert _count(db, "program_log_days") >= 1

                purge_all_channels(db)

                assert _count(db, "program_log_days") == 0, (
                    "INV-CHANNEL-PURGE-003: program_log_days must be explicitly "
                    "deleted — Postgres CASCADE does not reach string-keyed tables"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_traffic_play_log_cleaned(self):
        """traffic_play_log (string channel_slug, no FK to channels) must be emptied."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)
                channel = _make_channel(db)

                tpl = TrafficPlayLog(
                    channel_slug=channel.slug,
                    asset_uuid=asset.uuid,
                    asset_uri=asset.uri,
                    asset_type="commercial",
                    duration_ms=30_000,
                )
                db.add(tpl)
                db.flush()

                assert _count(db, "traffic_play_log") >= 1

                purge_all_channels(db)

                assert _count(db, "traffic_play_log") == 0, (
                    "INV-CHANNEL-PURGE-003: traffic_play_log must be explicitly "
                    "deleted — Postgres CASCADE does not reach string-keyed tables"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_playlist_events_cleaned(self):
        """playlist_events (string channel_slug, no FK to channels) must be emptied."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                channel = _make_channel(db)

                pe = PlaylistEvent(
                    block_id=f"block-{_uid().hex[:8]}",
                    channel_slug=channel.slug,
                    broadcast_day=date.today(),
                    start_utc_ms=1_700_000_000_000,
                    end_utc_ms=1_700_001_800_000,
                    segments=[{"type": "content"}],
                )
                db.add(pe)
                db.flush()

                assert _count(db, "playlist_events") >= 1

                purge_all_channels(db)

                assert _count(db, "playlist_events") == 0, (
                    "INV-CHANNEL-PURGE-003: playlist_events must be explicitly "
                    "deleted — Postgres CASCADE does not reach string-keyed tables"
                )

                sp.rollback()

        except Exception as e:
            if "does not exist" in str(e):
                pytest.skip(f"Required table not yet migrated: {e}")
            raise

    def test_all_three_non_fk_tables_in_single_purge(self):
        """All three non-cascaded tables cleaned in one purge operation."""
        try:
            with db_session() as db:
                sp = db.begin_nested()

                source = _make_source(db)
                coll = _make_collection(db, source)
                asset = _make_asset(db, coll)
                channel = _make_channel(db)

                # Insert into all three non-FK tables
                db.add(ProgramLogDay(
                    channel_id=channel.slug,
                    broadcast_day=date.today(),
                    schedule_hash="h1",
                    program_log_json={"items": []},
                ))
                db.add(TrafficPlayLog(
                    channel_slug=channel.slug,
                    asset_uuid=asset.uuid,
                    asset_uri=asset.uri,
                    asset_type="promo",
                    duration_ms=15_000,
                ))
                db.add(PlaylistEvent(
                    block_id=f"block-{_uid().hex[:8]}",
                    channel_slug=channel.slug,
                    broadcast_day=date.today(),
                    start_utc_ms=1_700_000_000_000,
                    end_utc_ms=1_700_001_800_000,
                    segments=[],
                ))
                db.flush()

                purge_all_channels(db)

                assert _count(db, "program_log_days") == 0
                assert _count(db, "traffic_play_log") == 0
                assert _count(db, "playlist_events") == 0

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
#
# INV-CHANNEL-PURGE-001 requires single-transaction execution with rollback
# on failure. Testing this properly would require injecting a fault mid-purge
# and verifying the DB is unchanged. This is not practical because:
#
# 1. purge_all_channels() does not expose hook points for fault injection.
# 2. Mocking db.execute to fail partway through would couple tests to
#    implementation order, which the contract explicitly does not specify.
# 3. The UoW session() context manager already guarantees rollback-on-exception
#    via its try/except/rollback pattern (retrovue.infra.uow).
#
# Rollback-on-failure verification belongs at the integration layer.
