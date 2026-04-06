"""End-to-end scheduling correctness — deterministic system logic tests.

Proves whether the scheduling system is logically correct by bypassing
ingest/enrichment entirely and creating assets directly via StubAssetResolver
with all required fields set explicitly.

Tests validate:
  1. Pool resolution returns expected assets given type + tags + editorial
  2. Postroll assets appear in assembly output
  3. Segment order: preroll → content → postroll
  4. Budget conservation: preroll + content + postroll + filler == block
  5. Traffic directive in postroll controls fill position
  6. Missing editorial fields exclude assets from pool

No background workers. No async jobs. No CLI commands.
Pure deterministic system correctness.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.program_assembly import (
        POSTROLL_TRAFFIC_MARKER,
        assemble_schedule_block,
    )
    from retrovue.runtime.program_definition import (
        AssemblyFault,
        AssemblyResult,
        AssemblySegment,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Minimal valid asset fixtures — bypass ingest pipeline entirely
# ---------------------------------------------------------------------------

GRID_MINUTES = 30
SEED = 42


def _make_bumper(
    asset_id: str,
    duration_sec: int,
    title: str,
    tags: tuple[str, ...],
) -> AssetMetadata:
    """Create a bumper asset with all required fields for broadcast eligibility.

    Simulates a fully-enriched, approved asset:
    - state = "ready" (implied by StubAssetResolver)
    - approved_for_broadcast = True (implied by _PoolAsset defaults)
    - interstitial_type encoded in tags (e.g., "station_id" tag)
    - duration_ms derived from duration_sec
    """
    return AssetMetadata(
        type="bumper",
        duration_sec=duration_sec,
        title=title,
        tags=tags,
        file_uri=f"/mnt/bumpers/{asset_id}.mp4",
    )


def _make_promo(
    asset_id: str,
    duration_sec: int,
    title: str,
    tags: tuple[str, ...],
) -> AssetMetadata:
    """Create a promo asset with required fields."""
    return AssetMetadata(
        type="promo",
        duration_sec=duration_sec,
        title=title,
        tags=tags,
        file_uri=f"/mnt/promos/{asset_id}.mp4",
    )


def _make_movie(
    asset_id: str,
    duration_sec: int,
    title: str,
    rating: str = "PG-13",
) -> AssetMetadata:
    """Create a movie asset with required fields."""
    return AssetMetadata(
        type="movie",
        duration_sec=duration_sec,
        title=title,
        rating=rating,
        file_uri=f"/mnt/movies/{asset_id}.mkv",
    )


def _build_resolver() -> StubAssetResolver:
    """Build a resolver with a complete asset catalog and pool definitions.

    Assets simulate a fully-enriched HBO channel with:
    - Preroll: intros (bumpers) + rating cards (bumpers)
    - Content: movies
    - Postroll: coming_up_next promos + station_ids (bumpers)

    Each asset has explicit tags simulating enricher output.
    interstitial_type is encoded as a tag for pool matching.
    """
    resolver = StubAssetResolver()

    # --- Preroll assets ---
    resolver.add("hbo-intro-1", _make_bumper(
        "hbo-intro-1", 74, "HBO City Intro 1982",
        tags=("hbo", "presentation", "intros", "station_id"),
    ))
    resolver.add("hbo-intro-2", _make_bumper(
        "hbo-intro-2", 68, "HBO City Intro 1983",
        tags=("hbo", "presentation", "intros", "station_id"),
    ))
    resolver.add("rating-pg13", _make_bumper(
        "rating-pg13", 5, "PG-13 Rating Card",
        tags=("hbo", "presentation", "ratings_cards"),
    ))

    # --- Postroll assets ---
    resolver.add("station-id-1", _make_bumper(
        "station-id-1", 10, "HBO Station ID",
        tags=("hbo", "station_ids", "station_id"),
    ))
    resolver.add("station-id-2", _make_bumper(
        "station-id-2", 8, "HBO Station ID Alt",
        tags=("hbo", "station_ids", "station_id"),
    ))
    resolver.add("coming-up-1", _make_promo(
        "coming-up-1", 15, "Coming Up Next",
        tags=("hbo", "coming_up_next"),
    ))

    # --- Content assets ---
    resolver.add("movie-001", _make_movie("movie-001", 5400, "Taken"))
    resolver.add("movie-002", _make_movie("movie-002", 4800, "Click"))

    # --- Assets with MISSING editorial (negative test) ---
    # Bumper without interstitial_type tag and without hbo tag
    resolver.add("orphan-bumper", AssetMetadata(
        type="bumper",
        duration_sec=15,
        title="Orphan Bumper No Tags",
        tags=(),  # No tags at all
        file_uri="/mnt/bumpers/orphan.mp4",
    ))
    # Promo without required channel tag
    resolver.add("untagged-promo", AssetMetadata(
        type="promo",
        duration_sec=20,
        title="Untagged Promo",
        tags=("coming_up_next",),  # Missing "hbo" tag
        file_uri="/mnt/promos/untagged.mp4",
    ))

    # --- Register pools ---
    resolver.register_pools({
        "intros": {
            "match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]},
        },
        "ratings_cards": {
            "match": {"type": "bumper", "tags": ["hbo", "presentation", "ratings_cards"]},
        },
        "station_ids": {
            "match": {"type": "bumper", "tags": ["hbo", "station_ids"]},
        },
        "coming_up_next_promos": {
            "match": {"type": "promo", "tags": ["hbo", "coming_up_next"]},
        },
        "movies": {
            "match": {"type": "movie"},
        },
    })

    return resolver


def _assemble_with_postroll(
    resolver: StubAssetResolver,
    *,
    seed: int = SEED,
    grid_blocks: int = 4,
) -> list[AssemblyResult]:
    """Run assembly with preroll + postroll presentation."""
    return assemble_schedule_block(
        program_ref="hbo_movies",
        program_def={
            "pool": "movies",
            "grid_blocks": grid_blocks,
            "fill_mode": "single",
            "presentation": [
                {"pool": "intros"},
                {"pool": "ratings_cards"},
            ],
            "presentation_postroll": [
                {"pool": "coming_up_next_promos"},
                {"pool": "station_ids"},
            ],
        },
        pool_name="movies",
        slots=grid_blocks,
        progression="random",
        grid_minutes=GRID_MINUTES,
        resolver=resolver,
        bleed=True,
        seed=seed,
    )


# ===========================================================================
# Step 3 — Pool resolution: correct assets returned
# ===========================================================================


class TestPoolReturnsExpectedAssets:
    """Pool queries must return exactly the assets matching type + tags."""

    # Tier: 1 | Structural invariant
    def test_station_ids_pool_returns_station_id_assets(self):
        """station_ids pool matches bumpers tagged [hbo, station_ids]."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("station_ids")

        assert "station-id-1" in results
        assert "station-id-2" in results
        assert len(results) == 2

    # Tier: 1 | Structural invariant
    def test_intros_pool_returns_intro_assets(self):
        """intros pool matches bumpers tagged [hbo, presentation, intros]."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("intros")

        assert "hbo-intro-1" in results
        assert "hbo-intro-2" in results
        assert len(results) == 2

    # Tier: 1 | Structural invariant
    def test_coming_up_next_pool_returns_promos(self):
        """coming_up_next_promos pool matches promos tagged [hbo, coming_up_next]."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("coming_up_next_promos")

        assert results == ["coming-up-1"]

    # Tier: 1 | Structural invariant
    def test_movies_pool_returns_content(self):
        """movies pool returns all type=movie assets."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("movies")

        assert "movie-001" in results
        assert "movie-002" in results
        assert len(results) == 2

    # Tier: 1 | Structural invariant
    def test_pool_excludes_wrong_type(self):
        """station_ids pool must not return promos or movies."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("station_ids")

        assert "coming-up-1" not in results  # promo, not bumper
        assert "movie-001" not in results

    # Tier: 1 | Structural invariant
    def test_pool_excludes_wrong_tags(self):
        """intros pool must not return bumpers without matching tags."""
        resolver = _build_resolver()
        results = resolver.resolve_pool("intros")

        # station-id-1 is a bumper with hbo tag but missing "presentation" and "intros" tags
        assert "station-id-1" not in results
        assert "orphan-bumper" not in results


# ===========================================================================
# Step 4 — Postroll assets selected in assembly
# ===========================================================================


class TestPostrollAssetsSelected:
    """Postroll pool references must resolve to actual assets in assembly."""

    # Tier: 2 | Scheduling logic invariant
    def test_postroll_assets_present_in_segments(self):
        """Assembly output must contain postroll presentation segments
        with asset IDs from the postroll pools.
        """
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)

        assert len(results) >= 1
        result = results[0]

        # Find content boundary
        content_indices = [
            i for i, s in enumerate(result.segments)
            if s.segment_type == "content"
        ]
        assert content_indices, "Must have content segments"
        last_content_idx = content_indices[-1]

        # Postroll presentation segments must exist after content
        postroll_segs = [
            s for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]
        assert len(postroll_segs) >= 2, (
            f"Expected >=2 postroll segments, got {len(postroll_segs)}. "
            f"Segment types: {[s.segment_type for s in result.segments]}"
        )

        # First postroll must be from coming_up_next_promos pool
        assert postroll_segs[0].asset_id == "coming-up-1", (
            f"First postroll must be coming_up_next, got {postroll_segs[0].asset_id}"
        )

        # Second postroll must be from station_ids pool
        assert postroll_segs[1].asset_id in ("station-id-1", "station-id-2"), (
            f"Second postroll must be a station ID, got {postroll_segs[1].asset_id}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_postroll_segments_have_nonzero_duration(self):
        """Each postroll segment must carry its asset's actual duration."""
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        content_indices = [
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        ]
        last_content_idx = content_indices[-1]

        postroll_segs = [
            s for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]

        for seg in postroll_segs:
            assert seg.duration_ms > 0, (
                f"Postroll segment {seg.asset_id} has zero duration"
            )


# ===========================================================================
# Step 5 — Segment ordering: preroll → content → postroll
# ===========================================================================


class TestSegmentOrderPrerollContentPostroll:
    """INV-PRESENTATION-PRECEDES-PRIMARY-001 + INV-PRESENTATION-FOLLOWS-CONTENT-001."""

    # Tier: 1 | Structural invariant
    def test_preroll_before_content_before_postroll(self):
        """Segment order must be: preroll presentation → content → postroll presentation."""
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        # Classify segments by position
        first_content_idx = next(
            i for i, s in enumerate(result.segments)
            if s.segment_type == "content"
        )
        last_content_idx = max(
            i for i, s in enumerate(result.segments)
            if s.segment_type == "content"
        )

        preroll_indices = [
            i for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i < first_content_idx
        ]
        postroll_indices = [
            i for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]

        # INV-PRESENTATION-PRECEDES-PRIMARY-001
        assert len(preroll_indices) >= 1, "Must have at least one preroll segment"
        assert all(
            idx < first_content_idx for idx in preroll_indices
        ), "All preroll must precede content"

        # INV-PRESENTATION-FOLLOWS-CONTENT-001
        assert len(postroll_indices) >= 1, "Must have at least one postroll segment"
        assert all(
            idx > last_content_idx for idx in postroll_indices
        ), "All postroll must follow content"

    # Tier: 1 | Structural invariant
    def test_no_presentation_between_content_segments(self):
        """No presentation segments should appear between content segments.

        If there are multiple content segments (accumulate mode), presentation
        must be exclusively before-first or after-last.
        """
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        content_indices = [
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        ]
        if len(content_indices) < 2:
            return  # Only one content segment — nothing to check

        first_content = content_indices[0]
        last_content = content_indices[-1]

        interstitial_pres = [
            i for i, s in enumerate(result.segments)
            if s.segment_type == "presentation"
            and first_content < i < last_content
        ]
        assert len(interstitial_pres) == 0, (
            f"Presentation segments found between content: indices {interstitial_pres}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_postroll_declared_order_preserved(self):
        """Postroll entries must appear in YAML-declared order.

        INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: [coming_up_next, station_ids]
        → coming_up_next appears first.
        """
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        last_content_idx = max(
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        )
        postroll_segs = [
            s for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]

        assert postroll_segs[0].asset_id == "coming-up-1", (
            f"First postroll must be coming_up_next, got {postroll_segs[0].asset_id}"
        )
        assert postroll_segs[1].asset_id in ("station-id-1", "station-id-2"), (
            f"Second postroll must be station_id, got {postroll_segs[1].asset_id}"
        )


# ===========================================================================
# Step 6 — Budget conservation
# ===========================================================================


class TestPostrollDurationReserved:
    """INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001 + INV-PRESENTATION-GRID-BUDGET-001."""

    # Tier: 1 | Structural invariant
    def test_wrapper_includes_both_preroll_and_postroll(self):
        """Total wrapper_ms = preroll + postroll, deducted from grid budget."""
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        first_content_idx = next(
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        )
        last_content_idx = max(
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        )

        preroll_ms = sum(
            s.duration_ms for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i < first_content_idx
        )
        content_ms = sum(
            s.duration_ms for s in result.segments if s.segment_type == "content"
        )
        postroll_ms = sum(
            s.duration_ms for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        )

        # Postroll must have non-zero reserved time
        assert postroll_ms > 0, (
            "INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001: postroll must reserve non-zero duration"
        )

        # Preroll must have non-zero reserved time
        assert preroll_ms > 0, (
            "INV-PRESENTATION-GRID-BUDGET-001: preroll must reserve non-zero duration"
        )

        # Structural total must not exceed grid (bleed may exceed for content,
        # but wrapper is always budget-deducted)
        grid_ms = 4 * GRID_MINUTES * 60 * 1000
        assert preroll_ms + postroll_ms < grid_ms, (
            f"Wrapper ({preroll_ms + postroll_ms}ms) must not consume entire grid ({grid_ms}ms)"
        )

    # Tier: 1 | Structural invariant
    def test_total_segment_sum_equals_total_runtime(self):
        """sum(segment.duration_ms) == result.total_runtime_ms."""
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        seg_sum = sum(s.duration_ms for s in result.segments)
        assert seg_sum == result.total_runtime_ms, (
            f"Segment sum ({seg_sum}ms) != total_runtime ({result.total_runtime_ms}ms)"
        )


# ===========================================================================
# Step 7 — Traffic directive controls fill position
# ===========================================================================


class TestPostrollTrafficControlsFill:
    """INV-DSL-UNIFIED-FILL-001: traffic directive in postroll positions fill."""

    # Tier: 2 | Scheduling logic invariant
    def test_traffic_marker_appears_in_postroll(self):
        """A { type: traffic } postroll entry produces a postroll_traffic
        segment in the assembly output at the declared position.
        """
        resolver = _build_resolver()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                "presentation_postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"type": "traffic", "profile": "hbo_premium", "fill": "remaining"},
                    {"pool": "station_ids"},
                ],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        result = results[0]
        seg_types = [s.segment_type for s in result.segments]

        # Traffic marker must exist
        assert "postroll_traffic" in seg_types, (
            f"INV-DSL-UNIFIED-FILL-001: postroll_traffic segment missing. "
            f"Types: {seg_types}"
        )

        # Traffic marker must appear after content
        traffic_idx = seg_types.index("postroll_traffic")
        last_content_idx = max(
            i for i, t in enumerate(seg_types) if t == "content"
        )
        assert traffic_idx > last_content_idx, (
            "Traffic marker must appear after content"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_traffic_marker_between_postroll_segments(self):
        """Traffic marker preserves declared position within postroll sequence:
        [coming_up_next, TRAFFIC, station_ids].
        """
        resolver = _build_resolver()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                "presentation_postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"type": "traffic", "profile": "hbo_premium", "fill": "remaining"},
                    {"pool": "station_ids"},
                ],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        result = results[0]

        # Extract post-content segments only
        last_content_idx = max(
            i for i, s in enumerate(result.segments) if s.segment_type == "content"
        )
        post_content = result.segments[last_content_idx + 1:]
        post_types = [s.segment_type for s in post_content]

        # Expected order: presentation (coming_up_next), postroll_traffic, presentation (station_id)
        pres_and_traffic = [
            t for t in post_types if t in ("presentation", "postroll_traffic")
        ]
        assert pres_and_traffic == [
            "presentation", "postroll_traffic", "presentation"
        ], (
            f"Declared order not preserved. Post-content types: {pres_and_traffic}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_no_traffic_in_preroll_only_block(self):
        """Block without traffic directive produces no postroll_traffic segment."""
        resolver = _build_resolver()
        results = _assemble_with_postroll(resolver)
        result = results[0]

        traffic_segs = [
            s for s in result.segments if s.segment_type == "postroll_traffic"
        ]
        assert len(traffic_segs) == 0, (
            "Block without traffic directive must not produce postroll_traffic segments"
        )


# ===========================================================================
# Step 8 — Missing editorial excludes asset from pool
# ===========================================================================


class TestMissingEditorialExcludesAsset:
    """Assets without required editorial fields must not appear in pool results."""

    # Tier: 1 | Structural invariant
    def test_asset_without_tags_excluded_from_tag_pool(self):
        """orphan-bumper (no tags) must not appear in any tag-filtered pool."""
        resolver = _build_resolver()

        # station_ids requires tags [hbo, station_ids]
        results = resolver.resolve_pool("station_ids")
        assert "orphan-bumper" not in results

        # intros requires tags [hbo, presentation, intros]
        results = resolver.resolve_pool("intros")
        assert "orphan-bumper" not in results

    # Tier: 1 | Structural invariant
    def test_asset_missing_channel_tag_excluded(self):
        """untagged-promo has "coming_up_next" but not "hbo" — excluded."""
        resolver = _build_resolver()

        # coming_up_next_promos requires tags [hbo, coming_up_next]
        results = resolver.resolve_pool("coming_up_next_promos")
        assert "untagged-promo" not in results
        assert "coming-up-1" in results  # control: properly-tagged promo IS included

    # Tier: 1 | Structural invariant
    def test_wrong_type_excluded_even_with_correct_tags(self):
        """A promo with station_ids tags is excluded from bumper-type pool."""
        resolver = _build_resolver()

        # Add a promo that has station_ids tags but wrong type
        resolver.add("fake-station-promo", AssetMetadata(
            type="promo",  # Wrong type — pool expects "bumper"
            duration_sec=10,
            title="Fake Station Promo",
            tags=("hbo", "station_ids"),
            file_uri="/mnt/promos/fake.mp4",
        ))

        results = resolver.resolve_pool("station_ids")
        assert "fake-station-promo" not in results

    # Tier: 1 | Structural invariant
    def test_empty_pool_raises_on_resolve(self):
        """Pool matching zero assets raises KeyError on resolve."""
        resolver = _build_resolver()
        resolver.register_pools({
            "nonexistent": {"match": {"type": "bumper", "tags": ["nonexistent_tag"]}},
        })

        with pytest.raises(KeyError):
            resolver.resolve_pool("nonexistent")

    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_in_presentation_skipped_gracefully(self):
        """INV-DSL-MISSING-ASSET-NONFATAL-001: empty pool in presentation
        is omitted, not fatal.
        """
        resolver = _build_resolver()
        resolver.register_pools({
            "empty_bumpers": {"match": {"type": "bumper", "tags": ["nonexistent"]}},
        })

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [
                    {"pool": "empty_bumpers"},  # resolves to 0 assets → skip
                    {"pool": "intros"},          # resolves normally
                ],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        # Only the intros pool resolved — empty_bumpers was skipped
        assert len(pres_segs) == 1
        assert pres_segs[0].asset_id in ("hbo-intro-1", "hbo-intro-2")


# ===========================================================================
# Step 9 — Deterministic reproducibility
# ===========================================================================


class TestDeterministicReproducibility:
    """Same seed + same catalog → identical assembly output."""

    # Tier: 1 | Structural invariant
    def test_same_seed_same_output(self):
        """Two runs with identical seed and catalog produce identical segments."""
        resolver = _build_resolver()

        results_a = _assemble_with_postroll(resolver, seed=42)
        results_b = _assemble_with_postroll(resolver, seed=42)

        segs_a = [(s.asset_id, s.duration_ms, s.segment_type) for s in results_a[0].segments]
        segs_b = [(s.asset_id, s.duration_ms, s.segment_type) for s in results_b[0].segments]
        assert segs_a == segs_b, "Same seed must produce identical segments"

    # Tier: 1 | Structural invariant
    def test_different_seed_may_vary(self):
        """Different seeds may select different pool assets."""
        resolver = _build_resolver()

        # Run with many different seeds and collect intro selections
        selections = set()
        for seed in range(100):
            results = _assemble_with_postroll(resolver, seed=seed)
            pres_segs = [
                s for s in results[0].segments if s.segment_type == "presentation"
            ]
            if pres_segs:
                selections.add(pres_segs[0].asset_id)

        # With two intros in the pool, both should eventually be selected
        assert len(selections) >= 2, (
            f"Expected pool RNG to produce variety, got: {selections}"
        )
