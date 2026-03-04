"""
Contract tests for INV-SCHEDULE-SEED-DAY-VARIANCE-001.

Compilation seed MUST incorporate broadcast_day so that different days
produce different movie selections. Same (channel, day) MUST still
produce identical output (deterministic rebuild).

See: docs/contracts/invariants/core/runtime/INV-SCHEDULE-SEED-DAY-VARIANCE-001.md
"""

from __future__ import annotations

import hashlib

from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    compilation_seed,
    parse_dsl,
)


# ---------------------------------------------------------------------------
# Fixture: minimal movie-template DSL (HBO-Classics-like)
# ---------------------------------------------------------------------------

_TEMPLATE_DSL_YAML = """\
channel: test-movies
channel_number: 99
name: "Test Movies"
channel_type: movie
timezone: America/New_York

format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

pools:
  test_pool:
    match:
      type: movie
    max_duration_sec: 10800

templates:
  feature_presentation:
    segments:
      - source:
          type: pool
          name: test_pool
        mode: random

schedule:
  all_day:
    - type: template
      name: feature_presentation
      start: "08:00"
      end: "16:00"
      allow_bleed: true
    - type: template
      name: feature_presentation
      start: "16:00"
      end: "00:00"
      allow_bleed: true
"""


def _make_movie_resolver() -> StubAssetResolver:
    """10 movies — enough for variety testing."""
    r = StubAssetResolver()
    movies = [
        ("asset.movies.film_a", "Film A", 6600),
        ("asset.movies.film_b", "Film B", 6900),
        ("asset.movies.film_c", "Film C", 7200),
        ("asset.movies.film_d", "Film D", 5400),
        ("asset.movies.film_e", "Film E", 7800),
        ("asset.movies.film_f", "Film F", 6300),
        ("asset.movies.film_g", "Film G", 7500),
        ("asset.movies.film_h", "Film H", 5700),
        ("asset.movies.film_i", "Film I", 6000),
        ("asset.movies.film_j", "Film J", 7100),
    ]
    for aid, title, dur in movies:
        r.add(aid, AssetMetadata(type="movie", duration_sec=dur, title=title))
    return r


def _compile_day(broadcast_day: str) -> list[str]:
    """Compile the template DSL for a given day, return ordered asset_id list."""
    dsl = parse_dsl(_TEMPLATE_DSL_YAML)
    dsl["broadcast_day"] = broadcast_day
    resolver = _make_movie_resolver()
    seed = compilation_seed("test-movies", broadcast_day)
    schedule = compile_schedule(dsl, resolver=resolver, seed=seed)
    return [b["asset_id"] for b in schedule["program_blocks"]]


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestInvScheduleSeedDayVariance001:
    """INV-SCHEDULE-SEED-DAY-VARIANCE-001 contract tests."""

    def test_compilation_seed_deterministic(self):
        """Same (channel, day) always returns same seed."""
        s1 = compilation_seed("hbo-classics", "2026-03-01")
        s2 = compilation_seed("hbo-classics", "2026-03-01")
        assert s1 == s2

    def test_compilation_seed_varies_by_day(self):
        """Different broadcast_day → different seed."""
        s1 = compilation_seed("hbo-classics", "2026-03-01")
        s2 = compilation_seed("hbo-classics", "2026-03-02")
        assert s1 != s2

    def test_compilation_seed_varies_by_channel(self):
        """Different channel_id → different seed."""
        s1 = compilation_seed("hbo-classics", "2026-03-01")
        s2 = compilation_seed("showtime-cinema", "2026-03-01")
        assert s1 != s2

    def test_compilation_seed_uses_hashlib(self):
        """Seed matches expected hashlib formula."""
        expected = int(
            hashlib.sha256("hbo-classics:2026-03-01".encode("utf-8")).hexdigest(), 16
        ) % (2**31)
        assert compilation_seed("hbo-classics", "2026-03-01") == expected

    def test_different_days_produce_different_movies(self):
        """Compiling the same channel on two different days MUST produce
        different movie selections."""
        day_a = _compile_day("2026-03-01")
        day_b = _compile_day("2026-03-02")
        assert day_a != day_b, (
            "Same movie selections on different days — seed is not day-varying"
        )

    def test_same_day_produces_identical_movies(self):
        """Compiling the same channel on the same day twice MUST produce
        identical output (deterministic rebuild)."""
        run1 = _compile_day("2026-03-01")
        run2 = _compile_day("2026-03-01")
        assert run1 == run2

    def test_two_windows_same_day_differ(self):
        """Two template windows at different start times on the same day
        MUST produce different movie sequences."""
        dsl = parse_dsl(_TEMPLATE_DSL_YAML)
        dsl["broadcast_day"] = "2026-03-01"
        resolver = _make_movie_resolver()
        seed = compilation_seed("test-movies", "2026-03-01")
        schedule = compile_schedule(dsl, resolver=resolver, seed=seed)

        blocks = schedule["program_blocks"]
        # Split into window 1 (08:00-16:00) and window 2 (16:00-00:00)
        from datetime import datetime, timezone
        cutoff = datetime(2026, 3, 1, 21, 0, tzinfo=timezone.utc)  # ~16:00 ET
        window1 = [b["asset_id"] for b in blocks if datetime.fromisoformat(b["start_at"]) < cutoff]
        window2 = [b["asset_id"] for b in blocks if datetime.fromisoformat(b["start_at"]) >= cutoff]

        if window1 and window2:
            assert window1[0] != window2[0], (
                "First movie in both windows is identical — seed is not window-varying"
            )
