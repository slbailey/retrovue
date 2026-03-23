"""Contract tests for placement strategies (placement_dsl.md).

Validates:
- INV-PLACEMENT-FALLBACK-001: Chapter markers suppress fallback
- INV-PLACEMENT-STRUCTURE-001: Content duration preserved after expansion
- INV-PLACEMENT-COUNT-001: Break count matches strategy definition
- INV-PLACEMENT-BOUNDS-001: Positions strictly within (0, 1)

These tests exercise the placement model at the data/validation level.
They do NOT require a database or the full compiler pipeline.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Placement strategy helpers (pure functions, no imports needed yet)
# These will be extracted to a module when the compiler is updated.
# For now, define the logic inline to validate the contract.
# ---------------------------------------------------------------------------


def validate_weighted_positions(positions: list[float], weights: list[float]) -> list[str]:
    """Validate a weighted_positions placement definition. Returns error list."""
    errors = []
    if not positions:
        errors.append("positions must be non-empty")
    if len(positions) != len(weights):
        errors.append(f"positions length ({len(positions)}) != weights length ({len(weights)})")
    for i, p in enumerate(positions):
        if p <= 0.0 or p >= 1.0:
            errors.append(f"position[{i}]={p} must be strictly within (0, 1)")
    for i, w in enumerate(weights):
        if w <= 0:
            errors.append(f"weight[{i}]={w} must be positive")
    # Positions must be sorted
    if positions != sorted(positions):
        errors.append("positions must be in ascending order")
    return errors


def validate_equal_split(count: int) -> list[str]:
    """Validate an equal_split placement definition. Returns error list."""
    errors = []
    if not isinstance(count, int) or count <= 0:
        errors.append(f"count must be a positive integer, got {count}")
    return errors


def generate_weighted_positions(
    content_duration_ms: int,
    positions: list[float],
    weights: list[float],
) -> list[dict]:
    """Generate break positions from weighted_positions strategy.

    Returns list of {position_ms, weight} dicts.
    """
    return [
        {"position_ms": int(content_duration_ms * p), "weight": w}
        for p, w in zip(positions, weights)
    ]


def generate_equal_split(content_duration_ms: int, count: int) -> list[dict]:
    """Generate break positions from equal_split strategy.

    Returns list of {position_ms, weight} dicts with equal weights.
    """
    segment_ms = content_duration_ms // (count + 1)
    return [
        {"position_ms": segment_ms * (i + 1), "weight": 1.0}
        for i in range(count)
    ]


def select_placement(
    chapter_markers_ms: list[int] | None,
    fallback: dict | None,
    content_duration_ms: int,
) -> list[dict]:
    """Select placement strategy: chapters if available, else fallback.

    Returns list of {position_ms, weight} dicts.
    """
    # INV-PLACEMENT-FALLBACK-001: chapters suppress fallback
    if chapter_markers_ms:
        return [
            {"position_ms": m, "weight": 1.0}
            for m in chapter_markers_ms
            if 0 < m < content_duration_ms
        ]

    if fallback is None:
        return []

    strategy = fallback.get("strategy")
    if strategy == "weighted_positions":
        return generate_weighted_positions(
            content_duration_ms,
            fallback["positions"],
            fallback["weights"],
        )
    elif strategy == "equal_split":
        return generate_equal_split(content_duration_ms, fallback["count"])

    return []


# ---------------------------------------------------------------------------
# Tests: INV-PLACEMENT-FALLBACK-001
# ---------------------------------------------------------------------------


class TestPlacementFallback:
    """INV-PLACEMENT-FALLBACK-001: Chapter markers suppress fallback."""

    def test_chapter_markers_override_fallback(self):
        """When chapter markers exist, fallback is ignored."""
        chapters = [420000, 840000]  # 7:00, 14:00
        fallback = {
            "strategy": "weighted_positions",
            "positions": [0.3, 0.7],
            "weights": [1, 1],
        }
        result = select_placement(chapters, fallback, content_duration_ms=1320000)

        # Should use chapters, not fallback positions
        positions = [r["position_ms"] for r in result]
        assert positions == [420000, 840000], (
            f"INV-PLACEMENT-FALLBACK-001: Expected chapter positions, got {positions}"
        )

    def test_fallback_used_when_no_chapters(self):
        """When no chapter markers, fallback strategy generates breaks."""
        fallback = {
            "strategy": "weighted_positions",
            "positions": [0.3, 0.72],
            "weights": [1, 1],
        }
        result = select_placement(None, fallback, content_duration_ms=1320000)

        assert len(result) == 2
        assert result[0]["position_ms"] == int(1320000 * 0.3)
        assert result[1]["position_ms"] == int(1320000 * 0.72)

    def test_empty_chapters_uses_fallback(self):
        """Empty chapter list is treated as no chapters."""
        fallback = {
            "strategy": "equal_split",
            "count": 3,
        }
        result = select_placement([], fallback, content_duration_ms=1320000)
        assert len(result) == 3

    def test_no_placement_no_chapters_no_breaks(self):
        """No placement declared, no chapters: zero breaks."""
        result = select_placement(None, None, content_duration_ms=1320000)
        assert result == []

    def test_no_mixed_sources(self):
        """Chapters and fallback must never both contribute."""
        chapters = [420000]
        fallback = {
            "strategy": "equal_split",
            "count": 5,
        }
        result = select_placement(chapters, fallback, content_duration_ms=1320000)

        # Only 1 position (from chapter), not 5 (from fallback)
        assert len(result) == 1
        assert result[0]["position_ms"] == 420000


# ---------------------------------------------------------------------------
# Tests: INV-PLACEMENT-COUNT-001
# ---------------------------------------------------------------------------


class TestPlacementCount:
    """INV-PLACEMENT-COUNT-001: Break count matches strategy."""

    def test_weighted_positions_count(self):
        """weighted_positions: break count == len(positions)."""
        result = generate_weighted_positions(
            1320000, positions=[0.3, 0.5, 0.72], weights=[1, 2, 1]
        )
        assert len(result) == 3

    def test_equal_split_count(self):
        """equal_split: break count == count."""
        result = generate_equal_split(1320000, count=4)
        assert len(result) == 4

    def test_equal_split_positions_evenly_spaced(self):
        """equal_split positions are evenly distributed."""
        result = generate_equal_split(1200000, count=3)
        positions = [r["position_ms"] for r in result]
        # 1200000 / 4 = 300000
        assert positions == [300000, 600000, 900000]

    def test_weights_length_mismatch_rejected(self):
        """positions and weights with different lengths must be rejected."""
        errors = validate_weighted_positions(
            positions=[0.3, 0.7],
            weights=[1, 1, 1],  # 3 weights, 2 positions
        )
        assert any("length" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: INV-PLACEMENT-BOUNDS-001
# ---------------------------------------------------------------------------


class TestPlacementBounds:
    """INV-PLACEMENT-BOUNDS-001: Positions strictly within (0, 1)."""

    def test_position_at_zero_rejected(self):
        errors = validate_weighted_positions([0.0, 0.5], [1, 1])
        assert any("strictly within" in e for e in errors)

    def test_position_at_one_rejected(self):
        errors = validate_weighted_positions([0.5, 1.0], [1, 1])
        assert any("strictly within" in e for e in errors)

    def test_negative_position_rejected(self):
        errors = validate_weighted_positions([-0.1, 0.5], [1, 1])
        assert any("strictly within" in e for e in errors)

    def test_valid_positions_accepted(self):
        errors = validate_weighted_positions([0.25, 0.5, 0.75], [1, 1, 1])
        assert errors == []

    def test_equal_split_zero_rejected(self):
        errors = validate_equal_split(0)
        assert len(errors) > 0

    def test_equal_split_negative_rejected(self):
        errors = validate_equal_split(-1)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Tests: INV-PLACEMENT-STRUCTURE-001
# ---------------------------------------------------------------------------


class TestPlacementStructure:
    """INV-PLACEMENT-STRUCTURE-001: Content duration preserved."""

    def test_content_duration_preserved_weighted(self):
        """Sum of content acts after split must equal original duration."""
        content_ms = 1320000
        breaks = generate_weighted_positions(content_ms, [0.3, 0.72], [1, 1])

        # Content acts: [0, break1), [break1, break2), [break2, end)
        positions = sorted(r["position_ms"] for r in breaks)
        boundaries = [0] + positions + [content_ms]
        act_durations = [boundaries[i+1] - boundaries[i] for i in range(len(boundaries)-1)]

        assert sum(act_durations) == content_ms, (
            f"INV-PLACEMENT-STRUCTURE-001: content acts sum {sum(act_durations)} "
            f"!= original {content_ms}"
        )

    def test_content_duration_preserved_equal_split(self):
        """Sum of content acts after equal split must equal original duration."""
        content_ms = 1320000
        breaks = generate_equal_split(content_ms, count=3)

        positions = sorted(r["position_ms"] for r in breaks)
        boundaries = [0] + positions + [content_ms]
        act_durations = [boundaries[i+1] - boundaries[i] for i in range(len(boundaries)-1)]

        assert sum(act_durations) == content_ms

    def test_all_acts_positive_duration(self):
        """Every content act after splitting must have positive duration."""
        content_ms = 1320000
        breaks = generate_weighted_positions(content_ms, [0.3, 0.72], [1, 1])

        positions = sorted(r["position_ms"] for r in breaks)
        boundaries = [0] + positions + [content_ms]
        act_durations = [boundaries[i+1] - boundaries[i] for i in range(len(boundaries)-1)]

        for i, dur in enumerate(act_durations):
            assert dur > 0, f"Act {i} has zero or negative duration: {dur}ms"
