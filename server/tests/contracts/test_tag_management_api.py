"""Contract tests for tag management API endpoints.

INV-TAG-RENAME-ATOMIC-001: Tag rename/merge operations are atomic.
INV-TAG-SUMMARY-COMPLETE-001: Tag summary includes all tags and orphaned palette entries.

These tests validate the Studio API tag management endpoints using
a real Postgres test database.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid

import psycopg
import pytest

# ---------------------------------------------------------------------------
# Skip entirely if no Postgres connection available
# ---------------------------------------------------------------------------
PGDSN = os.environ.get("PGDSN", "host=192.168.1.50 dbname=retrovue user=retrovue")


def _pg_available():
    try:
        conn = psycopg.connect(PGDSN)
        conn.close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(not _pg_available(), reason="Postgres not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_conn():
    """Provide a Postgres connection that rolls back after each test."""
    conn = psycopg.connect(PGDSN)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def sqlite_palette(tmp_path):
    """Create a temporary SQLite palette database."""
    db_path = str(tmp_path / "retrovue.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE tag_palette (category TEXT, tag TEXT, color_bg TEXT, color_fg TEXT, "
        "PRIMARY KEY (category, tag))"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def test_container_uuid(pg_conn):
    """Get or create a test container for inserting test assets."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT uuid FROM containers LIMIT 1")
        row = cur.fetchone()
        if row:
            return row[0]
        # Create a minimal source + container if none exist
        src_uuid = uuid.uuid4()
        cont_uuid = uuid.uuid4()
        cur.execute(
            "INSERT INTO sources(uuid, name, source_type, base_path) "
            "VALUES(%s, 'test', 'local_directory', '/tmp/test') ON CONFLICT DO NOTHING",
            (src_uuid,),
        )
        cur.execute(
            "INSERT INTO containers(uuid, source_id, name, path) VALUES(%s, %s, 'test', '/tmp/test')",
            (cont_uuid, src_uuid),
        )
        return cont_uuid


def _insert_asset(cur, container_uuid, uri_suffix="test.mp4"):
    """Insert a test asset and return its UUID."""
    asset_uuid = uuid.uuid4()
    cur.execute(
        "INSERT INTO assets(uuid, container_id, uri, state) VALUES(%s, %s, %s, 'ready')",
        (asset_uuid, container_uuid, f"file:///tmp/test/{uri_suffix}"),
    )
    return asset_uuid


def _insert_tag(cur, asset_uuid, tag, source="operator"):
    cur.execute(
        "INSERT INTO asset_tags(asset_uuid, tag, source) VALUES(%s, %s, %s) ON CONFLICT DO NOTHING",
        (asset_uuid, tag, source),
    )


def _count_tag(cur, tag):
    cur.execute("SELECT COUNT(*) FROM asset_tags WHERE tag = %s", (tag,))
    return cur.fetchone()[0]


# ===========================================================================
# Tag Summary — INV-TAG-SUMMARY-COMPLETE-001
# ===========================================================================


@requires_pg
class TestTagSummary:
    """Tag summary endpoint returns complete namespace-grouped counts."""

    def test_summary_groups_by_namespace(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "s1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "s2.mp4")
            _insert_tag(cur, a1, "tag.hbo")
            _insert_tag(cur, a2, "tag.hbo")
            _insert_tag(cur, a1, "network.cbs")

        from retrovue.web.studio import _build_tag_summary

        result = _build_tag_summary(pg_conn, None)
        assert "tag" in result["namespaces"]
        assert "network" in result["namespaces"]

        hbo_entry = next(e for e in result["namespaces"]["tag"] if e["canonical"] == "tag.hbo")
        assert hbo_entry["asset_count"] == 2

        cbs_entry = next(e for e in result["namespaces"]["network"] if e["canonical"] == "network.cbs")
        assert cbs_entry["asset_count"] == 1

    def test_summary_includes_source_breakdown(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "src1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "src2.mp4")
            _insert_tag(cur, a1, "tag.classic", source="ingest")
            _insert_tag(cur, a2, "tag.classic", source="operator")

        from retrovue.web.studio import _build_tag_summary

        result = _build_tag_summary(pg_conn, None)
        classic = next(e for e in result["namespaces"]["tag"] if e["canonical"] == "tag.classic")
        assert classic["sources"]["ingest"] == 1
        assert classic["sources"]["operator"] == 1

    def test_summary_includes_orphaned_palette_tags(self, pg_conn, sqlite_palette):
        db = sqlite3.connect(sqlite_palette)
        db.execute("INSERT INTO tag_palette VALUES('TAG', 'orphan_tag', '#000', '#fff')")
        db.commit()
        db.close()

        from retrovue.web.studio import _build_tag_summary

        result = _build_tag_summary(pg_conn, sqlite_palette)
        orphaned_names = [o["tag"] for o in result["orphaned"]]
        assert "orphan_tag" in orphaned_names


# ===========================================================================
# Tag Rename — INV-TAG-RENAME-ATOMIC-001
# ===========================================================================


@requires_pg
class TestTagRename:
    """Tag rename is atomic and handles dedup."""

    def test_rename_updates_all_assets(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "r1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "r2.mp4")
            _insert_tag(cur, a1, "tag.oldname")
            _insert_tag(cur, a2, "tag.oldname")

        from retrovue.web.studio import _execute_tag_rename

        result = _execute_tag_rename(pg_conn, "tag.oldname", "tag.newname", None)
        assert result["affected_assets"] == 2

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.oldname") == 0
            assert _count_tag(cur, "tag.newname") == 2

    def test_rename_deduplicates_when_target_exists(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "rd1.mp4")
            _insert_tag(cur, a1, "tag.src")
            _insert_tag(cur, a1, "tag.dst")  # already has target

            a2 = _insert_asset(cur, test_container_uuid, "rd2.mp4")
            _insert_tag(cur, a2, "tag.src")  # only has source

        from retrovue.web.studio import _execute_tag_rename

        result = _execute_tag_rename(pg_conn, "tag.src", "tag.dst", None)
        assert result["deduped"] == 1  # a1 had both
        assert result["affected_assets"] == 2

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.src") == 0
            assert _count_tag(cur, "tag.dst") == 2

    def test_rename_noop_when_tag_absent(self, pg_conn):
        from retrovue.web.studio import _execute_tag_rename

        result = _execute_tag_rename(pg_conn, "tag.nonexistent", "tag.whatever", None)
        assert result["affected_assets"] == 0
        assert result["deduped"] == 0


# ===========================================================================
# Tag Merge
# ===========================================================================


@requires_pg
class TestTagMerge:
    """Tag merge deletes source, keeps target."""

    def test_merge_moves_assets_to_target(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "m1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "m2.mp4")
            _insert_tag(cur, a1, "tag.source_tag")
            _insert_tag(cur, a2, "tag.target_tag")

        from retrovue.web.studio import _execute_tag_merge

        result = _execute_tag_merge(pg_conn, "tag.source_tag", "tag.target_tag", None)
        assert result["affected_assets"] == 1

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.source_tag") == 0
            assert _count_tag(cur, "tag.target_tag") == 2

    def test_merge_dedup_when_asset_has_both(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "md1.mp4")
            _insert_tag(cur, a1, "tag.from")
            _insert_tag(cur, a1, "tag.to")

        from retrovue.web.studio import _execute_tag_merge

        result = _execute_tag_merge(pg_conn, "tag.from", "tag.to", None)
        assert result["already_had_target"] == 1

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.from") == 0


# ===========================================================================
# Tag Bulk Remove
# ===========================================================================


@requires_pg
class TestTagBulkRemove:
    """Bulk remove deletes a tag from all assets."""

    def test_bulk_remove_deletes_from_all_assets(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "br1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "br2.mp4")
            _insert_tag(cur, a1, "tag.unwanted")
            _insert_tag(cur, a2, "tag.unwanted")
            _insert_tag(cur, a1, "tag.keeper")

        from retrovue.web.studio import _execute_tag_bulk_remove

        result = _execute_tag_bulk_remove(pg_conn, "tag.unwanted")
        assert result["affected_assets"] == 2

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.unwanted") == 0
            assert _count_tag(cur, "tag.keeper") == 1


# ===========================================================================
# Rename Preview
# ===========================================================================


@requires_pg
class TestRenamePreview:
    """Preview returns affected count and pool references."""

    def test_preview_counts_affected_assets(self, pg_conn, test_container_uuid):
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, test_container_uuid, "p1.mp4")
            a2 = _insert_asset(cur, test_container_uuid, "p2.mp4")
            _insert_tag(cur, a1, "tag.hbo")
            _insert_tag(cur, a2, "tag.hbo")

        from retrovue.web.studio import _build_rename_preview

        result = _build_rename_preview(pg_conn, "tag.hbo", "tag.hbo_max")
        assert result["affected_assets"] == 2

    def test_preview_finds_pool_references(self, tmp_path, pg_conn):
        # Create a channel config that references the tag
        chan_dir = tmp_path / "channels"
        chan_dir.mkdir()
        (chan_dir / "test.yaml").write_text(
            "channel: test\npools:\n  my_pool:\n    select:\n      where:\n        tags:\n          contains_all: [hbo]\n"
        )

        from retrovue.web.studio import _build_rename_preview

        result = _build_rename_preview(pg_conn, "tag.hbo", "tag.hbo_max", config_dir=str(chan_dir))
        assert len(result["pool_references"]) >= 1
        assert result["pool_references"][0]["channel"] == "test"
        assert result["pool_references"][0]["pool_name"] == "my_pool"


# ===========================================================================
# Assets Scope Extension
# ===========================================================================


class TestAssetsScopeParam:
    """GET /studio/api/assets scope parameter extends query."""

    def test_scope_all_returns_non_interstitial_assets(self):
        from retrovue.web.studio import _build_assets_query

        where_parts, params = _build_assets_query(scope="all")
        sql = " AND ".join(where_parts)
        assert "c.name = ANY" not in sql

    def test_scope_interstitials_keeps_filter(self):
        from retrovue.web.studio import _build_assets_query

        where_parts, params = _build_assets_query(scope="interstitials")
        sql = " AND ".join(where_parts)
        assert "c.name = ANY" in sql

    def test_scope_default_is_all(self):
        from retrovue.web.studio import _build_assets_query

        where_parts_default, _ = _build_assets_query()
        where_parts_all, _ = _build_assets_query(scope="all")
        assert where_parts_default == where_parts_all

    def test_scope_specific_collection(self):
        from retrovue.web.studio import _build_assets_query

        where_parts, params = _build_assets_query(scope="commercials")
        sql = " AND ".join(where_parts)
        assert "c.name = %s" in sql
        assert "commercials" in params


# ===========================================================================
# Pool Reference Scanner (unit, no Postgres)
# ===========================================================================


class TestPoolReferenceScanner:
    """_scan_pool_references finds tag references in channel YAML."""

    def test_finds_contains_all_reference(self, tmp_path):
        chan_dir = tmp_path / "channels"
        chan_dir.mkdir()
        (chan_dir / "hbo.yaml").write_text(
            "channel: hbo\npools:\n  intros:\n    select:\n      where:\n        tags:\n          contains_all: [hbo, presentation]\n"
        )
        from retrovue.web.studio import _scan_pool_references

        refs = _scan_pool_references("tag.hbo", config_dir=str(chan_dir))
        assert len(refs) == 1
        assert refs[0]["channel"] == "hbo"
        assert refs[0]["pool_name"] == "intros"
        assert refs[0]["operator"] == "contains_all"

    def test_finds_excludes_any_reference(self, tmp_path):
        chan_dir = tmp_path / "channels"
        chan_dir.mkdir()
        (chan_dir / "test.yaml").write_text(
            "channel: test\npools:\n  traffic:\n    select:\n      where:\n        tags:\n          excludes_any: [anime]\n"
        )
        from retrovue.web.studio import _scan_pool_references

        refs = _scan_pool_references("tag.anime", config_dir=str(chan_dir))
        assert len(refs) == 1
        assert refs[0]["operator"] == "excludes_any"

    def test_no_match_returns_empty(self, tmp_path):
        chan_dir = tmp_path / "channels"
        chan_dir.mkdir()
        (chan_dir / "test.yaml").write_text(
            "channel: test\npools:\n  traffic:\n    select:\n      where:\n        tags:\n          contains_all: [hbo]\n"
        )
        from retrovue.web.studio import _scan_pool_references

        refs = _scan_pool_references("tag.nonexistent", config_dir=str(chan_dir))
        assert refs == []

    def test_missing_dir_returns_empty(self, tmp_path):
        from retrovue.web.studio import _scan_pool_references

        refs = _scan_pool_references("tag.hbo", config_dir=str(tmp_path / "nope"))
        assert refs == []
