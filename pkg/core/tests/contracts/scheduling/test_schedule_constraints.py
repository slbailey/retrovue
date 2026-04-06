"""
Contract tests for the schedule constraints engine.

Constraint families:
    - Blackout constraints (date/time exclusion windows)
    - Adjacency constraints (back-to-back content rules)
    - Content restriction constraints (rating/classification gates)

Invariants tested:
    - INV-CONSTRAINT-BLACKOUT-001: blackout exclusion windows
    - INV-CONSTRAINT-ADJACENCY-001: adjacency content restrictions
    - INV-CONSTRAINT-CONTENT-RESTRICTION-001: content time-window restrictions
    - INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001: evaluation idempotency
"""

from dataclasses import dataclass
from datetime import date, time, timezone, datetime
from typing import Any

import pytest

from retrovue.scheduling.schedule_constraints import (
    BlackoutConstraint,
    AdjacencyConstraint,
    ContentRestrictionConstraint,
    ConstraintViolation,
    check_blackout_constraints,
    check_adjacency_constraints,
    check_content_restriction_constraints,
)


# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

BROADCAST_DAY = date(2026, 4, 6)  # Monday
PROGRAMMING_DAY_START = time(6, 0)


# ---------------------------------------------------------------------------
# Stub zone for blackout tests
# ---------------------------------------------------------------------------

@dataclass
class StubZone:
    """Minimal zone-like object for constraint tests."""

    name: str
    start_time: time
    end_time: time
    day_filters: list[str] | None
    enabled: bool
    schedulable_assets: list[str] | None = None


# ===========================================================================
# Tier 1 — Structural invariants (data types)
# ===========================================================================


class TestConstraintDataTypes:
    """Tier 1: Structural validation of constraint data types."""

    def test_blackout_constraint_frozen(self) -> None:
        bc = BlackoutConstraint(
            asset_ids=frozenset({"asset-1"}),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="seasonal blackout",
        )
        with pytest.raises(AttributeError):
            bc.reason = "changed"  # type: ignore[misc]

    def test_adjacency_constraint_frozen(self) -> None:
        ac = AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )
        with pytest.raises(AttributeError):
            ac.direction = "a_before_b"  # type: ignore[misc]

    def test_adjacency_constraint_rejects_invalid_direction(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            AdjacencyConstraint(
                classification_a="horror",
                classification_b="children",
                direction="invalid",
                reason="test",
            )

    def test_content_restriction_constraint_frozen(self) -> None:
        cr = ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=None,
            reason="watershed",
        )
        with pytest.raises(AttributeError):
            cr.classification = "changed"  # type: ignore[misc]

    def test_constraint_violation_frozen(self) -> None:
        cv = ConstraintViolation(
            invariant_id="INV-TEST-001",
            constraint_type="test",
            message="test violation",
            details={"key": "value"},
        )
        with pytest.raises(AttributeError):
            cv.message = "changed"  # type: ignore[misc]

    def test_blackout_constraint_empty_asset_ids_means_all(self) -> None:
        """Empty asset_ids frozenset is valid — means all assets blocked."""
        bc = BlackoutConstraint(
            asset_ids=frozenset(),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="total blackout",
        )
        assert len(bc.asset_ids) == 0


# ===========================================================================
# Tier 2 — Blackout constraint logic (INV-CONSTRAINT-BLACKOUT-001)
# ===========================================================================


@pytest.mark.contract
class TestInvConstraintBlackout001:
    """INV-CONSTRAINT-BLACKOUT-001: Blackout exclusion windows."""

    def test_asset_in_blackout_window_rejected(self) -> None:
        """Asset matching blackout window on matching day produces violation."""
        zones = [StubZone(
            name="prime",
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            enabled=True,
            schedulable_assets=["asset-christmas"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-christmas"}),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="not December",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 1
        assert violations[0].invariant_id == "INV-CONSTRAINT-BLACKOUT-001-VIOLATED"
        assert violations[0].constraint_type == "blackout"
        assert "asset-christmas" in violations[0].message

    def test_asset_outside_blackout_date_range_passes(self) -> None:
        """Asset outside blackout date range produces no violation."""
        zones = [StubZone(
            name="prime",
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            enabled=True,
            schedulable_assets=["asset-christmas"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-christmas"}),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="Q1 only",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_asset_on_non_matching_day_filter_passes(self) -> None:
        """Blackout with day filter not matching broadcast day passes."""
        zones = [StubZone(
            name="prime",
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            enabled=True,
            schedulable_assets=["asset-1"],
        )]
        # BROADCAST_DAY is Monday; blackout only on weekends
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-1"}),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=frozenset({"SAT", "SUN"}),
            reason="weekends only",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_non_overlapping_time_windows_pass(self) -> None:
        """Zone and blackout with non-overlapping time windows produce no violation."""
        zones = [StubZone(
            name="morning",
            start_time=time(8, 0),
            end_time=time(10, 0),
            day_filters=None,
            enabled=True,
            schedulable_assets=["asset-1"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-1"}),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(20, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="evening blackout",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_empty_asset_ids_blocks_all_zone_assets(self) -> None:
        """Blackout with empty asset_ids blocks all assets in matching zones."""
        zones = [StubZone(
            name="prime",
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            enabled=True,
            schedulable_assets=["asset-a", "asset-b"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset(),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            reason="total blackout",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 2  # both assets

    def test_disabled_zone_ignored(self) -> None:
        """Disabled zones are not checked against constraints."""
        zones = [StubZone(
            name="disabled",
            start_time=time(20, 0),
            end_time=time(22, 0),
            day_filters=None,
            enabled=False,
            schedulable_assets=["asset-1"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-1"}),
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            start_time=time(0, 0),
            end_time=time(23, 59, 59, 999999),
            day_filters=None,
            reason="test",
        )]
        violations = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_no_constraints_returns_empty(self) -> None:
        zones = [StubZone(
            name="prime", start_time=time(20, 0), end_time=time(22, 0),
            day_filters=None, enabled=True, schedulable_assets=["asset-1"],
        )]
        violations = check_blackout_constraints(
            zones, [], BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert violations == []


# ===========================================================================
# Tier 2 — Adjacency constraint logic (INV-CONSTRAINT-ADJACENCY-001)
# ===========================================================================


@pytest.mark.contract
class TestInvConstraintAdjacency001:
    """INV-CONSTRAINT-ADJACENCY-001: Adjacency content restrictions."""

    def test_symmetric_adjacency_violation(self) -> None:
        """Symmetric constraint catches both orderings."""
        blocks = [("blk-1", "horror"), ("blk-2", "children")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 1
        assert violations[0].invariant_id == "INV-CONSTRAINT-ADJACENCY-001-VIOLATED"

    def test_symmetric_adjacency_reverse_order(self) -> None:
        """Symmetric constraint catches reverse ordering."""
        blocks = [("blk-1", "children"), ("blk-2", "horror")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 1

    def test_directional_adjacency_a_before_b_violated(self) -> None:
        """Directional constraint catches A followed by B."""
        blocks = [("blk-1", "horror"), ("blk-2", "children")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="a_before_b",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 1

    def test_directional_adjacency_b_before_a_passes(self) -> None:
        """Directional constraint allows B followed by A."""
        blocks = [("blk-1", "children"), ("blk-2", "horror")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="a_before_b",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 0

    def test_non_adjacent_blocks_pass(self) -> None:
        """Non-adjacent matching classifications produce no violation."""
        blocks = [("blk-1", "horror"), ("blk-2", "drama"), ("blk-3", "children")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 0

    def test_non_matching_classifications_pass(self) -> None:
        """Classifications not matching constraint produce no violation."""
        blocks = [("blk-1", "drama"), ("blk-2", "comedy")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 0

    def test_single_block_passes(self) -> None:
        """A schedule with one block cannot have adjacency violations."""
        blocks = [("blk-1", "horror")]
        constraints = [AdjacencyConstraint(
            classification_a="horror",
            classification_b="children",
            direction="both",
            reason="content policy",
        )]
        violations = check_adjacency_constraints(blocks, constraints)
        assert len(violations) == 0

    def test_no_constraints_returns_empty(self) -> None:
        blocks = [("blk-1", "horror"), ("blk-2", "children")]
        violations = check_adjacency_constraints(blocks, [])
        assert violations == []


# ===========================================================================
# Tier 2 — Content restriction logic (INV-CONSTRAINT-CONTENT-RESTRICTION-001)
# ===========================================================================


@pytest.mark.contract
class TestInvConstraintContentRestriction001:
    """INV-CONSTRAINT-CONTENT-RESTRICTION-001: Content time-window restrictions."""

    def _make_start_utc_ms(self, hour: int, minute: int = 0) -> int:
        """Create a UTC timestamp in ms for the given hour on BROADCAST_DAY."""
        dt = datetime(2026, 4, 6, hour, minute, 0, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def test_restricted_content_outside_window_rejected(self) -> None:
        """Mature content at 14:00 rejected when window is 21:00-06:00."""
        blocks = [("blk-1", "mature", self._make_start_utc_ms(14, 0))]
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=None,
            reason="watershed",
        )]
        violations = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 1
        assert violations[0].invariant_id == "INV-CONSTRAINT-CONTENT-RESTRICTION-001-VIOLATED"
        assert violations[0].constraint_type == "content_restriction"

    def test_restricted_content_within_window_passes(self) -> None:
        """Mature content at 22:00 passes when window is 21:00-06:00."""
        blocks = [("blk-1", "mature", self._make_start_utc_ms(22, 0))]
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=None,
            reason="watershed",
        )]
        violations = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_non_matching_classification_passes(self) -> None:
        """Content with different classification passes restriction check."""
        blocks = [("blk-1", "family", self._make_start_utc_ms(14, 0))]
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=None,
            reason="watershed",
        )]
        violations = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_day_filter_non_matching_passes(self) -> None:
        """Restriction on weekends only; Monday broadcast passes."""
        blocks = [("blk-1", "mature", self._make_start_utc_ms(14, 0))]
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=frozenset({"SAT", "SUN"}),
            reason="weekend watershed",
        )]
        violations = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert len(violations) == 0

    def test_no_constraints_returns_empty(self) -> None:
        blocks = [("blk-1", "mature", self._make_start_utc_ms(14, 0))]
        violations = check_content_restriction_constraints(
            blocks, [], BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert violations == []

    def test_empty_blocks_returns_empty(self) -> None:
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0),
            allowed_end_time=time(6, 0),
            day_filters=None,
            reason="watershed",
        )]
        violations = check_content_restriction_constraints(
            [], constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert violations == []


# ===========================================================================
# Tier 2 — Idempotency (INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001)
# ===========================================================================


@pytest.mark.contract
class TestInvConstraintEvaluationIdempotent001:
    """INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001: Evaluation idempotency."""

    def _make_start_utc_ms(self, hour: int, minute: int = 0) -> int:
        dt = datetime(2026, 4, 6, hour, minute, 0, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def test_blackout_evaluation_idempotent(self) -> None:
        """Blackout check returns identical results on repeated calls."""
        zones = [StubZone(
            name="prime", start_time=time(20, 0), end_time=time(22, 0),
            day_filters=None, enabled=True, schedulable_assets=["asset-1"],
        )]
        constraints = [BlackoutConstraint(
            asset_ids=frozenset({"asset-1"}),
            start_date=date(2026, 4, 1), end_date=date(2026, 4, 30),
            start_time=time(20, 0), end_time=time(22, 0),
            day_filters=None, reason="test",
        )]
        result1 = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        result2 = check_blackout_constraints(
            zones, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert result1 == result2

    def test_adjacency_evaluation_idempotent(self) -> None:
        """Adjacency check returns identical results on repeated calls."""
        blocks = [("blk-1", "horror"), ("blk-2", "children")]
        constraints = [AdjacencyConstraint(
            classification_a="horror", classification_b="children",
            direction="both", reason="test",
        )]
        result1 = check_adjacency_constraints(blocks, constraints)
        result2 = check_adjacency_constraints(blocks, constraints)
        assert result1 == result2

    def test_content_restriction_evaluation_idempotent(self) -> None:
        """Content restriction check returns identical results on repeated calls."""
        blocks = [("blk-1", "mature", self._make_start_utc_ms(14, 0))]
        constraints = [ContentRestrictionConstraint(
            classification="mature",
            allowed_start_time=time(21, 0), allowed_end_time=time(6, 0),
            day_filters=None, reason="test",
        )]
        result1 = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        result2 = check_content_restriction_constraints(
            blocks, constraints, BROADCAST_DAY, PROGRAMMING_DAY_START,
        )
        assert result1 == result2
