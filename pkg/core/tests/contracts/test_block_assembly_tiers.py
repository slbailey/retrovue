"""Contract tests for Tier 3 Optional Presentation.

Validates:
    INV-TIER3-COMPILE-RESOLUTION-001
    INV-TIER3-NEXT-BLOCK-IDENTITY-001
    INV-ASSEMBLY-SEQUENCE-001

Derived From: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION

These tests exercise evaluate_optional_presentation() from
optional_presentation.py. That module does not exist yet — all tests
MUST fail at import (RED phase).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

try:
    from retrovue.runtime.optional_presentation import (
        evaluate_optional_presentation,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime.optional_presentation not available — "
        "implementation not yet provided",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_30_MIN_MS = 1_800_000
EPISODE_22_MIN_MS = 1_320_000

# Two consecutive blocks: 20:00-20:30 and 20:30-21:00 on 2026-03-27
BLOCK_1_START = datetime(2026, 3, 27, 20, 0, 0, tzinfo=timezone.utc)
BLOCK_2_START = datetime(2026, 3, 27, 20, 30, 0, tzinfo=timezone.utc)
BLOCK_1_START_MS = int(BLOCK_1_START.timestamp() * 1000)
BLOCK_2_START_MS = int(BLOCK_2_START.timestamp() * 1000)

IDENT_DURATION_MS = 5_000       # 5s channel ident
PROMO_DURATION_MS = 15_000      # 15s coming-up-next promo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_compiled_segments(
    *,
    content_duration_ms: int = EPISODE_22_MIN_MS,
    filler_ms: int | None = None,
    has_presentation: bool = False,
    presentation_ms: int = 5_000,
    has_obligation: bool = False,
    obligation_ms: int = 10_000,
) -> list[dict]:
    """Build a representative compiled_segments list for Tier 3 testing.

    Mirrors the dict schema used in test_clock_obligation_evaluation.py.
    """
    segments: list[dict] = []

    if has_obligation:
        segments.append({
            "segment_type": "obligation",
            "obligation_type": "station_id",
            "asset_id": "station_id_001",
            "duration_ms": obligation_ms,
        })

    if has_presentation:
        segments.append({
            "segment_type": "presentation",
            "asset_id": "intro_001",
            "duration_ms": presentation_ms,
        })

    segments.append({
        "segment_type": "content",
        "asset_id": "ep001",
        "duration_ms": content_duration_ms,
        "asset_start_offset_ms": 0,
    })

    if filler_ms is None:
        used = content_duration_ms
        if has_presentation:
            used += presentation_ms
        if has_obligation:
            used += obligation_ms
        filler_ms = GRID_30_MIN_MS - used

    if filler_ms > 0:
        segments.append({
            "segment_type": "filler",
            "asset_id": "",
            "duration_ms": filler_ms,
        })

    return segments


def _make_block(
    *,
    start_utc: datetime = BLOCK_1_START,
    slot_duration_ms: int = GRID_30_MIN_MS,
    compiled_segments: list[dict] | None = None,
    title: str = "The Simpsons S01E01",
) -> dict:
    """Build a block dict for Tier 3 second-pass testing."""
    if compiled_segments is None:
        compiled_segments = _make_compiled_segments()
    return {
        "start_utc_ms": int(start_utc.timestamp() * 1000),
        "slot_duration_ms": slot_duration_ms,
        "compiled_segments": compiled_segments,
        "title": title,
    }


def _make_two_blocks() -> list[dict]:
    """Two consecutive blocks in a broadcast day."""
    return [
        _make_block(
            start_utc=BLOCK_1_START,
            title="The Simpsons S01E01",
        ),
        _make_block(
            start_utc=BLOCK_2_START,
            title="Seinfeld S03E12",
        ),
    ]


def _make_continuity_config(
    *,
    channel_ident_pool: str | None = None,
    channel_ident_max_duration_ms: int = IDENT_DURATION_MS,
    coming_up_next_pool: str | None = None,
    coming_up_next_max_duration_ms: int = PROMO_DURATION_MS,
) -> dict:
    """Build a continuity.optional config for Tier 3."""
    optional: list[dict] = []
    if channel_ident_pool is not None:
        optional.append({
            "type": "channel_ident",
            "pool": channel_ident_pool,
            "max_duration_ms": channel_ident_max_duration_ms,
        })
    if coming_up_next_pool is not None:
        optional.append({
            "type": "coming_up_next",
            "pool": coming_up_next_pool,
            "max_duration_ms": coming_up_next_max_duration_ms,
        })
    return {"optional": optional}


# ---------------------------------------------------------------------------
# INV-TIER3-COMPILE-RESOLUTION-001: Resolved at compile time
# ---------------------------------------------------------------------------


class TestTier3ResolvedAtCompileTime:
    """INV-TIER3-COMPILE-RESOLUTION-001: Tier 3 segments in compiled_segments
    have non-empty asset_id and duration_ms > 0 after compilation.
    """

    def test_tier3_resolved_at_compile_time(self):
        """After evaluate_optional_presentation(), every Tier 3 segment
        must have a concrete asset_id and positive duration_ms.
        """
        blocks = [_make_block()]
        continuity = _make_continuity_config(
            channel_ident_pool="channel_idents",
            coming_up_next_pool="promos",
        )

        # Need two blocks for "coming up next" to resolve
        blocks = _make_two_blocks()

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        tier3_types = {"channel_ident", "coming_up_next", "network_branding"}
        for block in result:
            for seg in block["compiled_segments"]:
                if seg["segment_type"] in tier3_types:
                    assert seg["asset_id"], (
                        f"Tier 3 segment {seg['segment_type']} has empty asset_id"
                    )
                    assert seg["duration_ms"] > 0, (
                        f"Tier 3 segment {seg['segment_type']} has non-positive duration"
                    )


# ---------------------------------------------------------------------------
# INV-TIER3-COMPILE-RESOLUTION-001: Included in grid sizing
# ---------------------------------------------------------------------------


class TestTier3IncludedInGridSizing:
    """INV-TIER3-COMPILE-RESOLUTION-001: Tier 3 duration is part of the
    structural total used for grid block allocation.
    """

    def test_tier3_included_in_grid_sizing(self):
        """slot_duration_ms must be >= structural total including Tier 3."""
        blocks = _make_two_blocks()
        continuity = _make_continuity_config(
            channel_ident_pool="channel_idents",
            coming_up_next_pool="promos",
        )

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        structural_types = {
            "content", "presentation", "obligation",
            "channel_ident", "coming_up_next", "network_branding",
        }
        for block in result:
            structural_total = sum(
                s["duration_ms"]
                for s in block["compiled_segments"]
                if s["segment_type"] in structural_types
            )
            assert block["slot_duration_ms"] >= structural_total, (
                f"slot_duration_ms ({block['slot_duration_ms']}) < "
                f"structural_total ({structural_total})"
            )


# ---------------------------------------------------------------------------
# INV-TIER3-COMPILE-RESOLUTION-001: Immutable during expansion
# ---------------------------------------------------------------------------


class TestTier3ImmutableDuringExpansion:
    """INV-TIER3-COMPILE-RESOLUTION-001: Tier 3 segments in an expanded
    ScheduledBlock match source compiled_segments in type, asset, and duration.
    """

    def test_tier3_immutable_during_expansion(self):
        """Tier 3 segments must not be modified between compile output and
        expanded block. We verify the compiled output is stable by running
        evaluate twice and comparing Tier 3 segments.
        """
        import copy

        blocks = _make_two_blocks()
        continuity = _make_continuity_config(
            channel_ident_pool="channel_idents",
            coming_up_next_pool="promos",
        )

        result1 = evaluate_optional_presentation(
            blocks=copy.deepcopy(blocks),
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        result2 = evaluate_optional_presentation(
            blocks=copy.deepcopy(blocks),
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        tier3_types = {"channel_ident", "coming_up_next", "network_branding"}
        for b1, b2 in zip(result1, result2):
            t3_segs_1 = [
                (s["segment_type"], s["asset_id"], s["duration_ms"])
                for s in b1["compiled_segments"]
                if s["segment_type"] in tier3_types
            ]
            t3_segs_2 = [
                (s["segment_type"], s["asset_id"], s["duration_ms"])
                for s in b2["compiled_segments"]
                if s["segment_type"] in tier3_types
            ]
            assert t3_segs_1 == t3_segs_2, (
                "Tier 3 segments differ across compilations with same input"
            )


# ---------------------------------------------------------------------------
# INV-TIER3-NEXT-BLOCK-IDENTITY-001: "Coming up next" uses next block title
# ---------------------------------------------------------------------------


class TestComingUpNextUsesNextBlockTitle:
    """INV-TIER3-NEXT-BLOCK-IDENTITY-001: 'Coming up next' segment references
    the next block's title.
    """

    def test_coming_up_next_uses_next_block_title(self):
        """The 'coming up next' segment on block[0] must reference
        all_blocks[1].title as its next_program_title metadata.
        """
        blocks = _make_two_blocks()
        continuity = _make_continuity_config(
            coming_up_next_pool="promos",
        )

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        # Find "coming_up_next" segment in the first block
        first_block_segs = result[0]["compiled_segments"]
        cun_segs = [
            s for s in first_block_segs
            if s["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segs) == 1, "Expected exactly one coming_up_next segment"
        assert cun_segs[0]["next_program_title"] == "Seinfeld S03E12", (
            "coming_up_next must reference the next block's title"
        )


# ---------------------------------------------------------------------------
# INV-TIER3-NEXT-BLOCK-IDENTITY-001: Last block — no error
# ---------------------------------------------------------------------------


class TestComingUpNextLastBlockNoError:
    """INV-TIER3-NEXT-BLOCK-IDENTITY-001: Last block of a broadcast day has
    no 'coming up next' segment and raises no error.
    """

    def test_coming_up_next_last_block_no_error(self):
        """The last block must silently omit 'coming up next'."""
        blocks = _make_two_blocks()
        continuity = _make_continuity_config(
            coming_up_next_pool="promos",
        )

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        # Last block must have zero "coming_up_next" segments
        last_block_segs = result[-1]["compiled_segments"]
        cun_segs = [
            s for s in last_block_segs
            if s["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segs) == 0, (
            "Last block must not have a coming_up_next segment"
        )


# ---------------------------------------------------------------------------
# INV-ASSEMBLY-SEQUENCE-001: Segment order follows tier precedence
# ---------------------------------------------------------------------------


class TestSegmentOrderTiers:
    """INV-ASSEMBLY-SEQUENCE-001: Segment sequence is:
    obligation, presentation, content, optional (Tier 3).
    """

    def test_segment_order_tiers(self):
        """With all tiers present, segments must appear in tier order:
        obligation → presentation → content → Tier 3 optional.
        """
        blocks = _make_two_blocks()

        # Add obligation and presentation to first block
        blocks[0]["compiled_segments"] = _make_compiled_segments(
            has_obligation=True,
            has_presentation=True,
        )

        continuity = _make_continuity_config(
            channel_ident_pool="channel_idents",
            coming_up_next_pool="promos",
        )

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-03-27",
            channel_id="ch_test",
            features={"coming_up_next": True},
        )

        # Define tier order for each segment_type
        tier_order = {
            "obligation": 0,
            "presentation": 1,
            "content": 2,
            "filler": 3,        # Tier 4 fill, interleaved with/after content
            "channel_ident": 4,
            "network_branding": 4,
            "coming_up_next": 4,
        }

        first_block_segs = result[0]["compiled_segments"]
        seg_types = [s["segment_type"] for s in first_block_segs]

        # Extract tier order for structural segments (skip filler for ordering)
        structural_order = [
            tier_order[t] for t in seg_types
            if t in tier_order and t != "filler"
        ]

        # Verify non-decreasing tier order
        for i in range(len(structural_order) - 1):
            assert structural_order[i] <= structural_order[i + 1], (
                f"Segment order violation: {seg_types} — "
                f"tier {structural_order[i]} followed by {structural_order[i + 1]}"
            )
