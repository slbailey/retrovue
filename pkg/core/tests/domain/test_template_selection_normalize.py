# pkg/core/tests/domain/test_template_selection_normalize.py
#
# Contract test for template segment selection normalization.
#
# Invariant: INV-TEMPLATE-SELECTION-NORMALIZE-001
#   Template segment `selection` may be either a single rule dict or a list
#   of rule dicts. The compiler must handle both forms without crashing.
#
# Root cause: hbo-classics.yaml declares selection as a dict:
#     selection:
#       type: tags
#       values: [hbo]
#   but _resolve_template_segments iterates with `for rule in selection`,
#   which yields dict keys (strings) instead of rule dicts.
#
# This test exercises _resolve_template_segments directly with both forms.

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import _resolve_template_segments, CompileError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_resolver() -> StubAssetResolver:
    """Resolver with intro assets tagged for filtering."""
    r = StubAssetResolver()
    r.add("intro-hbo-001", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO Intro",
        tags=("hbo",), file_uri="/assets/hbo_intro_1.mpg",
    ))
    r.add("intro-hbo-002", AssetMetadata(
        type="bumper", duration_sec=25, title="HBO Intro 2",
        tags=("hbo",), file_uri="/assets/hbo_intro_2.mpg",
    ))
    r.add("intro-showtime-001", AssetMetadata(
        type="bumper", duration_sec=28, title="Showtime Intro",
        tags=("showtime",), file_uri="/assets/showtime_intro_1.mpg",
    ))
    r.register_collection("Intros", [
        "intro-hbo-001", "intro-hbo-002", "intro-showtime-001",
    ])
    # Primary content asset
    r.add("movie-001", AssetMetadata(
        type="movie", duration_sec=7200, title="Blade Runner",
        tags=(), file_uri="/assets/blade_runner.mkv",
    ))
    return r


def _primary_seg():
    return {"source": {"type": "pool", "name": "hbo_movies"}, "mode": "random"}


def _primary_meta():
    return AssetMetadata(
        type="movie", duration_sec=7200, title="Blade Runner",
        tags=(), file_uri="/assets/blade_runner.mkv",
    )


# ---------------------------------------------------------------------------
# INV-TEMPLATE-SELECTION-NORMALIZE-001
# selection as a list of dicts (canonical form per ProgramTemplateAssembly)
# ---------------------------------------------------------------------------

class TestSelectionAsList:
    """selection declared as a list of rule dicts must work."""

    def test_list_form_compiles(self):
        resolver = _make_resolver()
        segments = [
            {
                "source": {"type": "collection", "name": "Intros"},
                "selection": [{"type": "tags", "values": ["hbo"]}],
                "mode": "random",
            },
            _primary_seg(),
        ]
        result = _resolve_template_segments(
            segments=segments,
            primary_seg=segments[1],
            primary_asset_id="movie-001",
            primary_meta=_primary_meta(),
            resolver=resolver,
            seed=42,
        )
        assert len(result) == 2
        # First segment should be an hbo intro
        assert result[0]["asset_id"] in ("intro-hbo-001", "intro-hbo-002")


# ---------------------------------------------------------------------------
# INV-TEMPLATE-SELECTION-NORMALIZE-001
# selection as a single dict (YAML shorthand used in hbo-classics.yaml)
# ---------------------------------------------------------------------------

class TestSelectionAsDict:
    """selection declared as a single rule dict must also work (not crash)."""

    def test_dict_form_does_not_crash(self):
        """The form used in hbo-classics.yaml must not raise AttributeError."""
        resolver = _make_resolver()
        segments = [
            {
                "source": {"type": "collection", "name": "Intros"},
                "selection": {"type": "tags", "values": ["hbo"]},
                "mode": "random",
            },
            _primary_seg(),
        ]
        # Must not raise: AttributeError: 'str' object has no attribute 'get'
        result = _resolve_template_segments(
            segments=segments,
            primary_seg=segments[1],
            primary_asset_id="movie-001",
            primary_meta=_primary_meta(),
            resolver=resolver,
            seed=42,
        )
        assert len(result) == 2
        assert result[0]["asset_id"] in ("intro-hbo-001", "intro-hbo-002")

    def test_dict_form_filters_correctly(self):
        """Dict-form selection must filter the same as list-form."""
        resolver = _make_resolver()
        # Dict form
        seg_dict = {
            "source": {"type": "collection", "name": "Intros"},
            "selection": {"type": "tags", "values": ["showtime"]},
            "mode": "random",
        }
        primary = _primary_seg()
        result = _resolve_template_segments(
            segments=[seg_dict, primary],
            primary_seg=primary,
            primary_asset_id="movie-001",
            primary_meta=_primary_meta(),
            resolver=resolver,
            seed=42,
        )
        # Only showtime intro should survive the filter
        assert result[0]["asset_id"] == "intro-showtime-001"


# ---------------------------------------------------------------------------
# INV-TEMPLATE-SELECTION-NORMALIZE-001
# selection omitted entirely (no filtering)
# ---------------------------------------------------------------------------

class TestSelectionOmitted:
    """When selection is omitted, all candidates pass through."""

    def test_no_selection_returns_all_candidates(self):
        resolver = _make_resolver()
        segments = [
            {
                "source": {"type": "collection", "name": "Intros"},
                "mode": "random",
            },
            _primary_seg(),
        ]
        result = _resolve_template_segments(
            segments=segments,
            primary_seg=segments[1],
            primary_asset_id="movie-001",
            primary_meta=_primary_meta(),
            resolver=resolver,
            seed=42,
        )
        assert len(result) == 2
        # Any intro should be valid (no filter applied)
        assert result[0]["asset_id"] in (
            "intro-hbo-001", "intro-hbo-002", "intro-showtime-001",
        )
