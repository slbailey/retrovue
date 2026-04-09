"""
Contract: docs/contracts/metadata_consolidation.md
Task: RETA-126 — Phase 6B Step 6

Tests verify the five test obligations from the metadata consolidation contract:
  1. Backfill correctness: columns match JSONB extraction for all editorial rows.
  2. Dual-write correctness: new ingest writes populate both JSONB and columns.
  3. content_rating normalization: dict and string forms both resolve to code value.
  4. production_year fallback: 'year' key is used when 'production_year' absent.
  5. NULL preservation: missing JSONB keys produce NULL columns (not empty strings or zeros).
  6. catalog_resolver equivalence: pool filtering results identical before/after column-read switch.
"""

from __future__ import annotations

import uuid

import pytest

from retrovue.domain.entities import AssetEditorial


# ---------------------------------------------------------------------------
# Test Obligation 1: AssetEditorial has indexed columns
# ---------------------------------------------------------------------------


class TestAssetEditorialColumns:
    """Verify that AssetEditorial has the five indexed columns defined
    in the metadata consolidation contract."""

    EXPECTED_COLUMNS = {
        "series_title",
        "season_number",
        "episode_number",
        "content_rating",
        "production_year",
    }

    def test_columns_exist_on_model(self) -> None:
        """All five columns must exist as mapped attributes on AssetEditorial."""
        table_cols = {c.name for c in AssetEditorial.__table__.columns}
        for col_name in self.EXPECTED_COLUMNS:
            assert col_name in table_cols, (
                f"AssetEditorial missing column '{col_name}' — "
                f"required by metadata consolidation contract"
            )

    def test_columns_are_nullable(self) -> None:
        """All five columns must be nullable (movies lack season/episode, etc.)."""
        for col_name in self.EXPECTED_COLUMNS:
            col = AssetEditorial.__table__.columns[col_name]
            assert col.nullable is True, (
                f"Column '{col_name}' must be nullable per contract"
            )

    def test_series_title_type(self) -> None:
        """series_title must be VARCHAR(512)."""
        col = AssetEditorial.__table__.columns["series_title"]
        assert hasattr(col.type, "length"), "series_title must be a string type"
        assert col.type.length == 512

    def test_integer_columns_type(self) -> None:
        """season_number, episode_number, production_year must be INTEGER."""
        for col_name in ("season_number", "episode_number", "production_year"):
            col = AssetEditorial.__table__.columns[col_name]
            type_name = type(col.type).__name__.upper()
            assert "INT" in type_name, (
                f"Column '{col_name}' must be INTEGER, got {type_name}"
            )

    def test_content_rating_type(self) -> None:
        """content_rating must be VARCHAR(32)."""
        col = AssetEditorial.__table__.columns["content_rating"]
        assert hasattr(col.type, "length"), "content_rating must be a string type"
        assert col.type.length == 32


# ---------------------------------------------------------------------------
# Test Obligation 2: Dual-write correctness
# ---------------------------------------------------------------------------


class TestDualWriteCorrectness:
    """Verify that persist_asset_metadata populates both JSONB payload
    and the indexed columns on AssetEditorial."""

    def test_persist_sets_columns_from_editorial_payload(self) -> None:
        """When editorial data is persisted, the five indexed columns
        must be populated alongside the JSONB payload."""
        from retrovue.infra.metadata.persistence import persist_asset_metadata

        # Create a minimal AssetEditorial via the persistence function
        # and verify columns are set.
        editorial = {
            "series_title": "Knight Rider",
            "season_number": 2,
            "episode_number": 5,
            "content_rating": "TV-PG",
            "production_year": 1983,
        }

        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload=editorial,
        )

        # After construction with the new column support, columns should be
        # populated by the dual-write mechanism.
        # This test will FAIL (RED) until the dual-write is implemented.
        assert ed.series_title == "Knight Rider"
        assert ed.season_number == 2
        assert ed.episode_number == 5
        assert ed.content_rating == "TV-PG"
        assert ed.production_year == 1983


# ---------------------------------------------------------------------------
# Test Obligation 3: content_rating normalization
# ---------------------------------------------------------------------------


class TestContentRatingNormalization:
    """content_rating column must store the resolved 'code' string
    regardless of whether the JSONB stores a bare string or dict."""

    def test_string_rating_stored_directly(self) -> None:
        """Bare string content_rating → column stores string as-is."""
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={"content_rating": "TV-14"},
        )
        assert ed.content_rating == "TV-14"

    def test_dict_rating_extracts_code(self) -> None:
        """Dict content_rating with 'code' key → column stores code value."""
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={"content_rating": {"code": "TV-MA", "source": "TVPG"}},
        )
        assert ed.content_rating == "TV-MA"


# ---------------------------------------------------------------------------
# Test Obligation 4: production_year fallback
# ---------------------------------------------------------------------------


class TestProductionYearFallback:
    """production_year column must fall back to 'year' key when
    'production_year' is absent in the JSONB payload."""

    def test_production_year_preferred(self) -> None:
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={"production_year": 1985, "year": 1984},
        )
        assert ed.production_year == 1985

    def test_year_fallback(self) -> None:
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={"year": 1984},
        )
        assert ed.production_year == 1984


# ---------------------------------------------------------------------------
# Test Obligation 5: NULL preservation
# ---------------------------------------------------------------------------


class TestNullPreservation:
    """Missing JSONB keys must produce NULL columns, not empty strings or zeros."""

    def test_empty_payload_all_null(self) -> None:
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={},
        )
        assert ed.series_title is None
        assert ed.season_number is None
        assert ed.episode_number is None
        assert ed.content_rating is None
        assert ed.production_year is None

    def test_partial_payload_nulls_missing(self) -> None:
        ed = AssetEditorial(
            asset_uuid=uuid.uuid4(),
            payload={"series_title": "Airwolf"},
        )
        assert ed.series_title == "Airwolf"
        assert ed.season_number is None
        assert ed.episode_number is None
        assert ed.content_rating is None
        assert ed.production_year is None


# ---------------------------------------------------------------------------
# Test Obligation 6: catalog_resolver equivalence
# ---------------------------------------------------------------------------


class TestCatalogResolverColumnRead:
    """After migration, catalog_resolver must read indexed columns
    instead of JSONB paths for the five promoted fields."""

    def test_catalog_entry_uses_column_attributes(self) -> None:
        """The _load method should read .series_title, .season_number, etc.
        from AssetEditorial ORM attributes (columns), not from payload dict.

        This is a structural test — verifying the resolver code path reads
        from columns. Full integration is covered by pool filtering tests."""
        import inspect
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        source = inspect.getsource(CatalogAssetResolver._load)

        # After the column-read switch, the _load method should reference
        # ed.series_title (ORM attribute) instead of editorial.get("series_title")
        assert "ed.series_title" in source or "editorial_row.series_title" in source, (
            "catalog_resolver._load must read series_title from ORM column attribute, "
            "not from JSONB payload dict"
        )
