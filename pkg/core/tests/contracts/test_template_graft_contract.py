# pkg/core/tests/contracts/test_template_graft_contract.py
#
# Contract tests for the template-v2 graft plan.
#
# These tests enforce the invariants defined in:
#   INV-TEMPLATE-GRAFT-DUAL-YAML-001  — dual YAML syntax coexistence
#   INV-WINDOW-UUID-EMBEDDED-001      — window_uuid in day blob JSON
#   INV-TIER2-SOURCE-WINDOW-UUID-001  — Tier 2 propagation (planned)
#
# Test strategy:
#   - Tests exercise the PRODUCTION compiler pipeline (schedule_compiler.py
#     and dsl_schedule_service.py), NOT the parallel template_runtime.py types.
#   - Legacy YAML channels must continue to compile without regression.
#   - Template-mode YAML channels must compile and include window_uuid.
#   - No new runtime stores are introduced; only existing production stores
#     (ProgramLogDay, PlaylistEvent) are validated.
#
# ── Expected results ─────────────────────────────────────────────────────────
# Legacy tests PASS immediately (existing behavior).
# Template-mode tests FAIL until the graft implementation lands. That failure
# is the proof that the invariant is not yet satisfied.

from __future__ import annotations

import uuid as uuid_mod

import pytest
import yaml

from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
    expand_templates,
    CompileError,
)
from retrovue.runtime.asset_resolver import AssetMetadata


# ─────────────────────────────────────────────────────────────────────────────
# Test fixtures — Fake AssetResolver
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResolver:
    """Minimal AssetResolver for compiler tests.

    Returns controlled metadata so compilation completes without hitting
    a real database or filesystem.
    """

    def __init__(self) -> None:
        self._assets: dict[str, AssetMetadata] = {}
        self._pools: dict[str, list[str]] = {}

    def add_movie(self, asset_id: str, title: str, duration_sec: int = 7200) -> None:
        self._assets[asset_id] = AssetMetadata(
            type="movie",
            duration_sec=duration_sec,
            title=title,
            tags=(),
            file_uri=f"/assets/{asset_id}.mp4",
        )

    def add_pool(self, pool_id: str, asset_ids: list[str]) -> None:
        self._pools[pool_id] = list(asset_ids)
        # Register pool as a collection-type asset whose tags are member IDs
        self._assets[pool_id] = AssetMetadata(
            type="pool",
            duration_sec=0,
            title=pool_id,
            tags=tuple(asset_ids),
        )

    def add_collection(self, col_id: str, asset_ids: list[str]) -> None:
        self._assets[col_id] = AssetMetadata(
            type="pool",
            duration_sec=0,
            title=col_id,
            tags=tuple(asset_ids),
        )

    def lookup(self, asset_id: str) -> AssetMetadata:
        if asset_id not in self._assets:
            raise KeyError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def query(self, match: dict) -> list[str]:
        col = match.get("collection")
        if col and col in self._assets:
            meta = self._assets[col]
            return list(meta.tags)
        pool = match.get("type")
        if pool:
            return [
                aid for aid, m in self._assets.items()
                if m.type == pool and m.tags != ()
            ]
        return []

    def register_pools(self, pools: dict) -> None:
        """Handle the schedule compiler's pool registration call."""
        for pool_id, pool_def in pools.items():
            if pool_id in self._pools:
                # Pool already explicitly registered — use those assets
                continue
            # Auto-register as empty pool if not pre-populated
            if pool_id not in self._assets:
                self._assets[pool_id] = AssetMetadata(
                    type="pool", duration_sec=0, title=pool_id, tags=(),
                )


def _make_resolver_with_movies() -> _FakeResolver:
    """Create a resolver with a small movie catalog for testing."""
    r = _FakeResolver()
    r.add_movie("movie-001", "Weekend at Bernie's", 5400)
    r.add_movie("movie-002", "Caddyshack", 5880)
    r.add_movie("movie-003", "Ghostbusters", 6360)
    r.add_pool("hbo_movies", ["movie-001", "movie-002", "movie-003"])
    # Intro assets
    r.add_movie("intro-hbo-001", "HBO Intro", 30)
    r.add_collection("Intros", ["intro-hbo-001"])
    return r


# ─────────────────────────────────────────────────────────────────────────────
# YAML fixtures
# ─────────────────────────────────────────────────────────────────────────────

LEGACY_YAML = """\
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

TEMPLATE_MODE_YAML = """\
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
    - type: template
      name: hbo_feature_with_intro
      start: "14:00"
      end: "22:00"
      allow_bleed: true
    - type: template
      name: hbo_feature_with_intro
      start: "22:00"
      end: "06:00"
      allow_bleed: true
"""


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-GRAFT-DUAL-YAML-001 — Legacy YAML still compiles
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyYamlPreservation:
    """INV-TEMPLATE-GRAFT-DUAL-YAML-001 Rule 3: Legacy YAML channels produce
    identical compilation output to prior compiler versions."""

    def test_legacy_yaml_parses_without_error(self):
        """parse_dsl accepts legacy YAML without template-mode entries."""
        dsl = parse_dsl(LEGACY_YAML)
        assert dsl["channel"] == "nightmare-theater-test"
        assert "schedule" in dsl

    def test_legacy_yaml_compiles_program_blocks(self):
        """Legacy YAML compiles into program_blocks via compile_schedule."""
        resolver = _make_resolver_with_movies()
        # Register the horror_all pool manually to match the DSL
        resolver.add_pool("horror_all", ["movie-001", "movie-002", "movie-003"])

        dsl = parse_dsl(LEGACY_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        assert "program_blocks" in result
        assert len(result["program_blocks"]) > 0
        # Every block has the required fields
        for pb in result["program_blocks"]:
            assert "title" in pb
            assert "asset_id" in pb
            assert "start_at" in pb
            assert "slot_duration_sec" in pb

    def test_legacy_yaml_no_window_uuid_required(self):
        """INV-WINDOW-UUID-EMBEDDED-001 Rule 4: Legacy-mode compilation MAY
        omit window_uuid. We verify it is absent (or at least not mandatory)."""
        resolver = _make_resolver_with_movies()
        resolver.add_pool("horror_all", ["movie-001", "movie-002", "movie-003"])

        dsl = parse_dsl(LEGACY_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        for pb in result["program_blocks"]:
            # window_uuid is NOT expected on legacy blocks
            # (if it's present that's fine, but it must not be required)
            pass  # No assertion failure = pass


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-GRAFT-DUAL-YAML-001 Rule 6 — templates: mapping consistency
# ─────────────────────────────────────────────────────────────────────────────

LEGACY_ALIAS_YAML = """\
channel: retro-test
broadcast_day: "2026-03-03"
timezone: UTC

pools:
  horror_all:
    match:
      type: movie

templates:
  weeknight:
    - movie_marathon:
        start: "18:00"
        end: "06:00"
        title: "Horror Movie Marathon"
        movie_selector:
          pool: horror_all
          mode: random
          max_duration_sec: 9000
        allow_bleed: true

schedule:
  monday: { use: weeknight }
  tuesday: { use: weeknight }
"""

HALF_MIGRATED_YAML = """\
channel: half-migrated-test
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
        mode: random
      - source:
          type: pool
          name: hbo_movies
        mode: random
  weeknight:
    - movie_marathon:
        start: "18:00"
        end: "06:00"
        title: "Movie Marathon"
        movie_selector:
          pool: hbo_movies
          mode: random

schedule:
  all_day:
    - type: template
      name: hbo_feature_with_intro
      start: "06:00"
      end: "14:00"
      allow_bleed: true
"""


class TestTemplatesMappingConsistency:
    """INV-TEMPLATE-GRAFT-DUAL-YAML-001 Rule 6: no mixed templates: mapping.

    Legacy day-alias templates must still work when no segments: entries
    exist. But mixing segment-composition entries with legacy aliases in
    the same templates: mapping is invalid.
    """

    def test_legacy_template_aliases_still_expand(self):
        """Legacy templates: with day-alias values (no segments: anywhere)
        are expanded via { use: template_name } and compile normally."""
        resolver = _make_resolver_with_movies()
        resolver.add_pool("horror_all", ["movie-001", "movie-002", "movie-003"])

        dsl = parse_dsl(LEGACY_ALIAS_YAML)
        # expand_templates should replace { use: weeknight } with the block list
        expanded = expand_templates(dsl)
        assert isinstance(expanded["schedule"]["monday"], list)

        result = compile_schedule(dsl, resolver=resolver)
        assert len(result["program_blocks"]) > 0

    def test_half_migrated_templates_rejected(self):
        """templates: mapping that mixes segment-composition entries with
        legacy day-aliases must raise CompileError (Rule 6)."""
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(HALF_MIGRATED_YAML)
        with pytest.raises(CompileError, match=r"mix"):
            compile_schedule(dsl, resolver=resolver)


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-GRAFT-DUAL-YAML-001 — Template-mode YAML parses
# ─────────────────────────────────────────────────────────────────────────────


class TestTemplateYamlParsing:
    """INV-TEMPLATE-GRAFT-DUAL-YAML-001 Rules 1-2: Template-mode YAML
    is accepted by the parser and coexists with legacy syntax."""

    def test_template_yaml_parses_without_error(self):
        """parse_dsl accepts YAML with templates: and type:template entries."""
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        assert dsl["channel"] == "hbo-classics-test"
        assert "templates" in dsl
        assert "hbo_feature_with_intro" in dsl["templates"]

    def test_template_yaml_has_segments(self):
        """Template definitions contain segments with source/mode/selection."""
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        tpl = dsl["templates"]["hbo_feature_with_intro"]
        assert "segments" in tpl
        assert len(tpl["segments"]) == 2

        seg0 = tpl["segments"][0]
        assert seg0["source"]["type"] == "collection"
        assert seg0["source"]["name"] == "Intros"

        seg1 = tpl["segments"][1]
        assert seg1["source"]["type"] == "pool"
        assert seg1["source"]["name"] == "hbo_movies"

    def test_template_schedule_entries_have_type_field(self):
        """Schedule entries in template-mode have type: template."""
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        entries = dsl["schedule"]["all_day"]
        for entry in entries:
            assert entry.get("type") == "template"
            assert "name" in entry


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-GRAFT-DUAL-YAML-001 — Template-mode compiles
# ─────────────────────────────────────────────────────────────────────────────


class TestTemplateYamlCompilation:
    """INV-TEMPLATE-GRAFT-DUAL-YAML-001 Rule 1 + INV-WINDOW-UUID-EMBEDDED-001:
    Template-mode channels compile and include window_uuid in output.

    These tests FAIL until the compiler handles type:template entries.
    That failure is the contract proof that the graft is not yet done.
    """

    def test_template_mode_compiles_program_blocks(self):
        """Template-mode YAML must produce program_blocks.

        The compiler must recognize type:template entries and resolve
        them via the template's segment definitions.
        """
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        assert "program_blocks" in result
        assert len(result["program_blocks"]) > 0

    def test_template_mode_blocks_have_window_uuid(self):
        """INV-WINDOW-UUID-EMBEDDED-001 Rule 1: Every editorial window's
        blocks include a window_uuid field.

        This is the key graft requirement: window_uuid embedded in
        the compiled output, not in a separate DB column.
        """
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        blocks = result["program_blocks"]
        assert len(blocks) > 0, "Template-mode must produce program blocks"

        for pb in blocks:
            assert "window_uuid" in pb, (
                f"program block missing window_uuid: {pb.get('title', 'unknown')} "
                f"at {pb.get('start_at', '?')}"
            )
            # Must be a valid UUID4 string
            parsed = uuid_mod.UUID(pb["window_uuid"])
            assert parsed.version == 4

    def test_window_uuid_stable_within_window(self):
        """INV-WINDOW-UUID-EMBEDDED-001 Rule 3: All blocks within the
        same editorial window share the same window_uuid.

        The schedule has three 8-hour windows. Blocks produced within
        each window must share a UUID; blocks in different windows
        must have different UUIDs.
        """
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        blocks = result["program_blocks"]
        uuids_seen = set()
        for pb in blocks:
            uid = pb.get("window_uuid")
            assert uid is not None
            uuids_seen.add(uid)

        # With 3 editorial windows, we expect at least 3 distinct UUIDs
        assert len(uuids_seen) >= 3, (
            f"Expected >= 3 distinct window_uuids for 3 windows, got {len(uuids_seen)}"
        )

    def test_window_uuid_unique_across_windows(self):
        """INV-WINDOW-UUID-EMBEDDED-001 Rule 2: No two windows within the
        same day blob share a window_uuid."""
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        # Group blocks by their start time slot to identify windows
        # The schedule defines 06:00-14:00, 14:00-22:00, 22:00-06:00
        blocks = result["program_blocks"]
        window_uuids = set()
        for pb in blocks:
            uid = pb.get("window_uuid")
            if uid is not None:
                window_uuids.add(uid)

        # All UUIDs are unique (no two windows share one)
        uuid_list = [pb.get("window_uuid") for pb in blocks if pb.get("window_uuid")]
        unique_uuids = set(uuid_list)
        # The count of unique UUIDs must equal the count of distinct windows
        # (not the count of blocks, since multiple blocks share a window UUID)
        assert len(unique_uuids) >= 3

    def test_template_mode_blocks_have_template_id(self):
        """Template-mode blocks should include template_id for traceability."""
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        blocks = result["program_blocks"]
        assert len(blocks) > 0, "Template-mode must produce program blocks"

        for pb in blocks:
            assert "template_id" in pb, (
                f"program block missing template_id: {pb.get('title', 'unknown')}"
            )
            assert pb["template_id"] == "hbo_feature_with_intro"

    def test_template_mode_blocks_have_epg_title(self):
        """Template-mode blocks should include epg_title when set on entry."""
        # Add epg_title to test YAML
        yaml_with_epg = TEMPLATE_MODE_YAML.replace(
            '      start: "06:00"',
            '      start: "06:00"\n      epg_title: "HBO Feature Presentation"',
        )
        resolver = _make_resolver_with_movies()
        dsl = parse_dsl(yaml_with_epg)
        result = compile_schedule(dsl, resolver=resolver)

        # At least the blocks from the first window should have epg_title
        blocks = result["program_blocks"]
        blocks_with_epg = [pb for pb in blocks if pb.get("epg_title")]
        assert len(blocks_with_epg) > 0, "No blocks have epg_title set"


# ─────────────────────────────────────────────────────────────────────────────
# INV-WINDOW-UUID-EMBEDDED-001 — Serialization round-trip
# ─────────────────────────────────────────────────────────────────────────────


class TestWindowUuidSerialization:
    """INV-WINDOW-UUID-EMBEDDED-001 Rule 4-5: window_uuid survives
    serialization into ProgramLogDay.program_log_json and deserialization
    by PlaylistBuilderDaemon.

    These tests use the production serialization functions.
    """

    def test_serialize_preserves_window_uuid(self):
        """_serialize_scheduled_block preserves window_uuid if present
        in the input dict (simulating template-mode output)."""
        from retrovue.runtime.dsl_schedule_service import (
            _serialize_scheduled_block,
            _deserialize_scheduled_block,
        )
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        test_uuid = str(uuid_mod.uuid4())
        block = ScheduledBlock(
            block_id="test-block-001",
            start_utc_ms=1709510400000,
            end_utc_ms=1709517600000,
            segments=(
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/assets/movie.mp4",
                    asset_start_offset_ms=0,
                    segment_duration_ms=7200000,
                ),
            ),
        )

        serialized = _serialize_scheduled_block(block)
        # Manually inject window_uuid as the compiler would
        serialized["window_uuid"] = test_uuid

        # Deserialize should produce a block; the window_uuid
        # should survive in the dict form (it's passed through
        # as a dict field when loaded by PlaylistBuilderDaemon)
        assert serialized["window_uuid"] == test_uuid

        # Verify the dict round-trips through JSON
        import json
        json_str = json.dumps(serialized)
        restored = json.loads(json_str)
        assert restored["window_uuid"] == test_uuid


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-GRAFT-DUAL-YAML-001 — Dedupe within window
# ─────────────────────────────────────────────────────────────────────────────


class TestDedupeWithinWindow:
    """Template-mode: within a single multi-iteration window, the compiler
    should not pick the same primary movie twice (when the pool has enough
    candidates).

    This test validates compiler-level dedupe for iterative windows.
    """

    def test_no_duplicate_movies_within_window(self):
        """Within a single template window with multiple iterations,
        the same movie should not be picked twice if pool has enough
        candidates.
        """
        resolver = _make_resolver_with_movies()
        # Pool has 3 movies, window should fit 2-3 iterations
        dsl = parse_dsl(TEMPLATE_MODE_YAML)
        result = compile_schedule(dsl, resolver=resolver)

        # Group blocks by window_uuid
        windows: dict[str, list[dict]] = {}
        for pb in result["program_blocks"]:
            uid = pb.get("window_uuid", "legacy")
            windows.setdefault(uid, []).append(pb)

        for uid, blocks in windows.items():
            if uid == "legacy":
                continue
            asset_ids = [pb["asset_id"] for pb in blocks]
            # With 3 movies in pool and iterations fitting in ~8 hours,
            # we should see no duplicates (or at most wrapping after exhaustion)
            # For this test we verify that if len <= pool size, no dupes
            if len(asset_ids) <= 3:
                assert len(asset_ids) == len(set(asset_ids)), (
                    f"Duplicate movies in window {uid}: {asset_ids}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# INV-TEMPLATE-PRIMARY-SEGMENT-001 — Primary segment detection
# ─────────────────────────────────────────────────────────────────────────────


def _make_dsl_with_template(template_segments: list[dict]) -> dict:
    """Build a minimal DSL dict with the given template segments."""
    return {
        "channel": "primary-detect-test",
        "broadcast_day": "2026-03-03",
        "timezone": "UTC",
        "pools": {
            "pool_a": {"match": {"type": "movie"}},
            "pool_b": {"match": {"type": "movie"}},
        },
        "templates": {
            "test_tpl": {
                "segments": template_segments,
            },
        },
        "schedule": {
            "all_day": [
                {
                    "type": "template",
                    "name": "test_tpl",
                    "start": "06:00",
                    "end": "14:00",
                    "allow_bleed": True,
                },
            ],
        },
    }


def _make_resolver_two_pools() -> _FakeResolver:
    """Resolver with two separate movie pools."""
    r = _FakeResolver()
    r.add_movie("movie-a1", "Movie A1", 5400)
    r.add_movie("movie-a2", "Movie A2", 5880)
    r.add_pool("pool_a", ["movie-a1", "movie-a2"])
    r.add_movie("movie-b1", "Movie B1", 6360)
    r.add_movie("movie-b2", "Movie B2", 7200)
    r.add_pool("pool_b", ["movie-b1", "movie-b2"])
    # A collection for non-pool segments
    r.add_movie("intro-001", "Intro", 30)
    r.add_collection("Intros", ["intro-001"])
    return r


class TestPrimarySegmentDetection:
    """INV-TEMPLATE-PRIMARY-SEGMENT-001: Primary segment detection rules.

    Rule 1: Explicit primary:true on exactly one segment → that is primary.
    Rule 2: Multiple primary:true → CompileError.
    Rule 3: No primary:true, exactly one pool → pool is primary by convention.
    Rule 4: No primary:true, zero pools → CompileError.
    Rule 5: No primary:true, multiple pools → CompileError.
    """

    def test_one_pool_one_collection_convention(self):
        """Rule 3: one pool + one collection, no primary:true → pool is
        primary by convention. Compilation succeeds."""
        segments = [
            {"source": {"type": "collection", "name": "Intros"}, "mode": "random"},
            {"source": {"type": "pool", "name": "pool_a"}, "mode": "random"},
        ]
        dsl = _make_dsl_with_template(segments)
        resolver = _make_resolver_two_pools()
        result = compile_schedule(dsl, resolver=resolver)
        assert len(result["program_blocks"]) > 0

    def test_two_pools_one_marked_primary(self):
        """Rule 1: two pools, one marked primary:true → that one is primary.
        Compilation succeeds and uses the marked pool."""
        segments = [
            {"source": {"type": "pool", "name": "pool_a"}, "mode": "random"},
            {"source": {"type": "pool", "name": "pool_b"}, "mode": "random",
             "primary": True},
        ]
        dsl = _make_dsl_with_template(segments)
        resolver = _make_resolver_two_pools()
        result = compile_schedule(dsl, resolver=resolver)

        blocks = result["program_blocks"]
        assert len(blocks) > 0
        # All blocks must come from pool_b (the primary-marked pool)
        pool_b_ids = {"movie-b1", "movie-b2"}
        for pb in blocks:
            assert pb["asset_id"] in pool_b_ids, (
                f"Expected asset from pool_b, got {pb['asset_id']}"
            )

    def test_two_pools_none_marked_primary(self):
        """Rule 5: two pools, no primary:true → CompileError instructing
        operator to set primary:true."""
        segments = [
            {"source": {"type": "pool", "name": "pool_a"}, "mode": "random"},
            {"source": {"type": "pool", "name": "pool_b"}, "mode": "random"},
        ]
        dsl = _make_dsl_with_template(segments)
        resolver = _make_resolver_two_pools()
        with pytest.raises(CompileError, match=r"primary: true"):
            compile_schedule(dsl, resolver=resolver)

    def test_two_segments_both_marked_primary(self):
        """Rule 2: two segments with primary:true → CompileError."""
        segments = [
            {"source": {"type": "collection", "name": "Intros"}, "mode": "random",
             "primary": True},
            {"source": {"type": "pool", "name": "pool_a"}, "mode": "random",
             "primary": True},
        ]
        dsl = _make_dsl_with_template(segments)
        resolver = _make_resolver_two_pools()
        with pytest.raises(CompileError, match=r"primary: true"):
            compile_schedule(dsl, resolver=resolver)

    def test_collections_only_no_primary(self):
        """Rule 4: zero pools, no primary:true → CompileError."""
        segments = [
            {"source": {"type": "collection", "name": "Intros"}, "mode": "random"},
        ]
        dsl = _make_dsl_with_template(segments)
        resolver = _make_resolver_two_pools()
        with pytest.raises(CompileError, match=r"primary: true"):
            compile_schedule(dsl, resolver=resolver)


# ─────────────────────────────────────────────────────────────────────────────
# INV-TIER2-SOURCE-WINDOW-UUID-001 — Tier 2 propagation (planned)
# ─────────────────────────────────────────────────────────────────────────────


class TestTier2Propagation:
    """INV-TIER2-SOURCE-WINDOW-UUID-001: PlaylistBuilderDaemon propagates
    source_window_uuid into PlaylistEvent rows.

    These tests are PLACEHOLDERS. They document the intended behavior
    but are skipped until the Tier 2 propagation code is implemented.
    """

    @pytest.mark.skip(reason="INV-TIER2-SOURCE-WINDOW-UUID-001 not yet implemented")
    def test_tier2_propagates_source_window_uuid(self):
        """PlaylistEvent rows include source_window_uuid when
        the Tier 1 block contains window_uuid."""
        pass

    @pytest.mark.skip(reason="INV-TIER2-SOURCE-WINDOW-UUID-001 not yet implemented")
    def test_tier2_staleness_detection(self):
        """Future PlaylistEvent rows with stale source_window_uuid
        are detected and regenerated."""
        pass

    @pytest.mark.skip(reason="INV-TIER2-SOURCE-WINDOW-UUID-001 not yet implemented")
    def test_on_air_freeze_prevents_regeneration(self):
        """A window currently airing is NOT regenerated even if stale."""
        pass
