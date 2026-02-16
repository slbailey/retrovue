"""
Tests for the Programming DSL Schedule Compiler (v2).

Covers: parsing, validation, grid alignment, episode selection,
template expansion, program-blocks-only output, schema validation,
and hash determinism.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as tz_mod
from pathlib import Path

import jsonschema
import pytest
import yaml

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    AssetResolutionError,
    CompileError,
    ProgramBlockOutput,
    ValidationError,
    compile_schedule,
    expand_templates,
    get_channel_template,
    parse_dsl,
    select_episode,
    select_movie,
    validate_dsl,
    validate_program_blocks,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCHEMA_PATH = Path(__file__).parents[4] / "docs" / "contracts" / "core" / "programming_dsl.schema.json"


# ---------------------------------------------------------------------------
# Stub resolver factories
# ---------------------------------------------------------------------------


def make_sitcom_resolver() -> StubAssetResolver:
    """Build a resolver with all assets needed for the weeknight sitcom fixture."""
    r = StubAssetResolver()
    r.add("col.cozby_show_s3", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.episodes.coz_s3e01", "asset.episodes.coz_s3e02", "asset.episodes.coz_s3e03"),
    ))
    r.add("col.cheers_s6", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.episodes.cheers_s6e01", "asset.episodes.cheers_s6e02"),
    ))
    r.add("col.taxi_s2", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.episodes.taxi_s2e01", "asset.episodes.taxi_s2e02"),
    ))
    for ep in ("asset.episodes.coz_s3e01", "asset.episodes.coz_s3e02", "asset.episodes.coz_s3e03"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    for ep in ("asset.episodes.cheers_s6e01", "asset.episodes.cheers_s6e02"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    for ep in ("asset.episodes.taxi_s2e01", "asset.episodes.taxi_s2e02"):
        r.add(ep, AssetMetadata(type="episode", duration_sec=1320, rating="PG"))
    return r


def make_movie_resolver() -> StubAssetResolver:
    """Build a resolver with all assets needed for the weekend movie fixture."""
    r = StubAssetResolver()
    r.add("col.movies.blockbusters_70s_90s", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.movies.back_to_future", "asset.movies.indiana_jones"),
    ))
    r.add("col.movies.family_adventure", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.movies.goonies", "asset.movies.princess_bride"),
    ))
    r.add("col.movies.late_night_thrillers", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.movies.alien", "asset.movies.thing"),
    ))
    r.add("asset.movies.back_to_future", AssetMetadata(type="movie", duration_sec=6960, rating="PG"))
    r.add("asset.movies.indiana_jones", AssetMetadata(type="movie", duration_sec=6900, rating="PG"))
    r.add("asset.movies.goonies", AssetMetadata(type="movie", duration_sec=6840, rating="PG"))
    r.add("asset.movies.princess_bride", AssetMetadata(type="movie", duration_sec=5880, rating="PG"))
    r.add("asset.movies.alien", AssetMetadata(type="movie", duration_sec=7020, rating="R"))
    r.add("asset.movies.thing", AssetMetadata(type="movie", duration_sec=6480, rating="R"))
    return r


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    def test_parse_weeknight_sitcom(self):
        yaml_text = (FIXTURES_DIR / "weeknight_sitcom.yaml").read_text()
        dsl = parse_dsl(yaml_text)
        assert dsl["channel"] == "retro_prime"
        assert dsl["broadcast_day"] == "1989-10-12"
        assert "templates" in dsl
        assert "weeknight_sitcom_block" in dsl["templates"]

    def test_parse_weekend_movie(self):
        yaml_text = (FIXTURES_DIR / "weekend_movie.yaml").read_text()
        dsl = parse_dsl(yaml_text)
        assert dsl["channel"] == "retro_movies"
        assert dsl["template"] == "premium_movie"
        assert isinstance(dsl["schedule"]["saturday"], list)
        assert len(dsl["schedule"]["saturday"]) == 2


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_required_fields(self):
        errors = validate_dsl({}, StubAssetResolver())
        assert any("channel" in e for e in errors)
        assert any("broadcast_day" in e for e in errors)
        assert any("schedule" in e for e in errors)

    def test_missing_asset_raises_error(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        errors = validate_dsl(dsl, StubAssetResolver())
        assert len(errors) > 0
        assert any("not found" in e for e in errors)

    def test_valid_dsl_no_errors(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        errors = validate_dsl(dsl, resolver)
        assert errors == []

    def test_overlap_detection(self):
        b1 = ProgramBlockOutput(title="A", asset_id="a", start_at=datetime(2024, 1, 1, 20, 0, tzinfo=tz_mod.utc), slot_duration_sec=1800, episode_duration_sec=1320)
        b2 = ProgramBlockOutput(title="B", asset_id="b", start_at=datetime(2024, 1, 1, 20, 15, tzinfo=tz_mod.utc), slot_duration_sec=1800, episode_duration_sec=1320)
        errors = validate_program_blocks([b1, b2])
        assert len(errors) == 1
        assert "Overlap" in errors[0]

    def test_no_overlap(self):
        b1 = ProgramBlockOutput(title="A", asset_id="a", start_at=datetime(2024, 1, 1, 20, 0, tzinfo=tz_mod.utc), slot_duration_sec=1800, episode_duration_sec=1320)
        b2 = ProgramBlockOutput(title="B", asset_id="b", start_at=datetime(2024, 1, 1, 20, 30, tzinfo=tz_mod.utc), slot_duration_sec=1800, episode_duration_sec=1320)
        errors = validate_program_blocks([b1, b2])
        assert errors == []


# ---------------------------------------------------------------------------
# Grid alignment tests
# ---------------------------------------------------------------------------


class TestGridAlignment:
    def test_network_grid_aligned(self):
        """Network TV slots must start at :00 or :30."""
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        for block in plan["program_blocks"]:
            start = datetime.fromisoformat(block["start_at"])
            assert start.minute % 30 == 0, f"Block starts at :{start.minute}, not grid-aligned"

    def test_premium_grid_aligned(self):
        """Premium movie slots must start at :00 or :15/:30/:45."""
        dsl = parse_dsl((FIXTURES_DIR / "weekend_movie.yaml").read_text())
        resolver = make_movie_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        for block in plan["program_blocks"]:
            start = datetime.fromisoformat(block["start_at"])
            assert start.minute % 15 == 0, f"Block starts at :{start.minute}, not grid-aligned"

    def test_off_grid_rejected(self):
        """Off-grid start times must be rejected."""
        from retrovue.runtime.schedule_compiler import validate_grid_alignment
        errors = validate_grid_alignment("20:17", 30)
        assert len(errors) == 1
        assert "not aligned" in errors[0]


# ---------------------------------------------------------------------------
# Template expansion tests
# ---------------------------------------------------------------------------


class TestTemplateExpansion:
    def test_expand_use_reference(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        expanded = expand_templates(dsl)
        weeknights = expanded["schedule"]["weeknights"]
        assert "use" not in weeknights
        assert "slots" in weeknights
        assert weeknights["start"] == "20:00"

    def test_unknown_template_raises(self):
        dsl = {
            "channel": "test",
            "broadcast_day": "2024-01-01",
            "timezone": "UTC",
            "schedule": {"day": {"use": "nonexistent_template"}},
        }
        with pytest.raises(CompileError, match="Unknown template"):
            expand_templates(dsl)


# ---------------------------------------------------------------------------
# Episode selector tests
# ---------------------------------------------------------------------------


class TestEpisodeSelector:
    def test_sequential_determinism(self):
        resolver = make_sitcom_resolver()
        ep1 = select_episode("col.cozby_show_s3", "sequential", resolver, seed=0)
        ep2 = select_episode("col.cozby_show_s3", "sequential", resolver, seed=0)
        assert ep1 == ep2

    def test_sequential_different_seeds(self):
        resolver = make_sitcom_resolver()
        ep0 = select_episode("col.cozby_show_s3", "sequential", resolver, seed=0)
        ep1 = select_episode("col.cozby_show_s3", "sequential", resolver, seed=1)
        assert ep0 == "asset.episodes.coz_s3e01"
        assert ep1 == "asset.episodes.coz_s3e02"

    def test_random_determinism(self):
        resolver = make_sitcom_resolver()
        ep1 = select_episode("col.cheers_s6", "random", resolver, seed=42)
        ep2 = select_episode("col.cheers_s6", "random", resolver, seed=42)
        assert ep1 == ep2


# ---------------------------------------------------------------------------
# Movie selector tests
# ---------------------------------------------------------------------------


class TestMovieSelector:
    def test_rating_filter(self):
        resolver = make_movie_resolver()
        movie = select_movie(
            ["col.movies.blockbusters_70s_90s", "col.movies.family_adventure"],
            resolver, rating_include=["PG"], seed=42,
        )
        meta = resolver.lookup(movie)
        assert meta.rating == "PG"

    def test_r_rated_filter(self):
        resolver = make_movie_resolver()
        movie = select_movie(
            ["col.movies.late_night_thrillers"],
            resolver, rating_include=["R"], seed=42,
        )
        meta = resolver.lookup(movie)
        assert meta.rating == "R"

    def test_no_candidates_raises(self):
        resolver = make_movie_resolver()
        with pytest.raises(AssetResolutionError):
            select_movie(["col.movies.blockbusters_70s_90s"], resolver, rating_include=["NC-17"], seed=42)


# ---------------------------------------------------------------------------
# No breaks in output
# ---------------------------------------------------------------------------


class TestNoBreaksInOutput:
    def test_sitcom_no_breaks(self):
        """Program schedule must contain only program blocks, no breaks/bumpers."""
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        assert "program_blocks" in plan
        assert "segments" not in plan
        for block in plan["program_blocks"]:
            assert "asset_id" in block
            assert "slot_duration_sec" in block
            assert "episode_duration_sec" in block

    def test_movie_no_breaks(self):
        """Movie schedule must contain only program blocks."""
        dsl = parse_dsl((FIXTURES_DIR / "weekend_movie.yaml").read_text())
        resolver = make_movie_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        assert "program_blocks" in plan
        for block in plan["program_blocks"]:
            assert block["slot_duration_sec"] >= block["episode_duration_sec"]


# ---------------------------------------------------------------------------
# Output schema validation
# ---------------------------------------------------------------------------


class TestOutputSchema:
    def test_weeknight_matches_schema(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        schema = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(instance=plan, schema=schema)

    def test_weekend_movie_matches_schema(self):
        dsl = parse_dsl((FIXTURES_DIR / "weekend_movie.yaml").read_text())
        resolver = make_movie_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        schema = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(instance=plan, schema=schema)


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


class TestHashDeterminism:
    def test_same_input_same_hash(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan1 = compile_schedule(dsl, resolver, seed=42)
        plan2 = compile_schedule(dsl, resolver, seed=42)
        assert plan1["hash"] == plan2["hash"]
        assert plan1["hash"].startswith("sha256:")


# ---------------------------------------------------------------------------
# Full compilation integration
# ---------------------------------------------------------------------------


class TestFullCompilation:
    def test_weeknight_compiles(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        assert plan["version"] == "program-schedule.v2"
        assert plan["channel_id"] == "retro_prime"
        assert len(plan["program_blocks"]) == 3  # 3 shows

    def test_weekend_movie_compiles(self):
        dsl = parse_dsl((FIXTURES_DIR / "weekend_movie.yaml").read_text())
        resolver = make_movie_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        assert plan["version"] == "program-schedule.v2"
        assert plan["channel_id"] == "retro_movies"
        assert len(plan["program_blocks"]) == 2  # 2 movies

    def test_notes_preserved(self):
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        assert "notes" in plan
        assert plan["notes"]["vibe"] == "Water-cooler Thursday"

    def test_slot_duration_covers_episode(self):
        """Every program block's slot_duration must be >= episode_duration."""
        dsl = parse_dsl((FIXTURES_DIR / "weeknight_sitcom.yaml").read_text())
        resolver = make_sitcom_resolver()
        plan = compile_schedule(dsl, resolver, seed=42)
        for block in plan["program_blocks"]:
            assert block["slot_duration_sec"] >= block["episode_duration_sec"]
