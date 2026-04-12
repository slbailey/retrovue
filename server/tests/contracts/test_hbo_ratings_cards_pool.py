"""Contract tests for HBO ratings_cards pool resolution.

Validates that the real hbo.yaml config's ratings_cards pool resolves
bumper assets with correct tags, and that the contextual select
(tags eq program.rating_tag) correctly narrows to rating-specific cards.

Contracts: INV-DSL-MISSING-ASSET-NONFATAL-001, INV-POOL-TAGS-FILTER-001
Parent issue: RETA-176
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from retrovue.runtime.asset_resolver import AssetMetadata
from retrovue.dev.stub_asset_resolver import StubAssetResolver
from retrovue.runtime.pool_dsl_normalize import normalize_pool_definition
from retrovue.runtime.program_assembly import assemble_schedule_block


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

HBO_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "channels" / "hbo.yaml"


def _load_hbo_config() -> dict:
    """Load and parse the real hbo.yaml channel config."""
    assert HBO_CONFIG_PATH.exists(), f"HBO config not found: {HBO_CONFIG_PATH}"
    with open(HBO_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Resolver factory — mirrors production asset catalog shapes
# ---------------------------------------------------------------------------

# Production has 8 bumper assets with tags: hbo, presentation, ratings_cards
# plus a per-rating tag (g, pg, pg13, r).
_PRODUCTION_RATINGS_CARDS = {
    "hbo-rc-g-1": ("hbo", "presentation", "ratings_cards", "g"),
    "hbo-rc-g-2": ("hbo", "presentation", "ratings_cards", "g"),
    "hbo-rc-pg-1": ("hbo", "presentation", "ratings_cards", "pg"),
    "hbo-rc-pg-2": ("hbo", "presentation", "ratings_cards", "pg"),
    "hbo-rc-pg13-1": ("hbo", "presentation", "ratings_cards", "pg13"),
    "hbo-rc-pg13-2": ("hbo", "presentation", "ratings_cards", "pg13"),
    "hbo-rc-r-1": ("hbo", "presentation", "ratings_cards", "r"),
    "hbo-rc-r-2": ("hbo", "presentation", "ratings_cards", "r"),
}


def _make_resolver(
    *,
    movie_rating: str = "PG",
    include_ratings_cards: bool = True,
) -> StubAssetResolver:
    """Build a resolver with HBO-shaped assets and pools from real config."""
    config = _load_hbo_config()
    resolver = StubAssetResolver()

    # Register intro bumpers
    resolver.add("hbo-intro-1", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO City 1982",
        tags=("hbo", "presentation", "intros"),
    ))

    # Register ratings card bumpers
    if include_ratings_cards:
        for card_id, tags in _PRODUCTION_RATINGS_CARDS.items():
            resolver.add(card_id, AssetMetadata(
                type="bumper", duration_sec=10, title=f"Ratings Card {card_id}",
                tags=tags,
            ))

    # Register station IDs
    resolver.add("hbo-sid-1", AssetMetadata(
        type="station_id", duration_sec=5, title="HBO Station ID",
        tags=("hbo", "station_ids"),
    ))

    # Register promos
    resolver.add("hbo-promo-1", AssetMetadata(
        type="promo", duration_sec=30, title="Coming Up Next",
        tags=("hbo", "coming_up_next"),
    ))

    # Register movies
    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="Ghostbusters",
        rating=movie_rating,
    ))
    resolver.add("movie-002", AssetMetadata(
        type="movie", duration_sec=5000, title="E.T.",
        rating=movie_rating,
    ))

    # Register trailers and teasers for traffic pools
    resolver.add("trailer-001", AssetMetadata(
        type="trailer", duration_sec=120, title="Trailer 1",
    ))
    resolver.add("teaser-001", AssetMetadata(
        type="teaser", duration_sec=30, title="Teaser 1",
    ))

    # Register pools from the REAL hbo.yaml config
    pools_dsl = config.get("pools", {})
    normalized = {
        name: normalize_pool_definition(defn)
        for name, defn in pools_dsl.items()
    }
    resolver.register_pools(normalized)

    return resolver


# ===========================================================================
# Base pool resolution — ratings_cards pool must resolve >= 1 asset
# ===========================================================================


@pytest.mark.contract
class TestHboRatingsCardsBaseResolution:
    """INV-POOL-TAGS-FILTER-001: HBO ratings_cards pool must resolve assets
    when bumper assets with [hbo, presentation, ratings_cards] tags exist."""

    def test_ratings_cards_pool_resolves_nonzero(self):
        """ratings_cards pool resolves >= 1 asset from production-shaped catalog."""
        resolver = _make_resolver()
        matched = resolver.query(
            resolver._pools["ratings_cards"].get("match", {}),
        )
        assert len(matched) >= 1, (
            f"ratings_cards pool resolved {len(matched)} assets — "
            f"expected >= 1 with production-shaped bumper assets"
        )

    def test_ratings_cards_pool_resolves_all_production_cards(self):
        """All 8 production-shaped ratings cards are matched."""
        resolver = _make_resolver()
        matched = resolver.query(
            resolver._pools["ratings_cards"].get("match", {}),
        )
        assert len(matched) == 8, (
            f"Expected 8 ratings cards (matching production), got {len(matched)}: {matched}"
        )

    def test_ratings_cards_pool_match_criteria_correct(self):
        """The normalized pool match criteria are type=bumper + tags=[hbo, presentation, ratings_cards]."""
        config = _load_hbo_config()
        pool_def = config["pools"]["ratings_cards"]
        normalized = normalize_pool_definition(pool_def)
        match = normalized.get("match", {})

        assert match.get("type") == "bumper", (
            f"Expected type=bumper, got {match.get('type')}"
        )
        assert set(match.get("tags", [])) == {"hbo", "presentation", "ratings_cards"}, (
            f"Expected tags=[hbo, presentation, ratings_cards], got {match.get('tags')}"
        )

    def test_intros_pool_also_resolves(self):
        """Sanity: intros pool resolves alongside ratings_cards."""
        resolver = _make_resolver()
        matched = resolver.query(
            resolver._pools["intros"].get("match", {}),
        )
        assert len(matched) >= 1, (
            f"intros pool should also resolve — got {len(matched)} assets"
        )


# ===========================================================================
# Contextual select — tags eq program.rating_tag
# ===========================================================================


@pytest.mark.contract
class TestHboRatingsCardsContextualSelect:
    """INV-PRESENTATION-CONTEXTUAL-SELECT-001: contextual select in HBO
    movies presentation correctly narrows ratings_cards by program.rating_tag."""

    def _get_movies_presentation(self) -> list[dict]:
        """Extract the presentation.programs.movies config from real hbo.yaml."""
        config = _load_hbo_config()
        pres = config.get("presentation", {})
        programs = pres.get("programs", {})
        movies_pres = programs.get("movies", {})
        # Combine preroll + postroll for full presentation stack
        preroll = movies_pres.get("preroll", [])
        return preroll

    def _assemble_with_rating(self, rating: str, seed: int = 42) -> list:
        """Assemble a movie block with the given rating and HBO presentation."""
        config = _load_hbo_config()
        preroll = self._get_movies_presentation()
        resolver = _make_resolver(movie_rating=rating)

        return assemble_schedule_block(
            program_ref="hbo_movies_test",
            program_def={
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "presentation": "movies",
            },
            pool_name="movies",
            slots=5,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=seed,
            channel_id="hbo",
        )

    def test_g_movie_gets_g_rating_card(self):
        """G-rated movie produces a presentation segment from a G ratings card."""
        resolver = _make_resolver(movie_rating="G")
        preroll = self._get_movies_presentation()

        results = assemble_schedule_block(
            program_ref="hbo_movies_g",
            program_def={
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "presentation": preroll,
            },
            pool_name="movies",
            slots=5,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        # Should have at least 2 presentation segments: intro + ratings card
        assert len(pres_segs) >= 2, (
            f"Expected >= 2 presentation segments (intro + ratings card), "
            f"got {len(pres_segs)}: {[(s.asset_id, s.segment_type) for s in result.segments]}"
        )
        # One of the presentation segments should be a G ratings card
        g_card_ids = {cid for cid, tags in _PRODUCTION_RATINGS_CARDS.items() if "g" in tags}
        ratings_card_segs = [s for s in pres_segs if s.asset_id in g_card_ids]
        assert len(ratings_card_segs) >= 1, (
            f"Expected a G ratings card in presentation, "
            f"got segments: {[s.asset_id for s in pres_segs]}"
        )

    def test_r_movie_gets_r_rating_card(self):
        """R-rated movie produces a presentation segment from an R ratings card."""
        resolver = _make_resolver(movie_rating="R")
        preroll = self._get_movies_presentation()

        results = assemble_schedule_block(
            program_ref="hbo_movies_r",
            program_def={
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "presentation": preroll,
            },
            pool_name="movies",
            slots=5,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        r_card_ids = {cid for cid, tags in _PRODUCTION_RATINGS_CARDS.items() if "r" in tags}
        ratings_card_segs = [s for s in pres_segs if s.asset_id in r_card_ids]
        assert len(ratings_card_segs) >= 1, (
            f"Expected an R ratings card in presentation, "
            f"got segments: {[s.asset_id for s in pres_segs]}"
        )

    def test_pg13_movie_gets_pg13_rating_card(self):
        """PG-13-rated movie produces a presentation segment from a PG-13 ratings card."""
        resolver = _make_resolver(movie_rating="PG-13")
        preroll = self._get_movies_presentation()

        results = assemble_schedule_block(
            program_ref="hbo_movies_pg13",
            program_def={
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "presentation": preroll,
            },
            pool_name="movies",
            slots=5,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]
        pres_segs = [s for s in result.segments if s.segment_type == "presentation"]
        pg13_card_ids = {cid for cid, tags in _PRODUCTION_RATINGS_CARDS.items() if "pg13" in tags}
        ratings_card_segs = [s for s in pres_segs if s.asset_id in pg13_card_ids]
        assert len(ratings_card_segs) >= 1, (
            f"Expected a PG-13 ratings card in presentation, "
            f"got segments: {[s.asset_id for s in pres_segs]}"
        )

    def test_empty_ratings_cards_pool_degrades_gracefully(self):
        """INV-DSL-MISSING-ASSET-NONFATAL-001: empty pool skips segment, no crash."""
        resolver = _make_resolver(include_ratings_cards=False)
        preroll = self._get_movies_presentation()

        results = assemble_schedule_block(
            program_ref="hbo_movies_g",
            program_def={
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "presentation": preroll,
            },
            pool_name="movies",
            slots=5,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]
        # Content segment should still exist — only the ratings card is missing
        content_segs = [s for s in result.segments if s.segment_type == "content"]
        assert len(content_segs) >= 1, "Content must still air even without ratings cards"
