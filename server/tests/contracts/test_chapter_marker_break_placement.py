"""Contract tests for Chapter Marker Break Placement.

Validates all invariants defined in:
    docs/contracts/chapter_marker_break_placement.md

Derived From: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION

Invariant:
    INV-BREAK-PLACEMENT-PRIORITY-001 — Strict break placement priority order
    INV-BREAK-DENSITY-SCALES-001 — target_segment_minutes drives break count in fallback
    INV-BREAK-001 — Break detection receives chapter markers via AssemblySegment
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.block_break_layout import (
        BlockBreakLayout,
        MidrollOpportunity,
        MidrollPlan,
        PostrollEntry,
        StructuralEntry,
        SuppressedSource,
        build_break_layout,
        expand_break_layout,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime.block_break_layout not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN = 1_800_000
GRID_60_MIN = 3_600_000
EPISODE_22_MIN = 1_320_000  # 22-min sitcom
EPISODE_44_MIN = 2_640_000  # 44-min drama

# Fixed anchor: 2026-03-27T20:00:00Z in ms
BLOCK_START_UTC_MS = 1_774_929_600_000

# Chapter markers at ~7min and ~15min into a 22-min episode
CHAPTER_MARKERS_MS = (420_000, 900_000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_network(
    *,
    grid_slot_ms: int = GRID_30_MIN,
    content_duration_ms: int = EPISODE_22_MIN,
    chapter_markers_ms: tuple[int, ...] | None = None,
    dsl_midroll: list[dict] | None = None,
    preroll: list[StructuralEntry] | None = None,
    postroll: list[PostrollEntry] | None = None,
    min_segment_ms: int = 0,
    target_segment_minutes: int | None = None,
    break_strategy: str | None = None,
) -> BlockBreakLayout:
    """Build a network-channel layout with sensible defaults."""
    return build_break_layout(
        grid_slot_ms=grid_slot_ms,
        content_duration_ms=content_duration_ms,
        channel_type="network",
        block_start_utc_ms=BLOCK_START_UTC_MS,
        chapter_markers_ms=chapter_markers_ms,
        dsl_midroll=dsl_midroll,
        preroll=preroll or [],
        postroll=postroll or [],
        min_segment_ms=min_segment_ms,
        target_segment_minutes=target_segment_minutes,
        break_strategy=break_strategy,
    )


# ---------------------------------------------------------------------------
# INV-BREAK-PLACEMENT-PRIORITY-001 tests
# ---------------------------------------------------------------------------


class TestChapterMarkersPriority:
    """Chapter markers (Tier 1) take priority over algorithmic (Tier 3)."""

    def test_chapter_markers_take_priority_over_algorithmic(self):
        """Asset with chapter markers produces only source: 'chapter'
        opportunities, no algorithmic.

        INV-BREAK-PLACEMENT-PRIORITY-001
        """
        layout = _build_network(chapter_markers_ms=CHAPTER_MARKERS_MS)

        assert layout.midroll.source == "chapter"
        assert len(layout.midroll.opportunities) == 2
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert positions == [420_000, 900_000]

        # No algorithmic breaks should exist — chapter markers suppress them
        # (verified by source being "chapter", not "algorithmic")

    def test_chapter_markers_coexist_with_boundary(self):
        """Accumulate program: chapter breaks within segments + boundary
        breaks between segments.

        INV-BREAK-PLACEMENT-PRIORITY-001: boundary opportunities are
        independent of chapter marker presence on individual assets.

        Note: This test validates at the break_detection.py level since
        boundary detection operates on multi-segment assembly results.
        At the block_break_layout level (single content segment), we
        verify that chapter source is used AND boundary opportunities
        would not be suppressed by chapter presence.
        """
        # Single-segment layout with chapter markers → chapters used
        layout = _build_network(chapter_markers_ms=CHAPTER_MARKERS_MS)
        assert layout.midroll.source == "chapter"

        # Verify no suppression record for "boundary" exists
        # (boundary is a separate tier, not suppressed by chapter presence)
        suppressed_sources = [s.source for s in layout.suppressed_sources]
        assert "boundary" not in suppressed_sources


class TestChapterMarkersPreferredStrategy:
    """Template strategy: chapter_markers_preferred."""

    def test_chapter_markers_preferred_strategy_uses_markers(self):
        """Template with strategy: chapter_markers_preferred and asset
        with markers uses chapter positions.

        INV-BREAK-PLACEMENT-PRIORITY-001
        """
        layout = _build_network(
            chapter_markers_ms=CHAPTER_MARKERS_MS,
            break_strategy="chapter_markers_preferred",
        )

        assert layout.midroll.source == "chapter"
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert positions == [420_000, 900_000]

    def test_no_chapter_markers_falls_to_synthetic(self):
        """Asset without chapter markers with chapter_markers_preferred
        strategy produces algorithmic breaks.

        INV-BREAK-PLACEMENT-PRIORITY-001
        """
        layout = _build_network(
            chapter_markers_ms=None,
            break_strategy="chapter_markers_preferred",
            target_segment_minutes=11,
        )

        assert layout.midroll.source == "algorithmic"
        assert len(layout.midroll.opportunities) > 0


class TestSyntheticStrategy:
    """Template strategy: synthetic — ignores chapter markers."""

    def test_synthetic_strategy_ignores_chapter_markers(self):
        """Template with strategy: synthetic ignores chapter markers
        even when present.

        INV-BREAK-PLACEMENT-PRIORITY-001
        """
        layout = _build_network(
            chapter_markers_ms=CHAPTER_MARKERS_MS,
            break_strategy="synthetic",
            target_segment_minutes=11,
        )

        # Strategy=synthetic must skip chapter markers
        assert layout.midroll.source != "chapter"
        assert layout.midroll.source in ("algorithmic", "dsl")

        # Chapter markers should be recorded as suppressed
        suppressed_sources = [s.source for s in layout.suppressed_sources]
        assert "chapter" in suppressed_sources


class TestFallbackBehavior:
    """Fallback from chapter_markers_preferred to synthetic."""

    def test_fallback_uses_target_segment_minutes(self):
        """Fallback from chapter_markers_preferred to synthetic uses
        target_segment_minutes for break count.

        INV-BREAK-PLACEMENT-PRIORITY-001, INV-BREAK-DENSITY-SCALES-001
        """
        # No chapter markers → fallback to synthetic
        # 22-min content / 11 target_segment_minutes = 2 breaks (floor)
        layout = _build_network(
            chapter_markers_ms=None,
            break_strategy="chapter_markers_preferred",
            target_segment_minutes=11,
        )

        assert layout.midroll.source == "algorithmic"
        assert len(layout.midroll.opportunities) == 2


class TestDataShape:
    """Chapter marker data shape from assembly."""

    def test_chapter_marker_data_shape_from_assembly(self):
        """Break detection receives chapter markers via chapter_markers_ms
        on AssemblySegment, not raw catalog.

        INV-BREAK-001: The build_break_layout function accepts
        chapter_markers_ms as a tuple[int, ...] | None parameter.
        """
        import inspect

        sig = inspect.signature(build_break_layout)
        assert "chapter_markers_ms" in sig.parameters
        param = sig.parameters["chapter_markers_ms"]
        # Should accept tuple[int, ...] | None — verify it's a keyword arg
        assert param.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )


class TestInvalidMarkers:
    """Invalid marker filtering."""

    def test_invalid_markers_filtered(self):
        """Markers at position 0 and at segment boundary are excluded.

        INV-BREAK-PLACEMENT-PRIORITY-001
        """
        # Markers: 0 (invalid), 420_000 (valid), EPISODE_22_MIN (boundary, invalid)
        layout = _build_network(
            chapter_markers_ms=(0, 420_000, EPISODE_22_MIN),
        )

        assert layout.midroll.source == "chapter"
        # Only the valid marker at 420_000 should survive
        positions = [o.position_ms for o in layout.midroll.opportunities]
        assert positions == [420_000]


class TestBackwardCompat:
    """Backward compatibility — no template."""

    def test_backward_compat_no_template(self):
        """Channel without templates: section uses existing priority model
        unchanged.

        INV-BREAK-PLACEMENT-PRIORITY-001: When no strategy is specified
        (break_strategy=None), the existing priority model applies:
        chapter > dsl > algorithmic.
        """
        # With chapter markers, no strategy → chapters win (existing behavior)
        layout_with_chapters = _build_network(
            chapter_markers_ms=CHAPTER_MARKERS_MS,
            break_strategy=None,
        )
        assert layout_with_chapters.midroll.source == "chapter"

        # Without chapter markers, no strategy → algorithmic (existing behavior)
        layout_no_chapters = _build_network(
            chapter_markers_ms=None,
            break_strategy=None,
        )
        assert layout_no_chapters.midroll.source == "algorithmic"
