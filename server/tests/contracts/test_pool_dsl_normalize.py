"""Contract tests for select.where → match normalization (pool DSL)."""

from __future__ import annotations

import pytest

from retrovue.runtime.pool_dsl_normalize import (
    normalize_pool_definition,
    select_where_to_match,
)


def test_select_where_eq_to_match():
    assert select_where_to_match(
        {
            "type": {"eq": "episode"},
            "series_title": {"eq": "Cheers"},
        }
    ) == {"type": "episode", "series_title": "Cheers"}


def test_select_where_rating_in_becomes_include():
    assert select_where_to_match(
        {"rating": {"in": ["PG", "PG-13"]}}
    ) == {"rating": {"include": ["PG", "PG-13"]}}


def test_select_where_tags_contains_all():
    assert select_where_to_match(
        {"tags": {"contains_all": ["hbo", "presentation"]}}
    ) == {"tags": ["hbo", "presentation"]}


def test_normalize_pool_definition_strips_select():
    raw = {
        "select": {
            "where": {
                "type": {"eq": "episode"},
                "series_title": {"eq": "Cheers"},
            }
        }
    }
    out = normalize_pool_definition(raw)
    assert "select" not in out
    assert out["match"] == {"type": "episode", "series_title": "Cheers"}


def test_normalize_pool_definition_preserves_legacy_match():
    raw = {"match": {"type": "commercial"}}
    out = normalize_pool_definition(raw)
    assert out == {"match": {"type": "commercial"}}


def test_genres_in_raises():
    with pytest.raises(ValueError, match="genres"):
        select_where_to_match({"genres": {"in": ["Science Fiction"]}})
