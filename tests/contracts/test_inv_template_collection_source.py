"""Contract tests for INV-TEMPLATE-COLLECTION-SOURCE-RESOLVE.

Template segments with source.type == "collection" MUST resolve candidates
via resolver.query({"collection": source_name}), not resolver.lookup().

Coverage:
  1. Collection source resolves candidates via query()
  2. Pool source still resolves via lookup()
  3. Compilation succeeds for template with collection intro + pool movie
  4. KeyError is NOT raised for collection source names
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import _resolve_template_segments


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_resolver() -> StubAssetResolver:
    """Build a resolver with intro collection + movie pool assets."""
    resolver = StubAssetResolver()

    # Intro assets (belong to "Intros" collection)
    resolver.add("intro-hbo-001", AssetMetadata(
        type="bumper", duration_sec=15, title="HBO Intro",
        file_uri="/assets/intro-hbo-001.mp4",
        tags=("hbo",),
    ))
    resolver.add("intro-hbo-002", AssetMetadata(
        type="bumper", duration_sec=20, title="HBO Feature Presentation",
        file_uri="/assets/intro-hbo-002.mp4",
        tags=("hbo",),
    ))
    resolver.add("intro-generic", AssetMetadata(
        type="bumper", duration_sec=10, title="Generic Intro",
        file_uri="/assets/intro-generic.mp4",
    ))
    resolver.register_collection("Intros", [
        "intro-hbo-001", "intro-hbo-002", "intro-generic",
    ])

    # Movie assets (resolved via pool)
    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="The Matrix",
        file_uri="/assets/movie-001.mp4",
    ))
    resolver.add("movie-002", AssetMetadata(
        type="movie", duration_sec=7200, title="Blade Runner",
        file_uri="/assets/movie-002.mp4",
    ))
    resolver.register_pools({
        "hbo_movies": {"match": {"type": "movie"}},
    })

    return resolver


def _hbo_template_segments() -> list[dict]:
    """Template segments matching hbo-classics.yaml structure."""
    return [
        {
            "source": {"type": "collection", "name": "Intros"},
            "selection": [{"type": "tags", "values": ["hbo"]}],
            "mode": "random",
        },
        {
            "source": {"type": "pool", "name": "hbo_movies"},
            "mode": "random",
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Collection source resolves candidates via query()
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectionSourceResolution:

    def test_collection_source_returns_candidates(self):
        """A collection source type must resolve to assets in that collection."""
        resolver = _make_resolver()
        segments = _hbo_template_segments()
        primary_seg = segments[1]  # movie is primary
        primary_meta = resolver.lookup("movie-001")

        compiled = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id="movie-001",
            primary_meta=primary_meta,
            resolver=resolver,
            seed=42,
        )

        # First segment should be intro type from collection
        assert compiled[0]["segment_type"] == "intro"
        assert compiled[0]["source_type"] == "collection"
        assert compiled[0]["source_name"] == "Intros"
        assert compiled[0]["asset_uri"] != ""

    def test_collection_source_with_tag_filter(self):
        """Collection source with tag selection filters to matching assets."""
        resolver = _make_resolver()
        segments = _hbo_template_segments()
        primary_seg = segments[1]
        primary_meta = resolver.lookup("movie-001")

        compiled = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id="movie-001",
            primary_meta=primary_meta,
            resolver=resolver,
            seed=42,
        )

        # The intro should be one of the HBO-tagged intros (not generic)
        intro = compiled[0]
        assert intro["asset_id"] in ("intro-hbo-001", "intro-hbo-002")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pool source still resolves via lookup()
# ─────────────────────────────────────────────────────────────────────────────

class TestPoolSourceStillWorks:

    def test_pool_source_resolves(self):
        """Pool sources must still resolve via lookup() as before."""
        resolver = _make_resolver()
        segments = [
            {
                "source": {"type": "pool", "name": "hbo_movies"},
                "mode": "random",
            },
        ]
        primary_seg = segments[0]
        primary_meta = resolver.lookup("movie-001")

        compiled = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id="movie-001",
            primary_meta=primary_meta,
            resolver=resolver,
            seed=42,
        )

        assert compiled[0]["segment_type"] == "content"
        assert compiled[0]["asset_id"] == "movie-001"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Full template compilation with collection intro + pool movie
# ─────────────────────────────────────────────────────────────────────────────

class TestFullTemplateCompilation:

    def test_hbo_style_template_compiles(self):
        """A template with collection intro + pool movie must compile
        without errors, producing intro + content segments."""
        resolver = _make_resolver()
        segments = _hbo_template_segments()
        primary_seg = segments[1]  # movie segment is primary
        primary_meta = resolver.lookup("movie-001")

        compiled = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id="movie-001",
            primary_meta=primary_meta,
            resolver=resolver,
            seed=99,
        )

        assert len(compiled) == 2
        seg_types = [s["segment_type"] for s in compiled]
        assert seg_types == ["intro", "content"]

        # Intro comes from collection
        assert compiled[0]["source_type"] == "collection"
        assert compiled[0]["duration_sec" if "duration_sec" in compiled[0] else "segment_duration_ms"] > 0

        # Content is the primary movie
        assert compiled[1]["asset_id"] == "movie-001"
        assert compiled[1]["is_primary"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. KeyError is NOT raised for collection source names
# ─────────────────────────────────────────────────────────────────────────────

class TestNoKeyErrorForCollections:

    def test_no_keyerror_for_collection_name(self):
        """resolver.lookup("Intros") would raise KeyError, but
        _resolve_template_segments must NOT call lookup for collections."""
        resolver = _make_resolver()

        # Verify lookup WOULD fail (proving the bug existed)
        with pytest.raises(KeyError):
            resolver.lookup("Intros")

        # But _resolve_template_segments must succeed
        segments = _hbo_template_segments()
        primary_seg = segments[1]
        primary_meta = resolver.lookup("movie-001")

        compiled = _resolve_template_segments(
            segments=segments,
            primary_seg=primary_seg,
            primary_asset_id="movie-001",
            primary_meta=primary_meta,
            resolver=resolver,
            seed=1,
        )

        assert len(compiled) == 2
        assert compiled[0]["segment_type"] == "intro"
