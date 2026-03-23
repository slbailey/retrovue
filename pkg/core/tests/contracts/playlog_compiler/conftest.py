"""Shared fixtures for playlog compiler contract tests.

These tests validate the target compiler model defined in:
  - docs/contracts/block_assembly_tiers.md
  - docs/contracts/channel_dsl.md

All tests in this package are expected to FAIL against the current
implementation. They define the target behavior for the compiler refactor.
"""
from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.config.testing import TEST_RESOLVED_CONFIG


# ---------------------------------------------------------------------------
# Minimal DSL builders
# ---------------------------------------------------------------------------


def make_network_dsl(
    *,
    channel_id: str = "test-network",
    broadcast_day: str = "2026-04-01",
    grid_minutes: int = 30,
    pool_name: str = "cheers",
    program_name: str = "cheers_30",
    slots: int = 2,
    progression: str = "sequential",
    chapter_markers: bool = True,
) -> dict:
    """Build a minimal network channel DSL with a single sitcom program."""
    return {
        "channel": channel_id,
        "channel_type": "network",
        "timezone": "UTC",
        "broadcast_day": broadcast_day,
        "format": {"grid_minutes": grid_minutes},
        "pools": {
            pool_name: {
                "match": {"type": "episode", "series_title": "Cheers"},
            },
        },
        "programs": {
            program_name: {
                "pool": pool_name,
                "grid_blocks": 1,
                "fill_mode": "single",
            },
        },
        "schedule": {
            "all_day": [
                {
                    "start": "06:00",
                    "slots": slots,
                    "program": program_name,
                    "progression": progression,
                },
            ],
        },
    }


def make_network_resolver(*, chapter_markers: bool = True) -> StubAssetResolver:
    """Build a resolver for a network sitcom channel.

    Each episode is 22 minutes (1320 sec) in a 30-min grid slot.
    Chapter markers at 7:00 and 14:00 produce two mid-content breaks.
    """
    r = StubAssetResolver()
    markers = (420.0, 840.0) if chapter_markers else None
    r.add("cheers", AssetMetadata(
        type="pool", duration_sec=0,
        tags=("ep-001", "ep-002", "ep-003", "ep-004"),
    ))
    r.register_pools({
        "cheers": {"match": {"type": "episode", "series_title": "Cheers"}},
    })
    for ep_id in ("ep-001", "ep-002", "ep-003", "ep-004"):
        r.add(ep_id, AssetMetadata(
            type="episode",
            duration_sec=1320,
            title=f"Cheers {ep_id}",
            chapter_markers_sec=markers,
            loudness_gain_db=-2.5,
            file_uri=f"/mnt/episodes/{ep_id}.mkv",
        ))
    return r


def make_movie_dsl(
    *,
    channel_id: str = "test-movie",
    broadcast_day: str = "2026-04-01",
    grid_minutes: int = 30,
) -> dict:
    """Build a minimal premium movie channel DSL."""
    return {
        "channel": channel_id,
        "channel_type": "premium",
        "timezone": "UTC",
        "broadcast_day": broadcast_day,
        "format": {"grid_minutes": grid_minutes},
        "pools": {
            "movies": {
                "match": {"type": "movie"},
            },
        },
        "programs": {
            "hbo_movie": {
                "pool": "movies",
                "grid_blocks_max": 5,
                "fill_mode": "single",
            },
        },
        "schedule": {
            "all_day": [
                {
                    "start": "06:00",
                    "slots": 10,
                    "program": "hbo_movie",
                    "progression": "random",
                    "bleed": True,
                },
            ],
        },
    }


def make_movie_resolver() -> StubAssetResolver:
    """Build a resolver for a premium movie channel."""
    r = StubAssetResolver()
    r.add("movies", AssetMetadata(
        type="pool", duration_sec=0,
        tags=("movie-001", "movie-002"),
    ))
    r.register_pools({
        "movies": {"match": {"type": "movie"}},
    })
    r.add("movie-001", AssetMetadata(
        type="movie",
        duration_sec=6900,  # 115 min
        title="Test Movie Alpha",
        loudness_gain_db=-1.0,
        file_uri="/mnt/movies/alpha.mkv",
    ))
    r.add("movie-002", AssetMetadata(
        type="movie",
        duration_sec=5400,  # 90 min
        title="Test Movie Beta",
        loudness_gain_db=-0.5,
        file_uri="/mnt/movies/beta.mkv",
    ))
    return r
