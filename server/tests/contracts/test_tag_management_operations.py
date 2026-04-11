"""Contract tests for tag management operations — rename, merge, bulk-remove invariants.

Validates deeper behavioral guarantees beyond the API-level tests:
- INV-TAG-RENAME-ATOMIC-001: Atomic rename with palette update, dedup, rollback
- INV-TAG-MERGE-DEDUP-001: Merge deduplicates, fully removes source
- INV-TAG-BULK-REMOVE-001: Bulk remove is atomic, palette-independent
- INV-TAG-SCOPE-ALL-001: Operations apply across all asset/container types

Regression:
- Pool resolution via expand_tag_match_set works after rename/merge
- Canonical form preserved through all operations

These tests use real Postgres. No mocks (INV-PRODUCTION-BOUNDARY-001).
"""

from __future__ import annotations

import os
import sqlite3
import uuid

import psycopg
import pytest

from retrovue.domain.tag_normalization import (
    canonicalize_tag,
    expand_tag_match_set,
)

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
def test_source_uuid(pg_conn):
    """Get or create a test source."""
    with pg_conn.cursor() as cur:
        src_uuid = uuid.uuid4()
        cur.execute(
            "INSERT INTO sources(uuid, name, source_type, base_path) "
            "VALUES(%s, 'test-ops', 'local_directory', '/tmp/test-ops') ON CONFLICT DO NOTHING "
            "RETURNING uuid",
            (src_uuid,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT uuid FROM sources WHERE name = 'test-ops'")
        return cur.fetchone()[0]


@pytest.fixture
def multi_container(pg_conn, test_source_uuid):
    """Create three containers simulating different asset types (movies, episodes, interstitials)."""
    containers = {}
    for name in ("movies", "episodes", "interstitials"):
        cont_uuid = uuid.uuid4()
        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO containers(uuid, source_id, name, path) VALUES(%s, %s, %s, %s)",
                (cont_uuid, test_source_uuid, name, f"/tmp/test-ops/{name}"),
            )
        containers[name] = cont_uuid
    return containers


def _insert_asset(cur, container_uuid, uri_suffix="test.mp4"):
    """Insert a test asset and return its UUID."""
    asset_uuid = uuid.uuid4()
    cur.execute(
        "INSERT INTO assets(uuid, container_id, uri, state) VALUES(%s, %s, %s, 'ready')",
        (asset_uuid, container_uuid, f"file:///tmp/test-ops/{uri_suffix}"),
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


def _asset_tags(cur, asset_uuid):
    """Return set of tags for an asset."""
    cur.execute("SELECT tag FROM asset_tags WHERE asset_uuid = %s", (asset_uuid,))
    return {r[0] for r in cur.fetchall()}


def _insert_palette(db_path, category, tag, bg="#000", fg="#fff"):
    c = sqlite3.connect(db_path)
    c.execute(
        "INSERT INTO tag_palette(category, tag, color_bg, color_fg) VALUES(?, ?, ?, ?)",
        (category, tag, bg, fg),
    )
    c.commit()
    c.close()


def _palette_exists(db_path, category, tag):
    c = sqlite3.connect(db_path)
    row = c.execute(
        "SELECT 1 FROM tag_palette WHERE category = ? AND tag = ?", (category, tag)
    ).fetchone()
    c.close()
    return row is not None


# ===========================================================================
# INV-TAG-RENAME-ATOMIC-001 — Deeper atomicity and palette tests
# ===========================================================================


@requires_pg
class TestRenameAtomicity:
    """INV-TAG-RENAME-ATOMIC-001: Rename is atomic with palette update."""

    @pytest.mark.contract
    def test_rename_updates_palette_entry(self, pg_conn, multi_container, sqlite_palette):
        """Palette entry is renamed from old namespace.value to new namespace.value."""
        _insert_palette(sqlite_palette, "TAG", "oldshow", "#111", "#222")
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "pal1.mp4")
            _insert_tag(cur, a, "tag.oldshow")

        from retrovue.web.studio import _execute_tag_rename

        _execute_tag_rename(pg_conn, "tag.oldshow", "tag.newshow", sqlite_palette)
        assert not _palette_exists(sqlite_palette, "TAG", "oldshow")
        assert _palette_exists(sqlite_palette, "TAG", "newshow")

    @pytest.mark.contract
    def test_rename_preserves_other_tags_on_asset(self, pg_conn, multi_container):
        """Rename only touches the specified tag; other tags are untouched."""
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "ot1.mp4")
            _insert_tag(cur, a, "tag.oldtag")
            _insert_tag(cur, a, "genre.comedy")
            _insert_tag(cur, a, "network.hbo")

        from retrovue.web.studio import _execute_tag_rename

        _execute_tag_rename(pg_conn, "tag.oldtag", "tag.newtag", None)
        with pg_conn.cursor() as cur:
            tags = _asset_tags(cur, a)
        assert "tag.newtag" in tags
        assert "tag.oldtag" not in tags
        assert "genre.comedy" in tags
        assert "network.hbo" in tags

    @pytest.mark.contract
    def test_rename_dedup_leaves_no_duplicate_rows(self, pg_conn, multi_container):
        """When asset has both old and new tag, rename leaves exactly one row per (asset, new_tag)."""
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "dd1.mp4")
            _insert_tag(cur, a, "tag.alpha")
            _insert_tag(cur, a, "tag.beta")

        from retrovue.web.studio import _execute_tag_rename

        _execute_tag_rename(pg_conn, "tag.alpha", "tag.beta", None)
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM asset_tags WHERE asset_uuid = %s AND tag = %s",
                (a, "tag.beta"),
            )
            assert cur.fetchone()[0] == 1, "Must have exactly one row, not a duplicate"
            assert _count_tag(cur, "tag.alpha") == 0

    @pytest.mark.contract
    def test_rename_canonical_form_preserved(self, pg_conn, multi_container):
        """After rename, the new tag is in canonical form."""
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "cf1.mp4")
            _insert_tag(cur, a, "tag.original")

        from retrovue.web.studio import _execute_tag_rename

        _execute_tag_rename(pg_conn, "tag.original", "tag.renamed", None)
        with pg_conn.cursor() as cur:
            tags = _asset_tags(cur, a)
        for t in tags:
            if t.startswith("tag."):
                assert t == canonicalize_tag(t), f"Tag {t} not in canonical form"


# ===========================================================================
# INV-TAG-MERGE-DEDUP-001 — Merge dedup, source fully removed
# ===========================================================================


@requires_pg
class TestMergeDedup:
    """INV-TAG-MERGE-DEDUP-001: Merge deduplicates and fully removes source."""

    @pytest.mark.contract
    def test_merge_source_fully_removed(self, pg_conn, multi_container):
        """After merge, zero rows with source tag remain."""
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, multi_container["movies"], "mfr1.mp4")
            a2 = _insert_asset(cur, multi_container["episodes"], "mfr2.mp4")
            a3 = _insert_asset(cur, multi_container["interstitials"], "mfr3.mp4")
            _insert_tag(cur, a1, "tag.source")
            _insert_tag(cur, a2, "tag.source")
            _insert_tag(cur, a3, "tag.source")
            _insert_tag(cur, a2, "tag.target")  # overlap

        from retrovue.web.studio import _execute_tag_merge

        result = _execute_tag_merge(pg_conn, "tag.source", "tag.target", None)

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.source") == 0, "Source tag must be fully removed"
            assert _count_tag(cur, "tag.target") == 3, "All three assets must have target"

    @pytest.mark.contract
    def test_merge_no_duplicate_rows(self, pg_conn, multi_container):
        """Merge must not create duplicate (asset_uuid, tag) rows."""
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "mnd1.mp4")
            _insert_tag(cur, a, "tag.from")
            _insert_tag(cur, a, "tag.to")

        from retrovue.web.studio import _execute_tag_merge

        _execute_tag_merge(pg_conn, "tag.from", "tag.to", None)
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM asset_tags WHERE asset_uuid = %s AND tag = %s",
                (a, "tag.to"),
            )
            assert cur.fetchone()[0] == 1

    @pytest.mark.contract
    def test_merge_counts_correct(self, pg_conn, multi_container):
        """Result counts must be: affected_assets = total with source, already_had_target = overlap."""
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, multi_container["movies"], "mc1.mp4")
            a2 = _insert_asset(cur, multi_container["movies"], "mc2.mp4")
            a3 = _insert_asset(cur, multi_container["movies"], "mc3.mp4")
            _insert_tag(cur, a1, "tag.src")  # only source
            _insert_tag(cur, a2, "tag.src")  # both
            _insert_tag(cur, a2, "tag.tgt")
            _insert_tag(cur, a3, "tag.tgt")  # only target

        from retrovue.web.studio import _execute_tag_merge

        result = _execute_tag_merge(pg_conn, "tag.src", "tag.tgt", None)
        assert result["already_had_target"] == 1, "a2 had both"
        # affected_assets should count all assets that had source (a1 + a2 = 2)
        assert result["affected_assets"] == 2

    @pytest.mark.contract
    def test_merge_removes_source_from_palette(self, pg_conn, multi_container, sqlite_palette):
        """After merge, the source tag palette entry is deleted."""
        _insert_palette(sqlite_palette, "TAG", "oldname")
        _insert_palette(sqlite_palette, "TAG", "newname")
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "mp1.mp4")
            _insert_tag(cur, a, "tag.oldname")

        from retrovue.web.studio import _execute_tag_merge

        _execute_tag_merge(pg_conn, "tag.oldname", "tag.newname", sqlite_palette)
        assert not _palette_exists(sqlite_palette, "TAG", "oldname"), "Source palette entry must be removed"
        assert _palette_exists(sqlite_palette, "TAG", "newname"), "Target palette entry must remain"


# ===========================================================================
# INV-TAG-BULK-REMOVE-001 — Atomic removal, palette-independent
# ===========================================================================


@requires_pg
class TestBulkRemove:
    """INV-TAG-BULK-REMOVE-001: Bulk remove is atomic and palette-independent."""

    @pytest.mark.contract
    def test_bulk_remove_preserves_palette(self, pg_conn, multi_container, sqlite_palette):
        """Bulk remove deletes asset_tags rows but leaves palette entry intact."""
        _insert_palette(sqlite_palette, "TAG", "unwanted")
        with pg_conn.cursor() as cur:
            a1 = _insert_asset(cur, multi_container["movies"], "brp1.mp4")
            a2 = _insert_asset(cur, multi_container["movies"], "brp2.mp4")
            _insert_tag(cur, a1, "tag.unwanted")
            _insert_tag(cur, a2, "tag.unwanted")

        from retrovue.web.studio import _execute_tag_bulk_remove

        result = _execute_tag_bulk_remove(pg_conn, "tag.unwanted")
        assert result["affected_assets"] == 2
        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.unwanted") == 0
        assert _palette_exists(sqlite_palette, "TAG", "unwanted"), \
            "Palette entry must survive bulk remove — palette is display-only"

    @pytest.mark.contract
    def test_bulk_remove_preserves_other_tags(self, pg_conn, multi_container):
        """Bulk remove only deletes the specified tag; other tags on the same assets are untouched."""
        with pg_conn.cursor() as cur:
            a = _insert_asset(cur, multi_container["movies"], "bro1.mp4")
            _insert_tag(cur, a, "tag.remove_me")
            _insert_tag(cur, a, "genre.comedy")
            _insert_tag(cur, a, "network.hbo")

        from retrovue.web.studio import _execute_tag_bulk_remove

        _execute_tag_bulk_remove(pg_conn, "tag.remove_me")
        with pg_conn.cursor() as cur:
            tags = _asset_tags(cur, a)
        assert "tag.remove_me" not in tags
        assert "genre.comedy" in tags
        assert "network.hbo" in tags

    @pytest.mark.contract
    def test_bulk_remove_noop_when_absent(self, pg_conn):
        """Bulk remove of a nonexistent tag returns zero affected and does not error."""
        from retrovue.web.studio import _execute_tag_bulk_remove

        result = _execute_tag_bulk_remove(pg_conn, "tag.nonexistent")
        assert result["affected_assets"] == 0


# ===========================================================================
# INV-TAG-SCOPE-ALL-001 — Operations apply across all container types
# ===========================================================================


@requires_pg
class TestTagScopeAll:
    """INV-TAG-SCOPE-ALL-001: Tag operations affect all asset/container types."""

    @pytest.mark.contract
    def test_rename_across_container_types(self, pg_conn, multi_container):
        """Rename applies to assets in movies, episodes, and interstitials containers."""
        with pg_conn.cursor() as cur:
            a_movie = _insert_asset(cur, multi_container["movies"], "scope_r1.mp4")
            a_episode = _insert_asset(cur, multi_container["episodes"], "scope_r2.mp4")
            a_interstitial = _insert_asset(cur, multi_container["interstitials"], "scope_r3.mp4")
            for a in (a_movie, a_episode, a_interstitial):
                _insert_tag(cur, a, "tag.cross_type")

        from retrovue.web.studio import _execute_tag_rename

        result = _execute_tag_rename(pg_conn, "tag.cross_type", "tag.cross_type_new", None)
        assert result["affected_assets"] == 3

        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.cross_type") == 0
            assert _count_tag(cur, "tag.cross_type_new") == 3
            # Verify each individual asset
            for a in (a_movie, a_episode, a_interstitial):
                tags = _asset_tags(cur, a)
                assert "tag.cross_type_new" in tags
                assert "tag.cross_type" not in tags

    @pytest.mark.contract
    def test_merge_across_container_types(self, pg_conn, multi_container):
        """Merge applies to assets in all container types."""
        with pg_conn.cursor() as cur:
            a_movie = _insert_asset(cur, multi_container["movies"], "scope_m1.mp4")
            a_episode = _insert_asset(cur, multi_container["episodes"], "scope_m2.mp4")
            a_interstitial = _insert_asset(cur, multi_container["interstitials"], "scope_m3.mp4")
            _insert_tag(cur, a_movie, "tag.merge_src")
            _insert_tag(cur, a_episode, "tag.merge_src")
            _insert_tag(cur, a_interstitial, "tag.merge_tgt")

        from retrovue.web.studio import _execute_tag_merge

        _execute_tag_merge(pg_conn, "tag.merge_src", "tag.merge_tgt", None)
        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.merge_src") == 0
            assert _count_tag(cur, "tag.merge_tgt") == 3

    @pytest.mark.contract
    def test_bulk_remove_across_container_types(self, pg_conn, multi_container):
        """Bulk remove applies to assets in all container types."""
        with pg_conn.cursor() as cur:
            a_movie = _insert_asset(cur, multi_container["movies"], "scope_br1.mp4")
            a_episode = _insert_asset(cur, multi_container["episodes"], "scope_br2.mp4")
            a_interstitial = _insert_asset(cur, multi_container["interstitials"], "scope_br3.mp4")
            for a in (a_movie, a_episode, a_interstitial):
                _insert_tag(cur, a, "tag.scope_remove")

        from retrovue.web.studio import _execute_tag_bulk_remove

        result = _execute_tag_bulk_remove(pg_conn, "tag.scope_remove")
        assert result["affected_assets"] == 3
        with pg_conn.cursor() as cur:
            assert _count_tag(cur, "tag.scope_remove") == 0


# ===========================================================================
# INV-TAG-SCOPE-ALL-001 — scope=all query (no Postgres needed)
# ===========================================================================


class TestScopeAllQuery:
    """INV-TAG-SCOPE-ALL-001: scope=all does not filter by container type."""

    @pytest.mark.contract
    def test_scope_all_assets_query_excludes_nothing(self):
        """scope=all returns assets from all container types (no container filter)."""
        from retrovue.web.studio import _build_assets_query

        where_parts, params = _build_assets_query(scope="all")
        sql = " AND ".join(where_parts)
        assert "c.name" not in sql, "scope=all must not filter by container name"

    @pytest.mark.contract
    def test_scope_default_is_all(self):
        """Default scope (None) behaves as scope=all."""
        from retrovue.web.studio import _build_assets_query

        where_default, _ = _build_assets_query()
        where_all, _ = _build_assets_query(scope="all")
        assert where_default == where_all


# ===========================================================================
# Regression — Pool resolution after rename/merge
# ===========================================================================


class TestPoolResolutionRegression:
    """Regression: expand_tag_match_set works correctly after rename/merge operations."""

    @pytest.mark.contract
    def test_expand_tag_match_set_on_renamed_tag(self):
        """After renaming tag.hbo to tag.hbo_max, expand_tag_match_set on 'tag.hbo_max'
        includes all backward-compatible forms of 'hbo_max'."""
        expanded = expand_tag_match_set({"tag.hbo_max"})
        assert "tag.hbo_max" in expanded
        assert "hbo_max" in expanded
        assert "tag:hbo_max" in expanded

    @pytest.mark.contract
    def test_expand_tag_match_set_old_tag_not_in_new_set(self):
        """After renaming tag.hbo to tag.hbo_max, the old plain value 'hbo'
        does NOT appear in the expanded set for 'tag.hbo_max'."""
        expanded = expand_tag_match_set({"tag.hbo_max"})
        assert "hbo" not in expanded, "Old tag plain value must not leak into new tag's match set"

    @pytest.mark.contract
    def test_canonical_form_preserved_through_rename(self):
        """Renamed tags maintain canonical namespace.value form."""
        old = canonicalize_tag("tag.classic_hbo")
        new = canonicalize_tag("tag.classic_max")
        assert old == "tag.classic_hbo"
        assert new == "tag.classic_max"
        # Both are valid canonical forms
        assert "." in old
        assert "." in new

    @pytest.mark.contract
    def test_pool_filter_matches_after_rename(self):
        """Pool DSL filter using expand_tag_match_set matches renamed tags."""
        from retrovue.runtime.asset_resolver import AssetMetadata
        from retrovue.runtime.catalog_resolver import _CatalogEntry, _normalize_tags_match

        entry = _CatalogEntry(
            canonical_id="renamed-asset-1",
            asset_type="bumper",
            duration_sec=30,
            series_title="",
            season=None,
            episode=None,
            rating=None,
            source_name="test",
            collection_name="test",
            meta=AssetMetadata(type="bumper", duration_sec=30, tags=("tag.hbo_max",)),
        )
        required = _normalize_tags_match("hbo_max")
        expanded = expand_tag_match_set(set(entry.meta.tags))
        assert all(t in expanded for t in required), \
            "Pool DSL query 'hbo_max' must match asset with renamed tag 'tag.hbo_max'"

    @pytest.mark.contract
    def test_pool_filter_does_not_match_old_name_after_rename(self):
        """After renaming hbo -> hbo_max, querying 'hbo' must NOT match 'tag.hbo_max'."""
        from retrovue.runtime.asset_resolver import AssetMetadata
        from retrovue.runtime.catalog_resolver import _CatalogEntry, _normalize_tags_match

        entry = _CatalogEntry(
            canonical_id="renamed-asset-2",
            asset_type="bumper",
            duration_sec=30,
            series_title="",
            season=None,
            episode=None,
            rating=None,
            source_name="test",
            collection_name="test",
            meta=AssetMetadata(type="bumper", duration_sec=30, tags=("tag.hbo_max",)),
        )
        required = _normalize_tags_match("hbo")
        expanded = expand_tag_match_set(set(entry.meta.tags))
        assert not all(t in expanded for t in required), \
            "Old tag name 'hbo' must NOT match renamed tag 'tag.hbo_max'"
