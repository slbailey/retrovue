"""Contract tests for Timeline Compilation Templates.

Validates all invariants defined in:
    docs/contracts/timeline_compilation_templates.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION.

These tests exercise the template compilation pipeline:
    YAML DSL (with templates:) → compile_schedule → compiled_segments

Invariant groups:
    INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001
    INV-BREAK-BUDGET-DERIVED-001
    INV-BREAK-COUNT-DURATION-SEPARATED-001
    INV-BREAK-DENSITY-SCALES-001
    INV-BREAK-EXPAND-TO-FILL-001
    INV-CONFORMANCE-MANDATORY-001
    INV-CONTINUITY-DURATION-FILTER-001
    Template composition (extends)
    Backward compatibility (presentation: vs template:)
    Overconstrained / underconstrained policies
"""

from __future__ import annotations

import copy
import math

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.schedule_compiler import (
        compile_schedule,
        parse_dsl,
        ValidationError,
    )
    from retrovue.config.testing import TEST_RESOLVED_CONFIG
except ImportError:
    pytest.skip(
        "retrovue runtime modules not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 1_800_000
GRID_60_MIN_MS = 3_600_000

EPISODE_22_MIN_MS = 1_320_000
EPISODE_44_MIN_MS = 2_640_000
MOVIE_85_MIN_MS = 5_100_000
MOVIE_90_MIN_MS = 5_400_000

TOLERANCE_MS = 40  # INV-CONFORMANCE-MANDATORY-001 / INV-BLOCK-SEGMENT-CONSERVATION-001


# ---------------------------------------------------------------------------
# Resolver helpers
# ---------------------------------------------------------------------------


def _make_resolver(
    *,
    episodes: dict[str, int] | None = None,
    chapter_markers_sec: tuple[float, ...] | None = None,
    bumpers: dict[str, int] | None = None,
) -> StubAssetResolver:
    """Build a StubAssetResolver with configurable episodes and bumpers.

    Args:
        episodes: mapping of asset_id → duration_sec
        chapter_markers_sec: chapter markers for all episodes
        bumpers: mapping of asset_id → duration_sec
    """
    resolver = StubAssetResolver()

    if episodes is None:
        episodes = {"ep-001": 1320}  # 22-min default

    pool_tags = tuple(episodes.keys())
    resolver.add("episodes", AssetMetadata(
        type="pool", duration_sec=0, tags=pool_tags,
    ))
    resolver.register_pools({
        "episodes": {"match": {"type": "episode"}},
    })

    for ep_id, dur_sec in episodes.items():
        resolver.add(ep_id, AssetMetadata(
            type="episode",
            duration_sec=dur_sec,
            title=f"Test Episode {ep_id}",
            chapter_markers_sec=chapter_markers_sec,
            loudness_gain_db=-2.0,
            file_uri=f"/mnt/episodes/{ep_id}.mkv",
        ))

    if bumpers:
        bumper_tags = tuple(bumpers.keys())
        resolver.add("bumpers", AssetMetadata(
            type="pool", duration_sec=0, tags=bumper_tags,
        ))
        resolver.register_pools({
            "bumpers": {"match": {"type": "bumper"}},
        })
        for b_id, dur_sec in bumpers.items():
            resolver.add(b_id, AssetMetadata(
                type="bumper",
                duration_sec=dur_sec,
                title=f"Bumper {b_id}",
                loudness_gain_db=0.0,
                file_uri=f"/mnt/bumpers/{b_id}.mkv",
            ))

    return resolver


# ---------------------------------------------------------------------------
# DSL builders
# ---------------------------------------------------------------------------


def _base_dsl(
    *,
    templates: dict | None = None,
    program_template: str | None = None,
    program_presentation: str | None = None,
    channel_type: str = "network",
    slots: int = 6,
    grid_blocks: int | None = None,
    grid_blocks_max: int | None = None,
) -> dict:
    """Build a minimal channel DSL dict with optional templates section.

    Defaults: slots=6 (3 hours of 30-min grid) and grid_blocks_max=6
    to accommodate long-form content without assembly faults.
    """
    prog_def: dict = {
        "pool": "episodes",
        "fill_mode": "single",
    }
    if grid_blocks is not None:
        prog_def["grid_blocks"] = grid_blocks
    elif grid_blocks_max is not None:
        prog_def["grid_blocks_max"] = grid_blocks_max
    else:
        prog_def["grid_blocks_max"] = 6  # allow up to 3 hours

    if program_template is not None:
        prog_def["template"] = program_template
    if program_presentation is not None:
        prog_def["presentation"] = program_presentation

    dsl: dict = {
        "channel": "test-channel",
        "broadcast_day": "2026-04-10",
        "timezone": "UTC",
        "channel_type": channel_type,
        "template": "network_television",
        "pools": {
            "episodes": {
                "select": {"where": {"type": {"eq": "episode"}}},
            },
        },
        "programs": {
            "test_show": prog_def,
        },
        "schedule": {
            "all_day": [
                {
                    "start": "06:00",
                    "slots": slots,
                    "program": "test_show",
                    "progression": "sequential",
                },
            ],
        },
    }

    if templates is not None:
        dsl["templates"] = templates

    return dsl


def _extract_compiled_segments(result: dict) -> list[dict]:
    """Extract compiled_segments from the first block of a compilation result."""
    blocks = result["program_blocks"]
    assert len(blocks) > 0, "Expected at least one compiled block"
    return blocks[0]["compiled_segments"]


def _extract_block(result: dict, index: int = 0) -> dict:
    """Extract a compiled block from the result."""
    blocks = result["program_blocks"]
    assert len(blocks) > index, f"Expected at least {index + 1} compiled block(s)"
    return blocks[index]


def _segment_type_durations(segments: list[dict], seg_type: str) -> list[int]:
    """Extract durations for segments of a given type."""
    return [s["duration_ms"] for s in segments if s["segment_type"] == seg_type]


def _total_duration(segments: list[dict]) -> int:
    """Sum of all segment durations."""
    return sum(s["duration_ms"] for s in segments)


def _filler_count(segments: list[dict]) -> int:
    """Count filler (break) segments."""
    return sum(1 for s in segments if s["segment_type"] == "filler")


# ---------------------------------------------------------------------------
# INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001
# Templates define break *placement strategy* and *continuity element rules*
# — not fixed break counts or durations.
# ---------------------------------------------------------------------------


class TestTemplateBehaviorNotDuration:
    """INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001: Templates must not contain
    break_count, break_duration_sec, or grid_slots fields."""

    def test_template_no_break_count_field(self):
        """Template YAML with `break_count` field is rejected."""
        dsl = _base_dsl(
            templates={
                "sitcom": {
                    "breaks": {
                        "strategy": "synthetic",
                        "target_segment_minutes": 11,
                        "break_count": 3,  # FORBIDDEN
                    },
                },
            },
            program_template="sitcom",
        )
        resolver = _make_resolver()
        with pytest.raises((ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

    def test_template_no_break_duration_field(self):
        """Template YAML with `break_duration_sec` field is rejected."""
        dsl = _base_dsl(
            templates={
                "sitcom": {
                    "breaks": {
                        "strategy": "synthetic",
                        "target_segment_minutes": 11,
                        "break_duration_sec": 180,  # FORBIDDEN
                    },
                },
            },
            program_template="sitcom",
        )
        resolver = _make_resolver()
        with pytest.raises((ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

    def test_template_no_grid_slots_field(self):
        """Template YAML with `grid_slots` field is rejected."""
        dsl = _base_dsl(
            templates={
                "sitcom": {
                    "breaks": {
                        "strategy": "synthetic",
                        "target_segment_minutes": 11,
                        "grid_slots": 2,  # FORBIDDEN
                    },
                },
            },
            program_template="sitcom",
        )
        resolver = _make_resolver()
        with pytest.raises((ValidationError, ValueError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

    def test_template_applies_to_varying_runtimes(self):
        """Same template produces valid plans for 22-min, 44-min, and 60-min content."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }

        for dur_sec, label in [(1320, "22min"), (2640, "44min"), (3600, "60min")]:
            resolver = _make_resolver(episodes={"ep-001": dur_sec})
            dsl = _base_dsl(templates=templates, program_template="sitcom")
            result = compile_schedule(
                dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG,
            )
            segments = _extract_compiled_segments(result)
            assert len(segments) > 0, f"No segments for {label} content"
            block = _extract_block(result)
            slot_ms = block["slot_duration_sec"] * 1000
            total = _total_duration(segments)
            assert abs(total - slot_ms) <= TOLERANCE_MS, (
                f"{label}: segment total {total} != slot {slot_ms} "
                f"(drift {abs(total - slot_ms)}ms)"
            )


# ---------------------------------------------------------------------------
# INV-BREAK-BUDGET-DERIVED-001
# break_budget = scheduled_duration - content_duration - presentation_duration
# ---------------------------------------------------------------------------


class TestBreakBudgetDerived:
    """INV-BREAK-BUDGET-DERIVED-001: Break budget must equal
    scheduled_duration - content_duration - presentation_duration."""

    def test_break_budget_equals_derived_formula(self):
        """Break budget matches the formula with no presentation elements."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})  # 22 min
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        content_ms = sum(_segment_type_durations(segments, "content"))
        filler_ms = sum(_segment_type_durations(segments, "filler"))
        presentation_ms = sum(
            s["duration_ms"] for s in segments
            if s["segment_type"] not in ("content", "filler")
        )

        expected_budget = slot_ms - content_ms - presentation_ms
        assert abs(filler_ms - expected_budget) <= TOLERANCE_MS, (
            f"Break budget {filler_ms} != expected {expected_budget} "
            f"(slot={slot_ms}, content={content_ms}, presentation={presentation_ms})"
        )

    def test_break_budget_includes_presentation(self):
        """Presentation element durations reduce the break budget."""
        templates = {
            "sitcom": {
                "continuity": {
                    "presentation": [
                        {"type": "bumper", "pool": "bumpers", "duration_sec": 10},
                    ],
                },
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(
            episodes={"ep-001": 1320},
            bumpers={"bumper-001": 10},
        )
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        content_ms = sum(_segment_type_durations(segments, "content"))
        filler_ms = sum(_segment_type_durations(segments, "filler"))
        presentation_ms = sum(
            s["duration_ms"] for s in segments
            if s["segment_type"] not in ("content", "filler")
        )

        # Presentation exists and reduced the budget
        assert presentation_ms > 0, "Expected presentation segments"
        expected_budget = slot_ms - content_ms - presentation_ms
        assert abs(filler_ms - expected_budget) <= TOLERANCE_MS


# ---------------------------------------------------------------------------
# INV-BREAK-COUNT-DURATION-SEPARATED-001
# Break count and break duration are determined independently.
# ---------------------------------------------------------------------------


class TestBreakCountDurationSeparated:
    """INV-BREAK-COUNT-DURATION-SEPARATED-001: Changing break budget
    does not change break count; changing target_segment_minutes does
    not change individual break duration."""

    def test_break_count_independent_of_duration(self):
        """Same target_segment_minutes, different slot sizes → same break count,
        different break durations."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }

        # 22-min content in a 30-min slot (grid_blocks=1)
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl_30 = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=1,
        )
        result_30 = compile_schedule(
            dsl_30, resolver, resolved_config=TEST_RESOLVED_CONFIG,
        )
        seg_30 = _extract_compiled_segments(result_30)
        breaks_30 = _filler_count(seg_30)
        filler_30 = sum(_segment_type_durations(seg_30, "filler"))

        # 22-min content in a 60-min slot (grid_blocks=2)
        dsl_60 = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=2,
        )
        result_60 = compile_schedule(
            dsl_60, resolver, resolved_config=TEST_RESOLVED_CONFIG,
        )
        seg_60 = _extract_compiled_segments(result_60)
        breaks_60 = _filler_count(seg_60)
        filler_60 = sum(_segment_type_durations(seg_60, "filler"))

        # Same break count (target_segment_minutes unchanged, same content)
        assert breaks_30 == breaks_60, (
            f"Break count should be independent of budget: "
            f"30min→{breaks_30}, 60min→{breaks_60}"
        )
        # Different break durations (budgets differ)
        assert filler_60 > filler_30, (
            "Larger slot should have more total filler time"
        )


# ---------------------------------------------------------------------------
# INV-BREAK-DENSITY-SCALES-001
# break_count = floor(content_duration_minutes / target_segment_minutes)
# ---------------------------------------------------------------------------


class TestBreakDensityScales:
    """INV-BREAK-DENSITY-SCALES-001: Break density scales with content
    runtime via target_segment_minutes."""

    def test_break_density_22min(self):
        """target_segment_minutes=11 with 22-min content → ~2 breaks."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        breaks = _filler_count(segments)
        expected = math.floor(22 / 11)  # 2
        assert breaks == expected, f"Expected ~{expected} breaks, got {breaks}"

    def test_break_density_44min(self):
        """target_segment_minutes=11 with 44-min content → ~4 breaks."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 2640})  # 44 min
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        breaks = _filler_count(segments)
        expected = math.floor(44 / 11)  # 4
        assert breaks == expected, f"Expected ~{expected} breaks, got {breaks}"

    def test_break_density_90min(self):
        """target_segment_minutes=20 with 85-min content → 4 breaks."""
        templates = {
            "movie_broadcast": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 20,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 5100})  # 85 min
        dsl = _base_dsl(templates=templates, program_template="movie_broadcast")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        breaks = _filler_count(segments)
        expected = math.floor(85 / 20)  # 4
        assert breaks == expected, f"Expected ~{expected} breaks, got {breaks}"


# ---------------------------------------------------------------------------
# INV-BREAK-EXPAND-TO-FILL-001
# Breaks expand to consume the full break budget.
# ---------------------------------------------------------------------------


class TestBreakExpandToFill:
    """INV-BREAK-EXPAND-TO-FILL-001: Breaks must consume the full
    break budget. No fixed-length breaks with leftover."""

    def test_breaks_expand_to_fill_budget(self):
        """Sum of break durations equals break budget (no leftover)."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        content_ms = sum(_segment_type_durations(segments, "content"))
        filler_ms = sum(_segment_type_durations(segments, "filler"))
        presentation_ms = sum(
            s["duration_ms"] for s in segments
            if s["segment_type"] not in ("content", "filler")
        )

        budget = slot_ms - content_ms - presentation_ms
        assert abs(filler_ms - budget) <= TOLERANCE_MS, (
            f"Breaks {filler_ms}ms should fill budget {budget}ms"
        )

    def test_breaks_not_fixed_length(self):
        """Different break budgets produce different break durations
        for the same break count."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }

        # 22-min content in 30-min slot
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=1,
        )
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        fillers_a = _segment_type_durations(
            _extract_compiled_segments(result), "filler",
        )

        # 23-min content in 30-min slot (less budget, same break count)
        # floor(23/11) = 2 breaks, same as floor(22/11) = 2
        resolver2 = _make_resolver(episodes={"ep-001": 1380})  # 23 min
        dsl2 = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=1,
        )
        result2 = compile_schedule(dsl2, resolver2, resolved_config=TEST_RESOLVED_CONFIG)
        fillers_b = _segment_type_durations(
            _extract_compiled_segments(result2), "filler",
        )

        # Same break count but different individual durations
        assert len(fillers_a) == len(fillers_b), "Break count should be the same"
        assert sum(fillers_a) != sum(fillers_b), (
            "Break durations should differ when budgets differ"
        )


# ---------------------------------------------------------------------------
# INV-CONFORMANCE-MANDATORY-001
# sum(segments) == scheduled_block_duration ± 40ms
# ---------------------------------------------------------------------------


class TestConformanceMandatory:
    """INV-CONFORMANCE-MANDATORY-001: Compiled playout plan must exactly
    match the scheduled block duration within 40ms tolerance."""

    def test_conformance_exact_match(self):
        """sum(segments) == scheduled_duration ± 40ms for a compiled block."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        total = _total_duration(segments)
        drift = abs(total - slot_ms)
        assert drift <= TOLERANCE_MS, (
            f"Conformance violation: total={total}ms, slot={slot_ms}ms, "
            f"drift={drift}ms > {TOLERANCE_MS}ms"
        )

    def test_conformance_rejects_drift(self):
        """Verify conformance holds for multiple content lengths."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        for dur_sec in [1320, 2640, 1200, 2400]:
            resolver = _make_resolver(episodes={"ep-001": dur_sec})
            dsl = _base_dsl(templates=templates, program_template="sitcom")
            result = compile_schedule(
                dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG,
            )
            segments = _extract_compiled_segments(result)
            block = _extract_block(result)
            slot_ms = block["slot_duration_sec"] * 1000
            total = _total_duration(segments)
            assert abs(total - slot_ms) <= TOLERANCE_MS


# ---------------------------------------------------------------------------
# INV-CONTINUITY-DURATION-FILTER-001
# max_duration_sec is pool selection filter, not truncation.
# ---------------------------------------------------------------------------


class TestContinuityDurationFilter:
    """INV-CONTINUITY-DURATION-FILTER-001: max_duration_sec on a continuity
    element filters the pool, does not truncate."""

    def test_max_duration_sec_filters_pool(self):
        """Asset with duration > max_duration_sec is excluded from candidates."""
        templates = {
            "sitcom": {
                "continuity": {
                    "presentation": [
                        {
                            "type": "bumper",
                            "pool": "bumpers",
                            "max_duration_sec": 5,  # only accept ≤5s bumpers
                        },
                    ],
                },
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # bumper-long is 15s (should be excluded), bumper-short is 4s
        resolver = _make_resolver(
            episodes={"ep-001": 1320},
            bumpers={"bumper-long": 15, "bumper-short": 4},
        )
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        # No presentation segment should reference bumper-long
        for seg in segments:
            if seg["segment_type"] == "presentation":
                assert seg.get("asset_id") != "bumper-long", (
                    "bumper-long (15s) should be excluded by max_duration_sec=5"
                )

    def test_max_duration_sec_no_truncation(self):
        """Selected asset plays at full native duration, not truncated."""
        templates = {
            "sitcom": {
                "continuity": {
                    "presentation": [
                        {
                            "type": "bumper",
                            "pool": "bumpers",
                            "max_duration_sec": 10,
                        },
                    ],
                },
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # bumper is 8s, which is ≤10s so should be selected
        resolver = _make_resolver(
            episodes={"ep-001": 1320},
            bumpers={"bumper-001": 8},
        )
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        pres_segs = [
            s for s in segments
            if s["segment_type"] == "presentation"
            and s.get("asset_id") == "bumper-001"
        ]
        # If selected, it must play at full 8000ms, not truncated to 10000ms
        for seg in pres_segs:
            assert seg["duration_ms"] == 8000, (
                f"Bumper should play at native 8000ms, got {seg['duration_ms']}ms"
            )


# ---------------------------------------------------------------------------
# Template composition (extends)
# ---------------------------------------------------------------------------


class TestTemplateComposition:
    """Template inheritance via `extends` keyword."""

    def test_extends_inherits_parent(self):
        """Child template inherits parent break strategy and config."""
        templates = {
            "base_broadcast": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 15,
                },
            },
            "sitcom": {
                "extends": "base_broadcast",
                # No breaks override → inherits from parent
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        # Inherited target_segment_minutes=15: floor(22/15) = 1 break
        breaks = _filler_count(segments)
        expected = math.floor(22 / 15)  # 1
        assert breaks == expected, (
            f"Inherited template should produce {expected} breaks, got {breaks}"
        )

    def test_extends_child_overrides(self):
        """Child field overrides parent at the same key path."""
        templates = {
            "base_broadcast": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 15,
                },
            },
            "sitcom": {
                "extends": "base_broadcast",
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,  # override
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        dsl = _base_dsl(templates=templates, program_template="sitcom")
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        # Overridden target_segment_minutes=11: floor(22/11) = 2 breaks
        breaks = _filler_count(segments)
        expected = math.floor(22 / 11)  # 2
        assert breaks == expected, (
            f"Overridden template should produce {expected} breaks, got {breaks}"
        )

    def test_extends_circular_rejected(self):
        """Circular `extends` reference is rejected at validation."""
        templates = {
            "a": {"extends": "b", "breaks": {"strategy": "synthetic", "target_segment_minutes": 11}},
            "b": {"extends": "a", "breaks": {"strategy": "synthetic", "target_segment_minutes": 11}},
        }
        dsl = _base_dsl(templates=templates, program_template="a")
        resolver = _make_resolver()
        with pytest.raises((ValidationError, ValueError, RecursionError)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Template and presentation coexistence rules."""

    def test_template_wins_over_presentation(self):
        """When both `presentation:` and `template:` present on a program,
        template continuity is used."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
            },
        }
        # Program has both presentation (legacy) and template (new)
        dsl = _base_dsl(
            templates=templates,
            program_template="sitcom",
            program_presentation="legacy_pres",
        )
        # Add legacy presentation section
        dsl["presentation"] = {
            "programs": {
                "legacy_pres": {
                    "midroll": [
                        {
                            "type": "traffic",
                            "profile": "sitcom",
                            "fill": "remaining",
                            "placement": {
                                "fallback": {
                                    "strategy": "weighted_positions",
                                    "positions": [0.30, 0.72],
                                    "weights": [1, 1],
                                },
                            },
                        },
                    ],
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)

        # Template specifies target_segment_minutes=11 → floor(22/11) = 2 breaks
        # Legacy presentation specifies 2 DSL positions at 0.30 and 0.72
        # Template should win — break count should be from template logic
        breaks = _filler_count(segments)
        expected = math.floor(22 / 11)
        assert breaks == expected, (
            f"Template should override presentation: expected {expected} breaks, "
            f"got {breaks}"
        )

    def test_no_template_section_unchanged(self):
        """Channel without `templates:` section compiles identically
        to current behavior."""
        # No templates section — pure legacy path
        dsl = _base_dsl(program_presentation="sitcom_30")
        dsl["presentation"] = {
            "programs": {
                "sitcom_30": {
                    "midroll": [
                        {
                            "type": "traffic",
                            "profile": "sitcom",
                            "fill": "remaining",
                            "placement": {
                                "fallback": {
                                    "strategy": "weighted_positions",
                                    "positions": [0.30, 0.72],
                                    "weights": [1, 1],
                                },
                            },
                        },
                    ],
                },
            },
        }
        resolver = _make_resolver(episodes={"ep-001": 1320})
        # Should compile without error — existing behavior preserved
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        segments = _extract_compiled_segments(result)
        assert len(segments) > 0, "Legacy path should produce segments"
        # Conformance still holds
        block = _extract_block(result)
        slot_ms = block["slot_duration_sec"] * 1000
        total = _total_duration(segments)
        assert abs(total - slot_ms) <= TOLERANCE_MS


# ---------------------------------------------------------------------------
# Overconstrained / underconstrained policies
# ---------------------------------------------------------------------------


class TestOverconstrainedPolicy:
    """Overconstrained and underconstrained template policies."""

    def test_overconstrained_bleed(self):
        """Overconstrained block with `bleed` policy extends into adjacent slots."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "overconstrained": "bleed",
            },
        }
        # 35-min content in 30-min slot → overconstrained
        resolver = _make_resolver(episodes={"ep-001": 2100})  # 35 min
        dsl = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=1,
        )
        # Enable bleed at schedule block level
        dsl["schedule"]["all_day"][0]["bleed"] = True
        result = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        block = _extract_block(result)
        # Block should have expanded beyond 30 min slot
        assert block["slot_duration_sec"] >= 2100, (
            f"Bleed should expand slot to fit content, got {block['slot_duration_sec']}s"
        )

    def test_overconstrained_reject(self):
        """Overconstrained block with `reject` policy fails compilation."""
        templates = {
            "sitcom": {
                "breaks": {
                    "strategy": "synthetic",
                    "target_segment_minutes": 11,
                },
                "overconstrained": "reject",
            },
        }
        # 35-min content in 30-min slot → overconstrained, should reject
        resolver = _make_resolver(episodes={"ep-001": 2100})
        dsl = _base_dsl(
            templates=templates, program_template="sitcom",
            grid_blocks=1,
        )
        with pytest.raises((ValidationError, ValueError, Exception)):
            compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
