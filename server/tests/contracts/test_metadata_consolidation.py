"""Contract tests for metadata consolidation.

Validates that AssetEditorial indexed columns are correctly populated from
JSONB payload, including content_rating dict-vs-string normalization,
production_year/year fallback, NULL preservation, and dual-write behavior.

Reference: docs/contracts/metadata_consolidation.md
No new invariants — this is a performance optimization.
"""

from __future__ import annotations

import copy

import pytest

from retrovue.domain.entities import AssetEditorial


# ---------------------------------------------------------------------------
# Helper: construct an AssetEditorial-like object to test sync_columns_from_payload
# without requiring a live SQLAlchemy session.  We create a plain object whose
# __dict__ is writable and bind the unbound method.
# ---------------------------------------------------------------------------


class _EditorialStub:
    """Minimal stand-in for AssetEditorial that can call sync_columns_from_payload."""

    sync_columns_from_payload = AssetEditorial.sync_columns_from_payload

    def __init__(self, payload: dict | None) -> None:
        self.payload = payload
        self.series_title = None
        self.season_number = None
        self.episode_number = None
        self.content_rating = None
        self.production_year = None
        self.sync_columns_from_payload()


# ===========================================================================
# Backfill Correctness — sync_columns_from_payload
# ===========================================================================


class TestSyncColumnsFromPayload:
    """Contract: columns populated from JSONB payload via sync_columns_from_payload."""

    @pytest.mark.contract
    def test_series_title_populated(self):
        """Column: series_title extracted from payload."""
        ed = _EditorialStub({"series_title": "Breaking Bad"})
        assert ed.series_title == "Breaking Bad"

    @pytest.mark.contract
    def test_season_number_populated(self):
        """Column: season_number extracted and cast to int."""
        ed = _EditorialStub({"season_number": 3})
        assert ed.season_number == 3

    @pytest.mark.contract
    def test_episode_number_populated(self):
        """Column: episode_number extracted and cast to int."""
        ed = _EditorialStub({"episode_number": 12})
        assert ed.episode_number == 12

    @pytest.mark.contract
    def test_season_number_string_cast(self):
        """Column: season_number from string-typed JSONB value cast to int."""
        ed = _EditorialStub({"season_number": "5"})
        assert ed.season_number == 5

    @pytest.mark.contract
    def test_episode_number_string_cast(self):
        """Column: episode_number from string-typed JSONB value cast to int."""
        ed = _EditorialStub({"episode_number": "8"})
        assert ed.episode_number == 8


# ===========================================================================
# Content Rating Normalization
# ===========================================================================


class TestContentRatingNormalization:
    """Contract: content_rating dict-vs-string handling (metadata_consolidation.md §Column Definitions)."""

    @pytest.mark.contract
    def test_content_rating_string_form(self):
        """content_rating as bare string stored directly."""
        ed = _EditorialStub({"content_rating": "TV-14"})
        assert ed.content_rating == "TV-14"

    @pytest.mark.contract
    def test_content_rating_dict_form(self):
        """content_rating as dict: column stores the resolved 'code' field."""
        ed = _EditorialStub({"content_rating": {"code": "TV-MA", "source": "TVPG"}})
        assert ed.content_rating == "TV-MA"

    @pytest.mark.contract
    def test_content_rating_dict_missing_code(self):
        """content_rating dict with no 'code' key produces None."""
        ed = _EditorialStub({"content_rating": {"source": "TVPG"}})
        assert ed.content_rating is None

    @pytest.mark.contract
    def test_content_rating_empty_string(self):
        """content_rating empty string treated as None."""
        ed = _EditorialStub({"content_rating": ""})
        assert ed.content_rating is None


# ===========================================================================
# Production Year Fallback
# ===========================================================================


class TestProductionYearFallback:
    """Contract: production_year with year fallback (metadata_consolidation.md §Column Definitions)."""

    @pytest.mark.contract
    def test_production_year_from_production_year(self):
        """Primary key: production_year used when present."""
        ed = _EditorialStub({"production_year": 2005})
        assert ed.production_year == 2005

    @pytest.mark.contract
    def test_production_year_fallback_to_year(self):
        """Fallback: 'year' key used when 'production_year' is absent."""
        ed = _EditorialStub({"year": 1998})
        assert ed.production_year == 1998

    @pytest.mark.contract
    def test_production_year_prefers_production_year_over_year(self):
        """Priority: production_year takes precedence over year when both present."""
        ed = _EditorialStub({"production_year": 2010, "year": 2009})
        assert ed.production_year == 2010

    @pytest.mark.contract
    def test_production_year_string_cast(self):
        """production_year from string-typed JSONB value cast to int."""
        ed = _EditorialStub({"production_year": "2020"})
        assert ed.production_year == 2020


# ===========================================================================
# NULL Preservation
# ===========================================================================


class TestNullPreservation:
    """Contract: missing JSONB keys produce NULL columns, not empty strings or zeros."""

    @pytest.mark.contract
    def test_empty_payload_all_nulls(self):
        """Empty payload produces all-NULL columns."""
        ed = _EditorialStub({})
        assert ed.series_title is None
        assert ed.season_number is None
        assert ed.episode_number is None
        assert ed.content_rating is None
        assert ed.production_year is None

    @pytest.mark.contract
    def test_none_payload_all_nulls(self):
        """None payload produces all-NULL columns."""
        ed = _EditorialStub(None)
        assert ed.series_title is None
        assert ed.season_number is None
        assert ed.episode_number is None
        assert ed.content_rating is None
        assert ed.production_year is None

    @pytest.mark.contract
    def test_partial_payload_missing_fields_null(self):
        """Only populated fields get values; rest are NULL."""
        ed = _EditorialStub({"series_title": "Lost", "season_number": 1})
        assert ed.series_title == "Lost"
        assert ed.season_number == 1
        assert ed.episode_number is None
        assert ed.content_rating is None
        assert ed.production_year is None

    @pytest.mark.contract
    def test_empty_series_title_becomes_none(self):
        """Empty string series_title treated as None."""
        ed = _EditorialStub({"series_title": ""})
        assert ed.series_title is None


# ===========================================================================
# JSONB Payload Unchanged
# ===========================================================================


class TestPayloadUnchanged:
    """Contract: JSONB payload is never modified by sync_columns_from_payload."""

    @pytest.mark.contract
    def test_payload_not_mutated(self):
        """sync_columns_from_payload must not alter the payload dict."""
        original = {
            "series_title": "The Wire",
            "season_number": 4,
            "episode_number": 13,
            "content_rating": {"code": "TV-MA", "source": "TVPG"},
            "production_year": 2002,
            "description": "A show about Baltimore",
        }
        payload_copy = copy.deepcopy(original)

        ed = _EditorialStub(original)

        assert ed.payload == payload_copy, "payload must not be mutated by sync"


# ===========================================================================
# Full round-trip: all five columns from realistic payload
# ===========================================================================


class TestFullRoundTrip:
    """Contract: complete editorial payload populates all columns correctly."""

    @pytest.mark.contract
    def test_realistic_episode_payload(self):
        """All five columns extracted from a realistic episode editorial payload."""
        ed = _EditorialStub({
            "title": "Ozymandias",
            "series_title": "Breaking Bad",
            "season_number": 5,
            "episode_number": 14,
            "content_rating": "TV-14",
            "production_year": 2013,
            "description": "Everyone copes with radically changed circumstances.",
        })
        assert ed.series_title == "Breaking Bad"
        assert ed.season_number == 5
        assert ed.episode_number == 14
        assert ed.content_rating == "TV-14"
        assert ed.production_year == 2013

    @pytest.mark.contract
    def test_movie_payload_no_season_episode(self):
        """Movie payload: season/episode columns are NULL."""
        ed = _EditorialStub({
            "title": "The Shawshank Redemption",
            "content_rating": {"code": "R", "source": "MPAA"},
            "production_year": 1994,
        })
        assert ed.series_title is None
        assert ed.season_number is None
        assert ed.episode_number is None
        assert ed.content_rating == "R"
        assert ed.production_year == 1994
