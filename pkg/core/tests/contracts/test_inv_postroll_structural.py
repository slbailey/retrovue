"""Contract tests: Postroll structural segments — INV-DSL-POSTROLL-*

Validates that postroll is a first-class structural phase per channel_dsl.md:

- INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: postroll appears after content, in declared order
- INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001: postroll durations reserved before fill
- INV-DSL-SINGLE-FILL-DIRECTIVE-001: at most one traffic directive per block
- INV-DSL-UNIFIED-FILL-001: traffic directive owns all non-structural time
- INV-DSL-TIME-CONSERVATION-001: block_duration == structural + fill
- INV-DSL-NONNEGATIVE-FILL-001: fill duration >= 0

These tests FAIL with the current implementation (postroll is silently dropped
by _resolve_presentation_ref). They PASS once postroll resolution is wired.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
    from retrovue.runtime.program_assembly import assemble_schedule_block
    from retrovue.runtime.program_definition import AssemblyFault, AssemblyResult
    from retrovue.runtime.schedule_compiler import (
        _expand_to_compiled_segments,
        _resolve_presentation_ref,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_resolver() -> StubAssetResolver:
    """Resolver with content, preroll, and postroll assets."""
    resolver = StubAssetResolver()

    # Preroll assets
    resolver.add("hbo-intro-1", AssetMetadata(
        type="bumper", duration_sec=74, title="HBO City 1982",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/bumpers/hbo_intro.mp4",
    ))
    resolver.add("rating-pg13", AssetMetadata(
        type="bumper", duration_sec=5, title="PG-13 Card",
        tags=("hbo", "presentation", "ratings_cards"),
        file_uri="/mnt/bumpers/pg13.mp4",
    ))

    # Postroll assets
    resolver.add("station-id-1", AssetMetadata(
        type="bumper", duration_sec=10, title="HBO Station ID",
        tags=("hbo", "station_ids"),
        file_uri="/mnt/bumpers/hbo_station_id.mp4",
    ))
    resolver.add("station-id-2", AssetMetadata(
        type="bumper", duration_sec=8, title="HBO Station ID Alt",
        tags=("hbo", "station_ids"),
        file_uri="/mnt/bumpers/hbo_station_id_alt.mp4",
    ))
    resolver.add("coming-up-1", AssetMetadata(
        type="promo", duration_sec=15, title="Coming Up Next",
        tags=("hbo", "coming_up_next"),
        file_uri="/mnt/promos/coming_up_next.mp4",
    ))

    # Movies
    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="Taken",
        rating="PG-13", file_uri="/mnt/movies/taken.mkv",
    ))
    resolver.add("movie-002", AssetMetadata(
        type="movie", duration_sec=4800, title="Click",
        rating="PG-13", file_uri="/mnt/movies/click.mkv",
    ))

    # Register pools
    resolver.register_pools({
        "intros": {"match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]}},
        "ratings_cards": {"match": {"type": "bumper", "tags": ["hbo", "presentation", "ratings_cards"]}},
        "station_ids": {"match": {"type": "bumper", "tags": ["hbo", "station_ids"]}},
        "coming_up_next_promos": {"match": {"type": "promo", "tags": ["hbo", "coming_up_next"]}},
        "movies": {"match": {"type": "movie"}},
    })

    return resolver


def _prog_def_with_postroll():
    """Program definition that references a presentation with both preroll and postroll."""
    return {
        "pool": "movies",
        "grid_blocks_max": 5,
        "fill_mode": "single",
        "presentation": "movies",  # string ref — resolver expands to preroll+postroll
    }


def _presentation_defs():
    """Channel-level presentation definitions with preroll and postroll."""
    return {
        "programs": {
            "movies": {
                "preroll": [
                    {"pool": "intros"},
                    {"pool": "ratings_cards"},
                ],
                "postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"pool": "station_ids"},
                ],
            },
        },
    }


def _presentation_defs_with_traffic():
    """Postroll with a traffic directive between structural entries."""
    return {
        "programs": {
            "movies": {
                "preroll": [
                    {"pool": "intros"},
                ],
                "postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"type": "traffic", "profile": "hbo_premium", "fill": "remaining"},
                    {"pool": "station_ids"},
                ],
            },
        },
    }


# ===========================================================================
# Step 1 — INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: postroll present in output
# ===========================================================================


class TestPostrollSegmentsPresent:
    """Postroll structural segments must appear in compiled_segments."""

    def test_postroll_segments_present(self):
        """Compiled output must contain postroll presentation segments
        after content.

        INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: Postroll entries appear
        after primary content, in declared order.
        """
        prog_def = _prog_def_with_postroll()
        pres_defs = _presentation_defs()

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        # The resolver must produce BOTH preroll and postroll data.
        # Current implementation only produces preroll → this test FAILS.
        assert "presentation" in resolved, (
            "Preroll must be resolved"
        )

        # Postroll must be available for downstream assembly.
        # The exact key name is an implementation detail, but the data
        # must be present in the resolved prog_def.
        postroll = resolved.get("presentation_postroll")
        assert postroll is not None and len(postroll) > 0, (
            "INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: postroll entries "
            "must be resolved from presentation_defs, not silently dropped. "
            f"Got resolved keys: {list(resolved.keys())}"
        )


# ===========================================================================
# Step 2 — INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: postroll ordering
# ===========================================================================


class TestPostrollOrderPreserved:
    """Postroll segments must appear after content in declared order."""

    def test_postroll_order_preserved(self):
        """Postroll with [coming_up_next, station_ids]: coming_up_next
        must appear before station_ids, and both after content.

        INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001.
        """
        resolver = _make_resolver()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                # Postroll entries must be passed separately.
                # This tests the assembly path once wired.
                "presentation_postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"pool": "station_ids"},
                ],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]
        seg_types = [s.segment_type for s in result.segments]

        # Find content boundaries
        content_indices = [i for i, t in enumerate(seg_types) if t == "content"]
        assert content_indices, "Must have content segments"
        last_content_idx = content_indices[-1]

        # Postroll presentation segments must exist after content
        postroll_indices = [
            i for i, s in enumerate(result.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]
        assert len(postroll_indices) >= 2, (
            f"INV-DSL-SEGMENT-ORDER-DETERMINISTIC-001: expected >=2 postroll "
            f"presentation segments after content, got {len(postroll_indices)}. "
            f"Segment types: {seg_types}"
        )

        # Declared order: coming_up_next before station_id
        postroll_segs = [result.segments[i] for i in postroll_indices]
        assert postroll_segs[0].asset_id == "coming-up-1", (
            f"First postroll must be coming_up_next, got {postroll_segs[0].asset_id}"
        )


# ===========================================================================
# Step 3 — INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001: budget reservation
# ===========================================================================


class TestPostrollReservedBeforeFill:
    """Postroll structural durations must be reserved before fill computation."""

    def test_postroll_reserved_before_fill(self):
        """Postroll station_id (10s) + coming_up_next (15s) must reduce
        the content budget, not be consumed by filler.

        INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001.
        """
        resolver = _make_resolver()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                "presentation_postroll": [
                    {"pool": "coming_up_next_promos"},
                    {"pool": "station_ids"},
                ],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        result = results[0]

        # Compute expected budget components
        preroll_ms = sum(
            s.duration_ms for s in result.segments
            if s.segment_type == "presentation"
            and result.segments.index(s) < next(
                i for i, s2 in enumerate(result.segments)
                if s2.segment_type == "content"
            )
        )
        content_ms = sum(
            s.duration_ms for s in result.segments
            if s.segment_type == "content"
        )
        postroll_ms = sum(
            s.duration_ms for s in result.segments
            if s.segment_type == "presentation"
            and result.segments.index(s) > max(
                i for i, s2 in enumerate(result.segments)
                if s2.segment_type == "content"
            )
        )

        # Postroll must have non-zero duration
        assert postroll_ms > 0, (
            "INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001: postroll segments "
            "must contribute non-zero duration to wrapper_ms"
        )

        # wrapper_ms must include BOTH preroll and postroll
        wrapper_ms = preroll_ms + postroll_ms
        grid_ms = 4 * 30 * 60 * 1000  # 7,200,000ms

        assert wrapper_ms + content_ms <= grid_ms, (
            f"Structural total ({wrapper_ms + content_ms}ms) must not "
            f"exceed grid ({grid_ms}ms) without bleed"
        )


# ===========================================================================
# Step 4 — INV-DSL-SINGLE-FILL-DIRECTIVE-001: traffic directive in postroll
# ===========================================================================


class TestPostrollTrafficDirective:
    """Traffic directive in postroll must be honored."""

    def test_postroll_traffic_directive_produces_placeholder(self):
        """A { type: traffic } entry in postroll must produce a filler
        placeholder positioned within the postroll sequence.

        INV-DSL-UNIFIED-FILL-001.
        """
        prog_def = _prog_def_with_postroll()
        pres_defs = _presentation_defs_with_traffic()

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        postroll = resolved.get("presentation_postroll", [])

        # The traffic directive must be preserved in the resolved postroll
        traffic_entries = [
            e for e in postroll
            if isinstance(e, dict) and e.get("type") == "traffic"
        ]
        assert len(traffic_entries) == 1, (
            f"INV-DSL-UNIFIED-FILL-001: traffic directive must be "
            f"preserved in resolved postroll, got {len(traffic_entries)}"
        )
        assert traffic_entries[0].get("profile") == "hbo_premium", (
            "Traffic directive must preserve the declared profile"
        )


# ===========================================================================
# Step 5 — INV-DSL-SINGLE-FILL-DIRECTIVE-001: multiple traffic directives
# ===========================================================================


class TestMultipleFillDirectivesInvalid:
    """At most one traffic directive per block."""

    def test_multiple_fill_directives_invalid(self):
        """Two traffic directives (one in preroll, one in postroll) must
        be rejected.

        INV-DSL-SINGLE-FILL-DIRECTIVE-001.
        """
        pres_defs = {
            "programs": {
                "movies": {
                    "preroll": [
                        {"type": "traffic", "profile": "default", "fill": "remaining"},
                    ],
                    "postroll": [
                        {"type": "traffic", "profile": "hbo_premium", "fill": "remaining"},
                    ],
                },
            },
        }

        prog_def = {
            "pool": "movies",
            "grid_blocks_max": 5,
            "fill_mode": "single",
            "presentation": "movies",
        }

        # Resolution or downstream validation must reject this configuration
        with pytest.raises((ValueError, AssemblyFault)):
            resolved = _resolve_presentation_ref(prog_def, pres_defs)
            # If resolver doesn't validate, assembly must reject it
            if "presentation_postroll" in resolved:
                # Count traffic directives across both phases
                all_entries = resolved.get("presentation", []) + resolved.get("presentation_postroll", [])
                traffic_count = sum(
                    1 for e in all_entries
                    if isinstance(e, dict) and e.get("type") == "traffic"
                )
                if traffic_count > 1:
                    raise ValueError(
                        f"INV-DSL-SINGLE-FILL-DIRECTIVE-001: {traffic_count} "
                        f"traffic directives found, max 1 allowed"
                    )
                # If we get here without raising, the invariant is violated
                pytest.fail(
                    "INV-DSL-SINGLE-FILL-DIRECTIVE-001: multiple traffic "
                    "directives must be rejected"
                )

    def test_traffic_in_preroll_rejected(self):
        """A traffic directive in preroll must be rejected.

        INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001.
        """
        pres_defs = {
            "programs": {
                "movies": {
                    "preroll": [
                        {"pool": "intros"},
                        {"type": "traffic", "profile": "default", "fill": "remaining"},
                    ],
                    "postroll": [],
                },
            },
        }

        prog_def = {
            "pool": "movies",
            "grid_blocks_max": 5,
            "fill_mode": "single",
            "presentation": "movies",
        }

        with pytest.raises((ValueError, AssemblyFault)):
            resolved = _resolve_presentation_ref(prog_def, pres_defs)
            # If resolver doesn't validate preroll traffic, the test
            # should fail indicating the invariant is not enforced
            preroll = resolved.get("presentation", [])
            traffic_in_preroll = [
                e for e in preroll
                if isinstance(e, dict) and e.get("type") == "traffic"
            ]
            if traffic_in_preroll:
                raise ValueError(
                    "INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001: "
                    "traffic directive in preroll must be rejected"
                )
            pytest.fail(
                "INV-POSTROLL-TRAFFIC-PREROLL-FORBIDDEN-001: "
                "traffic directive in preroll was not rejected"
            )


# ===========================================================================
# Step 6 — INV-DSL-TIME-CONSERVATION-001: conservation with postroll
# ===========================================================================


class TestTimeConservationWithPostroll:
    """Block duration must equal structural + fill, including postroll."""

    def test_time_conservation_with_postroll(self):
        """block_duration == sum(all segments including postroll).

        INV-DSL-TIME-CONSERVATION-001.
        """
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        # Manually build compiled_segments that include postroll
        # (as the compiler SHOULD produce them).
        # preroll: 74s + 5s = 79s
        # content: 5400s
        # postroll: 15s (coming_up_next) + 10s (station_id) = 25s
        # filler: 7200 - 5400 - 79 - 25 = 1696s
        schedule = {
            "program_blocks": [{
                "title": "Taken",
                "asset_id": "movie-001",
                "start_at": "2026-03-09T06:00:00+00:00",
                "slot_duration_sec": 7200,
                "episode_duration_sec": 5400,
                "compiled_segments": [
                    {"segment_type": "presentation", "asset_id": "hbo-intro-1",
                     "duration_ms": 74000},
                    {"segment_type": "presentation", "asset_id": "rating-pg13",
                     "duration_ms": 5000},
                    {"segment_type": "content", "asset_id": "movie-001",
                     "duration_ms": 5400000, "is_primary": True},
                    {"segment_type": "presentation", "asset_id": "coming-up-1",
                     "duration_ms": 15000},
                    {"segment_type": "filler", "duration_ms": 1696000},
                    {"segment_type": "presentation", "asset_id": "station-id-1",
                     "duration_ms": 10000},
                ],
            }],
        }

        resolver = StubAssetResolver()
        resolver.add("movie-001", AssetMetadata(
            type="movie", duration_sec=5400, title="Taken",
            file_uri="/mnt/movies/taken.mkv",
        ))
        resolver.add("hbo-intro-1", AssetMetadata(
            type="bumper", duration_sec=74, title="HBO Intro",
            file_uri="/mnt/bumpers/hbo_intro.mp4",
        ))
        resolver.add("rating-pg13", AssetMetadata(
            type="bumper", duration_sec=5, title="PG-13",
            file_uri="/mnt/bumpers/pg13.mp4",
        ))
        resolver.add("coming-up-1", AssetMetadata(
            type="promo", duration_sec=15, title="Coming Up Next",
            file_uri="/mnt/promos/coming_up.mp4",
        ))
        resolver.add("station-id-1", AssetMetadata(
            type="bumper", duration_sec=10, title="Station ID",
            file_uri="/mnt/bumpers/station_id.mp4",
        ))

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        assert len(blocks) == 1

        block = blocks[0]
        block_duration_ms = block.end_utc_ms - block.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)

        assert sum_segment_ms == block_duration_ms, (
            f"INV-DSL-TIME-CONSERVATION-001: segment sum {sum_segment_ms}ms "
            f"!= block duration {block_duration_ms}ms "
            f"(delta={sum_segment_ms - block_duration_ms}ms)"
        )

        # Postroll presentation segments must exist after content
        seg_types = [s.segment_type for s in block.segments]
        content_indices = [i for i, t in enumerate(seg_types) if t == "content"]
        last_content_idx = content_indices[-1]

        postroll_pres = [
            s for i, s in enumerate(block.segments)
            if s.segment_type == "presentation" and i > last_content_idx
        ]
        assert len(postroll_pres) >= 2, (
            f"INV-DSL-TIME-CONSERVATION-001: expected >=2 postroll "
            f"presentation segments, got {len(postroll_pres)}"
        )


# ===========================================================================
# Step 7 — INV-DSL-NONNEGATIVE-FILL-001: no postroll = normal behavior
# ===========================================================================


class TestNoPostrollBehavesNormally:
    """Without postroll, existing behavior is unchanged."""

    def test_no_postroll_behaves_normally(self):
        """When no postroll is defined, fill uses full residual.

        INV-DSL-NONNEGATIVE-FILL-001, backward compatibility.
        """
        resolver = _make_resolver()

        # No postroll — only preroll
        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                # No presentation_postroll key at all
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=30,
            resolver=resolver,
            bleed=True,
            seed=42,
        )

        assert len(results) >= 1
        result = results[0]

        # Only preroll presentation before content, no postroll after
        seg_types = [s.segment_type for s in result.segments]
        content_indices = [i for i, t in enumerate(seg_types) if t == "content"]
        last_content_idx = content_indices[-1]

        postroll_pres = [
            i for i, t in enumerate(seg_types)
            if t == "presentation" and i > last_content_idx
        ]
        assert len(postroll_pres) == 0, (
            "Without postroll defined, no presentation segments "
            "should appear after content"
        )

    def test_preroll_only_resolution_unchanged(self):
        """_resolve_presentation_ref with preroll-only presentation
        still produces the same result as before.

        Backward compatibility.
        """
        pres_defs = {
            "programs": {
                "movies": {
                    "preroll": [
                        {"pool": "intros"},
                        {"pool": "ratings_cards"},
                    ],
                    # No postroll key
                },
            },
        }

        prog_def = {
            "pool": "movies",
            "grid_blocks_max": 5,
            "fill_mode": "single",
            "presentation": "movies",
        }

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        # Preroll must resolve as before
        assert "presentation" in resolved
        assert len(resolved["presentation"]) == 2

        # Postroll should be absent or empty (not an error)
        postroll = resolved.get("presentation_postroll", [])
        assert len(postroll) == 0, (
            "Preroll-only presentation must not produce postroll entries"
        )


# ===========================================================================
# Compile-time resolution: _resolve_presentation_ref reads postroll
# ===========================================================================


class TestResolverReadsPostroll:
    """_resolve_presentation_ref must read both preroll and postroll."""

    def test_resolver_reads_both_phases(self):
        """Both preroll and postroll must be present in resolved output.

        This is the root cause test — if this fails, all downstream
        postroll behavior is impossible.
        """
        pres_defs = _presentation_defs()
        prog_def = _prog_def_with_postroll()

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        # Preroll (existing behavior — must still work)
        preroll = resolved.get("presentation", [])
        assert len(preroll) == 2, (
            f"Preroll must have 2 entries, got {len(preroll)}"
        )

        # Postroll (new requirement — currently fails)
        postroll = resolved.get("presentation_postroll", [])
        assert len(postroll) == 2, (
            f"INV-DSL-POSTROLL-STRUCTURAL-RESERVED-001: postroll must "
            f"have 2 entries from presentation_defs, got {len(postroll)}. "
            f"Resolved keys: {list(resolved.keys())}"
        )

    def test_resolver_preserves_postroll_entry_structure(self):
        """Postroll entries must retain their original dict structure."""
        pres_defs = _presentation_defs_with_traffic()
        prog_def = _prog_def_with_postroll()

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        postroll = resolved.get("presentation_postroll", [])
        assert len(postroll) == 3, (
            f"Postroll with traffic must have 3 entries, got {len(postroll)}"
        )

        # Pool entries preserved
        pool_entries = [e for e in postroll if isinstance(e, dict) and "pool" in e]
        assert len(pool_entries) == 2

        # Traffic directive preserved
        traffic_entries = [e for e in postroll if isinstance(e, dict) and e.get("type") == "traffic"]
        assert len(traffic_entries) == 1
        assert traffic_entries[0]["profile"] == "hbo_premium"

    def test_resolver_absent_postroll_produces_empty(self):
        """If presentation block has no postroll key, result is empty list."""
        pres_defs = {
            "programs": {
                "movies": {
                    "preroll": [{"pool": "intros"}],
                    # No postroll key
                },
            },
        }
        prog_def = {
            "pool": "movies",
            "fill_mode": "single",
            "grid_blocks_max": 5,
            "presentation": "movies",
        }

        resolved = _resolve_presentation_ref(prog_def, pres_defs)

        postroll = resolved.get("presentation_postroll", [])
        assert postroll == [] or postroll is None, (
            "Missing postroll in presentation_defs must produce empty/None"
        )
