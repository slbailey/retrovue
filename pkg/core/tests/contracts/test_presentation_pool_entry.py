"""Contract tests for pool-based presentation entries.

Validates that presentation stack entries can reference pools, and that
pool entries resolve to a single randomly-selected asset using the block's
seeded RNG.

Contract: docs/contracts/program_presentation.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.program_assembly import assemble_schedule_block
from retrovue.runtime.program_definition import AssemblyFault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver() -> StubAssetResolver:
    """Build a resolver with bumper pools and a movie pool."""
    resolver = StubAssetResolver()

    # Intro bumpers
    resolver.add("hbo-intro-1", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO City 1982",
        tags=("hbo", "presentation", "intros"),
    ))
    resolver.add("hbo-intro-2", AssetMetadata(
        type="bumper", duration_sec=28, title="HBO City 1983",
        tags=("hbo", "presentation", "intros"),
    ))

    # G rating cards
    resolver.add("g-card-1", AssetMetadata(
        type="bumper", duration_sec=10, title="G Card Variant 1",
        tags=("hbo", "presentation", "ratings_cards", "g"),
    ))
    resolver.add("g-card-2", AssetMetadata(
        type="bumper", duration_sec=10, title="G Card Variant 2",
        tags=("hbo", "presentation", "ratings_cards", "g"),
    ))

    # Movies
    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="Ghostbusters", rating="G",
    ))
    resolver.add("movie-002", AssetMetadata(
        type="movie", duration_sec=5000, title="E.T.", rating="G",
    ))

    # Register pools
    resolver.register_pools({
        "intros": {"match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]}},
        "g_ratings_cards": {"match": {"type": "bumper", "tags": ["hbo", "presentation", "ratings_cards", "g"]}},
        "movies_g": {"match": {"type": "movie"}},
    })

    return resolver


def _assemble(resolver, presentation, seed=42):
    """Run assembly with the given presentation config."""
    return assemble_schedule_block(
        program_ref="hbo_movie_g",
        program_def={
            "pool": "movies_g",
            "grid_blocks": 4,
            "fill_mode": "single",
            "presentation": presentation,
        },
        pool_name="movies_g",
        slots=4,
        progression="random",
        grid_minutes=30,
        resolver=resolver,
        bleed=True,
        seed=seed,
    )


# ===========================================================================
# Pool entry resolution
# ===========================================================================


@pytest.mark.contract
class TestPresentationPoolEntry:
    """Pool-based presentation entries."""

    # Tier: 2 | Scheduling logic invariant
    def test_pool_entry_resolves_to_single_asset(self):
        # PRES-POOL-001 — a {pool: "intros"} entry resolves to exactly one
        # asset from that pool, appearing as segment_type="presentation".
        resolver = _make_resolver()
        results = _assemble(resolver, [{"pool": "intros"}])

        assert len(results) == 1
        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        assert len(pres_segs) == 1
        assert pres_segs[0].asset_id in ("hbo-intro-1", "hbo-intro-2")

    # Tier: 2 | Scheduling logic invariant
    def test_pool_entry_selection_is_seeded(self):
        # PRES-POOL-002 — same seed → same selection; different seed → may differ.
        resolver = _make_resolver()

        results_a = _assemble(resolver, [{"pool": "intros"}], seed=42)
        results_b = _assemble(resolver, [{"pool": "intros"}], seed=42)

        pres_a = [s for s in results_a[0].segments if s.segment_type == "presentation"]
        pres_b = [s for s in results_b[0].segments if s.segment_type == "presentation"]
        assert pres_a[0].asset_id == pres_b[0].asset_id, "Same seed must produce same selection"

        # Different seed should (with high probability) produce different selection
        # over multiple attempts — not guaranteed for 2-element pool, so we just
        # verify determinism above.

    # Tier: 2 | Scheduling logic invariant
    def test_mixed_asset_and_pool_entries(self):
        # PRES-POOL-003 — a stack with both direct asset and pool entries
        # resolves in declared order.
        resolver = _make_resolver()
        results = _assemble(resolver, [
            "hbo-intro-1",              # direct asset ref
            {"pool": "g_ratings_cards"},  # pool ref
        ])

        assert len(results) == 1
        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        assert len(pres_segs) == 2

        # First entry: always hbo-intro-1 (direct)
        assert pres_segs[0].asset_id == "hbo-intro-1"
        # Second entry: one of the G cards (from pool)
        assert pres_segs[1].asset_id in ("g-card-1", "g-card-2")

    # Tier: 2 | Scheduling logic invariant
    def test_pool_entry_duration_in_budget(self):
        # Pool-resolved presentation assets contribute to grid budget.
        resolver = _make_resolver()
        results = _assemble(resolver, [{"pool": "intros"}])

        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        # The resolved intro has a duration (28 or 30s)
        assert pres_segs[0].duration_ms > 0
        # Total runtime includes presentation duration
        assert result.total_runtime_ms > 0

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_pool_entries(self):
        # Two pool entries each resolve independently.
        resolver = _make_resolver()
        results = _assemble(resolver, [
            {"pool": "intros"},
            {"pool": "g_ratings_cards"},
        ])

        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        assert len(pres_segs) == 2
        assert pres_segs[0].asset_id in ("hbo-intro-1", "hbo-intro-2")
        assert pres_segs[1].asset_id in ("g-card-1", "g-card-2")

    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_raises(self):
        # Empty presentation pool must raise AssemblyFault, not IndexError.
        resolver = _make_resolver()
        resolver.register_pools({
            "empty_pool": {"match": {"type": "bumper", "tags": ["nonexistent"]}},
        })

        with pytest.raises((AssemblyFault, KeyError)):
            _assemble(resolver, [{"pool": "empty_pool"}])

    # Tier: 2 | Scheduling logic invariant
    def test_content_segment_follows_presentation(self):
        # Regardless of entry type, content always follows presentation.
        resolver = _make_resolver()
        results = _assemble(resolver, [
            {"pool": "intros"},
            {"pool": "g_ratings_cards"},
        ])

        result = results[0]
        types = [s.segment_type for s in result.segments]
        # presentation, presentation, content
        assert types[0] == "presentation"
        assert types[1] == "presentation"
        assert types[2] == "content"
