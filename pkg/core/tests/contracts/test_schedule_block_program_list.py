"""Contract tests for program list on schedule blocks.

Validates INV-SBLOCK-PROGRAM-001, 002, 003, 006 when the `program` field
is a list of ProgramDefinition names.

Contract: docs/contracts/schedule_block_program_reference.md
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.program_definition import AssemblyFault


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_resolver(*pools_with_movies):
    """Build a resolver with movie pools."""
    resolver = StubAssetResolver()

    # Default movies for each pool
    pool_defs = {}
    for pool_name, rating in pools_with_movies:
        asset_id = f"movie-{rating.lower()}-1"
        resolver.add(asset_id, AssetMetadata(
            type="movie", duration_sec=5400, title=f"Movie {rating}",
            rating=rating,
        ))
        pool_defs[pool_name] = {"match": {"type": "movie", "rating": {"include": [rating]}}}

    resolver.register_pools(pool_defs)
    return resolver


def _default_resolver():
    return _make_resolver(
        ("movies_pg", "PG"),
        ("movies_pg13", "PG-13"),
        ("movies_r", "R"),
    )


def _compile(resolver, block_def, programs_defs, grid_minutes=30, seed=42):
    """Call _compile_program_block through the public compile path."""
    from retrovue.runtime.schedule_compiler import _compile_program_block
    return _compile_program_block(
        block_def=block_def,
        programs=programs_defs,
        grid_minutes=grid_minutes,
        resolver=resolver,
        broadcast_day="2026-03-09",
        tz_name="America/New_York",
        seed=seed,
        channel_id="hbo",
    )


# ===========================================================================
# INV-SBLOCK-PROGRAM-001 — program list variant
# ===========================================================================


@pytest.mark.contract
class TestProgramListAcceptance:
    """INV-SBLOCK-PROGRAM-001 — list form"""

    # Tier: 2 | Scheduling logic invariant
    def test_program_list_accepted(self):
        # A non-empty list of valid program refs produces blocks.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
            "pg13_movie": {"pool": "movies_pg13", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 8,
            "program": ["pg_movie", "pg13_movie"],
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        assert len(blocks) == 2  # 8 slots / 4 grid_blocks = 2 executions

    # Tier: 2 | Scheduling logic invariant
    def test_program_list_empty_rejected(self):
        # An empty list is rejected.
        resolver = _default_resolver()
        programs = {}
        block_def = {
            "start": "10:00",
            "slots": 4,
            "program": [],
            "progression": "random",
        }

        with pytest.raises((AssemblyFault, ValueError, KeyError)):
            _compile(resolver, block_def, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_program_single_string_still_works(self):
        # A plain string still works as before (backward compat).
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 4,
            "program": "pg_movie",
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        assert len(blocks) == 1


# ===========================================================================
# INV-SBLOCK-PROGRAM-002 — all list members must resolve
# ===========================================================================


@pytest.mark.contract
class TestProgramListResolution:
    """INV-SBLOCK-PROGRAM-002 — list member resolution"""

    # Tier: 2 | Scheduling logic invariant
    def test_undefined_member_rejected(self):
        # One member not in programs dict → reject.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 4,
            "program": ["pg_movie", "nonexistent"],
            "progression": "random",
        }

        with pytest.raises((AssemblyFault, ValueError, KeyError)):
            _compile(resolver, block_def, programs)


# ===========================================================================
# INV-SBLOCK-PROGRAM-006 — uniform grid_blocks
# ===========================================================================


@pytest.mark.contract
class TestProgramListUniformGrid:
    """INV-SBLOCK-PROGRAM-006"""

    # Tier: 2 | Scheduling logic invariant
    def test_mismatched_grid_blocks_rejected(self):
        # Programs with different grid_blocks → reject.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
            "pg13_short": {"pool": "movies_pg13", "grid_blocks": 2, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 4,
            "program": ["pg_movie", "pg13_short"],
            "progression": "random",
        }

        with pytest.raises((AssemblyFault, ValueError)):
            _compile(resolver, block_def, programs)

    # Tier: 2 | Scheduling logic invariant
    def test_uniform_grid_blocks_accepted(self):
        # All programs same grid_blocks → accept.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
            "pg13_movie": {"pool": "movies_pg13", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 8,
            "program": ["pg_movie", "pg13_movie"],
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        assert len(blocks) == 2


# ===========================================================================
# Per-execution selection
# ===========================================================================


@pytest.mark.contract
class TestProgramListPerExecution:
    """Per-execution program selection from list."""

    # Tier: 2 | Scheduling logic invariant
    def test_selects_per_execution(self):
        # With 2 programs and 2 executions, both programs may appear.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
            "pg13_movie": {"pool": "movies_pg13", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 8,
            "program": ["pg_movie", "pg13_movie"],
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        assert len(blocks) == 2
        # Each block assembled from one of the programs
        collections = {b.collection for b in blocks}
        # At least one pool should appear (both likely with many seeds)
        assert collections.issubset({"movies_pg", "movies_pg13"})

    # Tier: 2 | Scheduling logic invariant
    def test_selection_is_seeded(self):
        # Same seed → same selections.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {"pool": "movies_pg", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
            "pg13_movie": {"pool": "movies_pg13", "grid_blocks": 4, "fill_mode": "single", "bleed": True},
        }
        block_def = {
            "start": "10:00",
            "slots": 8,
            "program": ["pg_movie", "pg13_movie"],
            "progression": "random",
        }

        blocks_a = _compile(resolver, block_def, programs, seed=99)
        blocks_b = _compile(resolver, block_def, programs, seed=99)

        titles_a = [b.title for b in blocks_a]
        titles_b = [b.title for b in blocks_b]
        assert titles_a == titles_b, "Same seed must produce same program selections"


# ===========================================================================
# grid_blocks_max — greedy packing
# ===========================================================================


def _make_resolver_with_durations(*movies):
    """Build a resolver with movies of specific durations.

    Each movie tuple: (pool_name, asset_id, duration_sec, title)
    """
    resolver = StubAssetResolver()
    pool_assets = {}

    for pool_name, asset_id, duration_sec, title in movies:
        resolver.add(asset_id, AssetMetadata(
            type="movie", duration_sec=duration_sec, title=title,
            rating="PG",
        ))
        pool_assets.setdefault(pool_name, []).append(asset_id)

    # Register pools — each pool's tags will contain its asset IDs
    pool_defs = {}
    for pool_name in pool_assets:
        pool_defs[pool_name] = {"match": {"type": "movie", "rating": {"include": ["PG"]}}}
    resolver.register_pools(pool_defs)
    return resolver


@pytest.mark.contract
class TestGridBlocksMaxGreedyPacking:
    """grid_blocks_max — movies take only the grid blocks they need."""

    # Tier: 2 | Scheduling logic invariant
    def test_short_movie_takes_fewer_blocks(self):
        # 85-min movie (5100s) at 30-min grid → needs 3 blocks (90min),
        # not the max of 5 blocks.
        resolver = _make_resolver_with_durations(
            ("movies_pg", "short-movie", 5100, "Short Movie"),
        )
        programs = {
            "pg_movie": {
                "pool": "movies_pg",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "bleed": True,
            },
        }
        block_def = {
            "start": "10:00",
            "slots": 10,
            "program": "pg_movie",
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        first = blocks[0]
        # 85-min movie → ceil(5100/1800) = 3 grid blocks → 5400s slot
        assert first.slot_duration_sec == 5400, (
            f"85-min movie should get 3 grid blocks (5400s), got {first.slot_duration_sec}s"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_greedy_packing_fits_more_movies(self):
        # With fixed grid_blocks=4 and 8 slots → 2 movies × 4 blocks = 8.
        # With grid_blocks_max=5 and 10 slots → 85-min movies take 3 blocks
        # each. Greedy packing: 3+3+3 = 9 slots, 1 remaining, then
        # a 4th movie bleeds (takes 3 blocks, exceeds budget by 2).
        #
        # Key assertions:
        # - More movies packed than fixed grid_blocks=4 would allow
        # - Each movie gets only the grid blocks it needs (3, not 5)
        resolver = _make_resolver_with_durations(
            ("movies_pg", "short-movie-1", 5100, "Short 1"),
            ("movies_pg", "short-movie-2", 5100, "Short 2"),
            ("movies_pg", "short-movie-3", 5100, "Short 3"),
        )
        programs = {
            "pg_movie": {
                "pool": "movies_pg",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "bleed": True,
            },
        }
        block_def = {
            "start": "10:00",
            "slots": 9,  # exactly 3 movies × 3 blocks
            "program": "pg_movie",
            "progression": "random",
        }

        blocks = _compile(resolver, block_def, programs)
        # Each 85-min movie should get 3 grid blocks (5400s), not 5 (9000s)
        for b in blocks:
            assert b.slot_duration_sec == 5400, (
                f"85-min movie should get 3 grid blocks (5400s), got {b.slot_duration_sec}s"
            )
        assert len(blocks) == 3, f"Should pack exactly 3 movies in 9 slots, got {len(blocks)}"

    # Tier: 2 | Scheduling logic invariant
    def test_slots_not_multiple_accepted_with_grid_blocks_max(self):
        # slots=7 is valid with grid_blocks_max — no modulus check.
        resolver = _make_resolver_with_durations(
            ("movies_pg", "movie-1", 5400, "Movie 1"),
        )
        programs = {
            "pg_movie": {
                "pool": "movies_pg",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "bleed": True,
            },
        }
        block_def = {
            "start": "10:00",
            "slots": 7,
            "program": "pg_movie",
            "progression": "random",
        }

        # Must not raise
        blocks = _compile(resolver, block_def, programs)
        assert len(blocks) >= 1

    # Tier: 2 | Scheduling logic invariant
    def test_grid_blocks_max_uniform_in_program_list(self):
        # INV-SBLOCK-PROGRAM-006 — all programs in list must have
        # the same grid_blocks_max when using dynamic mode.
        resolver = _default_resolver()
        programs = {
            "pg_movie": {
                "pool": "movies_pg",
                "grid_blocks_max": 5,
                "fill_mode": "single",
                "bleed": True,
            },
            "pg13_movie": {
                "pool": "movies_pg13",
                "grid_blocks_max": 4,
                "fill_mode": "single",
                "bleed": True,
            },
        }
        block_def = {
            "start": "10:00",
            "slots": 10,
            "program": ["pg_movie", "pg13_movie"],
            "progression": "random",
        }

        with pytest.raises((AssemblyFault, ValueError)):
            _compile(resolver, block_def, programs)
