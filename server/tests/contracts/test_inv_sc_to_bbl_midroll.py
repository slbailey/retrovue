"""Contract tests: INV-SC-TO-BBL-MIDROLL-001

If prog_def contains "presentation_midroll", then _expand_to_compiled_segments
MUST accept it via dsl_midroll parameter, and both call sites in
_compile_program_block MUST forward prog_def.get("presentation_midroll").

This tests the plumbing only — not the BBL cutover.
"""

from __future__ import annotations

import inspect

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.program_definition import AssemblyResult, AssemblySegment
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


def _make_resolver(*, chapter_markers_sec=None) -> StubAssetResolver:
    resolver = StubAssetResolver()
    resolver.add("ep-001", AssetMetadata(
        type="episode",
        duration_sec=1320,
        title="Cheers S01E01",
        file_uri="/mnt/episodes/cheers_s01e01.mkv",
        chapter_markers_sec=chapter_markers_sec,
    ))
    return resolver


def _make_assembly_result(*, duration_ms: int = 1_320_000) -> AssemblyResult:
    return AssemblyResult(
        segments=[
            AssemblySegment(
                asset_id="ep-001",
                duration_ms=duration_ms,
                segment_type="content",
            ),
        ],
        total_runtime_ms=duration_ms,
    )


DSL_MIDROLL = [
    {
        "type": "traffic",
        "profile": "sitcom",
        "placement": {
            "fallback": {
                "strategy": "weighted_positions",
                "positions": [0.30, 0.72],
                "weights": [1, 1],
            }
        },
    }
]


# ---------------------------------------------------------------------------
# INV-SC-TO-BBL-MIDROLL-001: Signature accepts dsl_midroll
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestExpandAcceptsDslMidroll:
    """_expand_to_compiled_segments must accept a dsl_midroll parameter."""

    def test_signature_has_dsl_midroll(self):
        sig = inspect.signature(_expand_to_compiled_segments)
        assert "dsl_midroll" in sig.parameters, (
            f"_expand_to_compiled_segments missing dsl_midroll param. "
            f"Has: {list(sig.parameters.keys())}"
        )

    def test_dsl_midroll_defaults_to_none(self):
        sig = inspect.signature(_expand_to_compiled_segments)
        param = sig.parameters["dsl_midroll"]
        assert param.default is None, (
            f"dsl_midroll default must be None, got {param.default!r}"
        )

    def test_callable_without_dsl_midroll(self):
        """Existing callers that don't pass dsl_midroll must still work."""
        resolver = _make_resolver()
        result = _make_assembly_result()
        # Call without dsl_midroll — must not raise
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
        )
        assert isinstance(compiled, list)
        assert len(compiled) > 0

    def test_callable_with_dsl_midroll(self):
        """Passing dsl_midroll must be accepted without error."""
        resolver = _make_resolver()
        result = _make_assembly_result()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        assert isinstance(compiled, list)
        assert len(compiled) > 0

    def test_callable_with_dsl_midroll_none(self):
        """Passing dsl_midroll=None explicitly must work identically to omitting it."""
        resolver = _make_resolver()
        result = _make_assembly_result()
        compiled_without = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
        )
        compiled_with_none = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=None,
        )
        # Same output — dsl_midroll=None should not change behavior
        assert compiled_without == compiled_with_none


# ---------------------------------------------------------------------------
# INV-SC-TO-BBL-MIDROLL-001: Chapter-first priority (post-cutover)
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestBehaviorPostCutover:
    """After BBL cutover, chapters take priority over DSL midroll."""

    def test_dsl_ignored_when_chapters_present(self):
        """When chapters present, DSL midroll is ignored — chapter markers
        are the primary source per INV-BBL-SOURCE-003."""
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly_result()
        compiled_chapter = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
        )
        compiled_both = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        # Chapters win — output identical regardless of DSL
        chapter_offsets = [
            s["asset_start_offset_ms"]
            for s in compiled_chapter if s["segment_type"] == "content"
        ]
        both_offsets = [
            s["asset_start_offset_ms"]
            for s in compiled_both if s["segment_type"] == "content"
        ]
        assert chapter_offsets == both_offsets, (
            "When chapters present, DSL should be ignored — offsets must match"
        )

    def test_dsl_activates_when_chapters_absent(self):
        """When no chapters, DSL midroll positions are used as fallback."""
        resolver = _make_resolver(chapter_markers_sec=None)
        result = _make_assembly_result()
        compiled_algo = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
        )
        compiled_dsl = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        # Without chapters, DSL should produce different positions than algorithmic
        algo_offsets = [
            s["asset_start_offset_ms"]
            for s in compiled_algo if s["segment_type"] == "content"
        ]
        dsl_offsets = [
            s["asset_start_offset_ms"]
            for s in compiled_dsl if s["segment_type"] == "content"
        ]
        assert algo_offsets != dsl_offsets, (
            "DSL midroll should produce different positions than algorithmic"
        )

    def test_movie_output_unchanged_with_dsl_midroll(self):
        resolver = _make_resolver()
        resolver.add("movie-001", AssetMetadata(
            type="movie", duration_sec=5400,
            title="Test Movie", file_uri="/mnt/movies/test.mkv",
        ))
        result = AssemblyResult(
            segments=[
                AssemblySegment(
                    asset_id="movie-001",
                    duration_ms=5_400_000,
                    segment_type="content",
                ),
            ],
            total_runtime_ms=5_400_000,
        )
        compiled_old = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=7_200_000,
            start_utc_ms=0,
            channel_type="movie",
        )
        compiled_new = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=7_200_000,
            start_utc_ms=0,
            channel_type="movie",
            dsl_midroll=DSL_MIDROLL,
        )
        assert compiled_old == compiled_new
