# tests/contracts/test_inv_template_segments_compiled.py
#
# Contract tests for:
#   INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS
#
# Template-derived schedule blocks must compile into an explicit, ordered
# segment list sufficient for deterministic playout without runtime
# editorial reconstruction.
#
# Coverage:
#   1. Compilation: compiled_segments present in ProgramBlockOutput
#   2. Segment structure: correct order, types, and is_primary flags
#   3. Persistence: compiled_segments survives into ScheduleItem.metadata_
#   4. Runtime hydration: schedule_items_reader uses compiled_segments
#      directly, bypassing expand_program_block heuristic expansion
#   5. Regression: non-template items still use existing expansion path

from __future__ import annotations

import hashlib
import random

import pytest

from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
    CompileError,
)
from retrovue.runtime.asset_resolver import AssetMetadata


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResolver:
    """Minimal AssetResolver for compiler tests."""

    def __init__(self) -> None:
        self._assets: dict[str, AssetMetadata] = {}
        self._pools: dict[str, list[str]] = {}
        self._collections: dict[str, list[str]] = {}

    def add_asset(
        self, asset_id: str, title: str, duration_sec: int,
        *, asset_type: str = "movie", file_uri: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> None:
        self._assets[asset_id] = AssetMetadata(
            type=asset_type,
            duration_sec=duration_sec,
            title=title,
            tags=tags,
            file_uri=file_uri or f"/assets/{asset_id}.mp4",
        )

    def add_pool(self, pool_id: str, asset_ids: list[str]) -> None:
        self._pools[pool_id] = list(asset_ids)
        self._assets[pool_id] = AssetMetadata(
            type="pool", duration_sec=0, title=pool_id,
            tags=tuple(asset_ids),
        )

    def add_collection(self, col_id: str, asset_ids: list[str]) -> None:
        self._collections[col_id] = list(asset_ids)

    def lookup(self, asset_id: str) -> AssetMetadata:
        if asset_id not in self._assets:
            raise KeyError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def query(self, match: dict) -> list[str]:
        collection = match.get("collection")
        if collection and collection in self._collections:
            return list(self._collections[collection])
        return []

    def register_pools(self, pools: dict) -> None:
        for pool_id, pool_def in pools.items():
            if pool_id in self._pools:
                continue
            if pool_id not in self._assets:
                self._assets[pool_id] = AssetMetadata(
                    type="pool", duration_sec=0, title=pool_id, tags=(),
                )


def _make_hbo_resolver() -> _FakeResolver:
    r = _FakeResolver()
    r.add_asset("movie-001", "Weekend at Bernie's", 5400)
    r.add_asset("movie-002", "Caddyshack", 5880)
    r.add_asset("movie-003", "Ghostbusters", 6360)
    r.add_pool("hbo_movies", ["movie-001", "movie-002", "movie-003"])
    r.add_asset("intro-hbo-001", "HBO Intro", 30)
    r.add_collection("Intros", ["intro-hbo-001"])
    return r


HBO_TEMPLATE_YAML = """\
channel: hbo-classics-test
broadcast_day: "2026-03-03"
timezone: UTC

pools:
  hbo_movies:
    match:
      type: movie
    max_duration_sec: 10800

templates:
  hbo_feature_with_intro:
    segments:
      - source:
          type: collection
          name: Intros
        selection:
          - type: tags
            values: [hbo]
        mode: random
      - source:
          type: pool
          name: hbo_movies
        mode: random

schedule:
  all_day:
    - type: template
      name: hbo_feature_with_intro
      start: "06:00"
      end: "14:00"
      allow_bleed: true
"""

LEGACY_MOVIE_YAML = """\
channel: nightmare-theater-test
broadcast_day: "2026-03-03"
timezone: UTC

pools:
  horror_all:
    match:
      type: movie

schedule:
  all_day:
    - movie_marathon:
        start: "06:00"
        end: "18:00"
        title: "Horror Movie Marathon"
        movie_selector:
          pool: horror_all
          mode: random
          max_duration_sec: 9000
        allow_bleed: true
"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. Contract: compiled_segments present in compilation output
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateSegmentsCompiled:
    """INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    Template-derived ProgramBlockOutput must include compiled_segments."""

    def test_compiled_segments_present(self):
        """Template blocks must include compiled_segments in output."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)
        blocks = result["program_blocks"]
        assert len(blocks) > 0

        for pb in blocks:
            assert "compiled_segments" in pb, (
                f"Block {pb.get('title', '?')} missing compiled_segments"
            )

    def test_exactly_two_segments_for_hbo(self):
        """HBO template: each block has exactly 2 compiled segments
        (intro + movie)."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            segs = pb["compiled_segments"]
            assert len(segs) == 2, (
                f"Expected 2 segments, got {len(segs)}: {segs}"
            )

    def test_segment_order_intro_then_movie(self):
        """First segment is intro (collection), second is movie (pool)."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            segs = pb["compiled_segments"]
            assert segs[0]["source_type"] == "collection"
            assert segs[0]["source_name"] == "Intros"
            assert segs[1]["source_type"] == "pool"
            assert segs[1]["source_name"] == "hbo_movies"

    def test_primary_flag(self):
        """Only the movie segment (pool) is marked is_primary=True."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            segs = pb["compiled_segments"]
            assert segs[0]["is_primary"] is False
            assert segs[1]["is_primary"] is True

    def test_all_required_fields_present(self):
        """Each compiled segment has all required fields."""
        required = {
            "segment_type", "asset_id", "asset_uri",
            "asset_start_offset_ms", "segment_duration_ms",
            "source_type", "source_name", "is_primary",
        }
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            for seg in pb["compiled_segments"]:
                missing = required - set(seg.keys())
                assert not missing, f"Segment missing fields: {missing}"

    def test_intro_segment_resolved_to_real_asset(self):
        """Intro segment asset_id and asset_uri are resolved, not empty."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            intro = pb["compiled_segments"][0]
            assert intro["asset_id"] == "intro-hbo-001"
            assert intro["asset_uri"] == "/assets/intro-hbo-001.mp4"
            assert intro["segment_duration_ms"] == 30000

    def test_movie_segment_has_correct_duration(self):
        """Movie segment duration matches the resolved asset."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        known_durations = {"movie-001": 5400, "movie-002": 5880, "movie-003": 6360}
        for pb in result["program_blocks"]:
            movie_seg = pb["compiled_segments"][1]
            expected_ms = known_durations[movie_seg["asset_id"]] * 1000
            assert movie_seg["segment_duration_ms"] == expected_ms

    def test_slot_duration_accounts_for_all_segments(self):
        """Slot duration must cover ALL template segments, not just the
        primary movie. A 90-min movie + 30s intro needs > 5400s slot."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        known_durations = {"movie-001": 5400, "movie-002": 5880, "movie-003": 6360}
        intro_duration = 30  # intro-hbo-001 is 30s

        for pb in result["program_blocks"]:
            movie_seg = pb["compiled_segments"][1]
            movie_dur = known_durations[movie_seg["asset_id"]]
            total_content = movie_dur + intro_duration
            slot_dur = pb["slot_duration_sec"]
            assert slot_dur >= total_content, (
                f"Slot {slot_dur}s < total content {total_content}s "
                f"(movie={movie_dur}s + intro={intro_duration}s) — "
                f"slot must cover all template segments"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Contract: persistence into ScheduleItem.metadata_
# ─────────────────────────────────────────────────────────────────────────────

class TestCompiledSegmentsPersistence:
    """INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    compiled_segments must survive serialization round-trip through
    ScheduleItem.metadata_ dict construction."""

    def test_metadata_dict_includes_compiled_segments(self):
        """The metadata_ dict built by schedule_revision_writer must include
        compiled_segments when present in the compiler output."""
        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        # Simulate what schedule_revision_writer does
        for block in result["program_blocks"]:
            metadata = {
                "title": block.get("title"),
                "asset_id_raw": block.get("asset_id"),
                "collection_raw": block.get("collection"),
                "selector": block.get("selector"),
                "episode_duration_sec": block.get("episode_duration_sec"),
                "template_id": block.get("template_id"),
                "epg_title": block.get("epg_title"),
                "compiled_segments": block.get("compiled_segments"),
            }
            assert metadata["compiled_segments"] is not None
            assert len(metadata["compiled_segments"]) == 2

    def test_content_type_inferred_as_movie_for_template(self):
        """Template blocks with a movie pool primary segment must infer
        content_type as 'movie', not rely on title heuristics."""
        from retrovue.runtime.schedule_revision_writer import _infer_content_type

        resolver = _make_hbo_resolver()
        dsl = parse_dsl(HBO_TEMPLATE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for block in result["program_blocks"]:
            ct = _infer_content_type(block)
            assert ct == "movie", (
                f"Expected content_type='movie' for template block "
                f"'{block.get('title')}', got '{ct}'"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Contract: runtime hydration honors compiled segments
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeHydration:
    """INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS:
    schedule_items_reader must use compiled_segments directly for
    template blocks, bypassing expand_program_block."""

    def test_hydrate_from_compiled_segments(self):
        """Given compiled_segments in metadata_, the reader must produce
        a ScheduledBlock with matching segment structure."""
        from retrovue.runtime.schedule_items_reader import (
            _hydrate_compiled_segments,
        )
        from retrovue.runtime.schedule_types import ScheduledBlock

        compiled = [
            {
                "segment_type": "intro",
                "asset_id": "intro-hbo-001",
                "asset_uri": "/assets/intro-hbo-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 30000,
                "source_type": "collection",
                "source_name": "Intros",
                "is_primary": False,
                "gain_db": 0.0,
            },
            {
                "segment_type": "content",
                "asset_id": "movie-001",
                "asset_uri": "/assets/movie-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 5400000,
                "source_type": "pool",
                "source_name": "hbo_movies",
                "is_primary": True,
                "gain_db": 0.0,
            },
        ]

        start_ms = 1709452800000
        slot_ms = 5400000 + 600000  # movie + grid padding
        block = _hydrate_compiled_segments(
            compiled_segments=compiled,
            asset_id="movie-001",
            start_utc_ms=start_ms,
            slot_duration_ms=slot_ms,
        )

        assert isinstance(block, ScheduledBlock)
        # Template segments + optional post-content filler
        content_segs = [s for s in block.segments if s.segment_type != "filler"]
        assert len(content_segs) == 2
        assert content_segs[0].segment_type == "intro"
        assert content_segs[0].asset_uri == "/assets/intro-hbo-001.mp4"
        assert content_segs[1].segment_type == "content"
        assert content_segs[1].asset_uri == "/assets/movie-001.mp4"

    def test_hydrated_block_has_post_content_filler(self):
        """When slot is longer than template content, filler segment
        is appended for slot completion."""
        from retrovue.runtime.schedule_items_reader import (
            _hydrate_compiled_segments,
        )

        compiled = [
            {
                "segment_type": "intro",
                "asset_id": "intro-hbo-001",
                "asset_uri": "/assets/intro-hbo-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 30000,
                "source_type": "collection",
                "source_name": "Intros",
                "is_primary": False,
                "gain_db": 0.0,
            },
            {
                "segment_type": "content",
                "asset_id": "movie-001",
                "asset_uri": "/assets/movie-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 5400000,
                "source_type": "pool",
                "source_name": "hbo_movies",
                "is_primary": True,
                "gain_db": 0.0,
            },
        ]

        start_ms = 1709452800000
        content_total_ms = 30000 + 5400000  # intro + movie
        slot_ms = 7200000  # 2 hours
        remaining = slot_ms - content_total_ms

        block = _hydrate_compiled_segments(
            compiled_segments=compiled,
            asset_id="movie-001",
            start_utc_ms=start_ms,
            slot_duration_ms=slot_ms,
        )

        filler_segs = [s for s in block.segments if s.segment_type == "filler"]
        assert len(filler_segs) == 1
        assert filler_segs[0].segment_duration_ms == remaining


# ─────────────────────────────────────────────────────────────────────────────
# 4. Regression: legacy non-template blocks unchanged
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyExpansionRegression:
    """Non-template blocks must not include compiled_segments and
    must continue using expand_program_block heuristic expansion."""

    def test_legacy_blocks_have_no_compiled_segments(self):
        resolver = _make_hbo_resolver()
        resolver.add_pool("horror_all", ["movie-001", "movie-002", "movie-003"])

        dsl = parse_dsl(LEGACY_MOVIE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            assert "compiled_segments" not in pb or pb["compiled_segments"] is None, (
                "Legacy block should not have compiled_segments"
            )

    def test_legacy_content_type_unchanged(self):
        """Legacy movie blocks still infer content_type from selector/title."""
        from retrovue.runtime.schedule_revision_writer import _infer_content_type

        # A legacy block with movie_selector
        block = {
            "title": "Weekend at Bernie's",
            "selector": {"max_duration_sec": 9000, "collections": ["horror_all"]},
        }
        assert _infer_content_type(block) == "movie"

        # A legacy block with "movie" in title
        block2 = {"title": "Horror Movie Marathon"}
        assert _infer_content_type(block2) == "movie"

        # A plain episode with no template
        block3 = {"title": "Tales from the Crypt S01E03"}
        assert _infer_content_type(block3) == "episode"
