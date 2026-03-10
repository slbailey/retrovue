"""
Contract tests for BreakStructure (break_structure.md).

Validates the internal shape of commercial breaks: slot ordering,
budget conservation, interstitial slot guarantee, traffic scope,
determinism, and no-invent rule.

Station IDs are structural elements with fixed placement (after the
interstitial pool, before the from_break bumper). Bumpers are transition
elements framing the break. Neither bumpers nor station IDs are traffic
inventory.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.break_structure import (
    BreakSlot,
    BreakStructure,
    build_break_structure,
    BreakConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_CONFIG = BreakConfig(
    to_break_bumper_ms=3000,
    from_break_bumper_ms=3000,
    station_id_ms=5000,
)

NO_BUMPERS = BreakConfig(
    to_break_bumper_ms=0,
    from_break_bumper_ms=0,
    station_id_ms=5000,
)

NO_STATION_ID = BreakConfig(
    to_break_bumper_ms=3000,
    from_break_bumper_ms=3000,
    station_id_ms=0,
)

BARE_CONFIG = BreakConfig(
    to_break_bumper_ms=0,
    from_break_bumper_ms=0,
    station_id_ms=0,
)

# Canonical slot order
_CANONICAL_ORDER = ["to_break_bumper", "interstitial", "station_id", "from_break_bumper"]


def _slot_order_valid(slots: list[BreakSlot] | tuple[BreakSlot, ...]) -> bool:
    """Return True if slots follow canonical ordering."""
    last_idx = -1
    for slot in slots:
        idx = _CANONICAL_ORDER.index(slot.slot_type)
        # interstitial slots may repeat, all others must advance
        if slot.slot_type != "interstitial" and idx <= last_idx:
            return False
        if slot.slot_type == "interstitial" and idx < last_idx:
            return False
        last_idx = idx
    return True


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-ORDERED-001 — Slot ordering
# ---------------------------------------------------------------------------

class TestSlotOrdering:
    """Slots must follow canonical order."""

    # Tier: 1 | Structural invariant
    def test_slots_follow_canonical_order(self):
        """Full config produces correct sequence: bumper → interstitial → sid → bumper."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        assert len(structure.slots) > 0
        assert _slot_order_valid(structure.slots)

        types = [s.slot_type for s in structure.slots]
        assert types[0] == "to_break_bumper"
        assert types[-1] == "from_break_bumper"
        assert "interstitial" in types
        assert "station_id" in types

    # Tier: 1 | Structural invariant
    def test_station_id_after_interstitial_before_from_bumper(self):
        """Station ID appears after interstitial pool, before from_break bumper."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        types = [s.slot_type for s in structure.slots]
        interstitial_idx = types.index("interstitial")
        sid_idx = types.index("station_id")
        fb_idx = types.index("from_break_bumper")
        assert interstitial_idx < sid_idx < fb_idx

    # Tier: 1 | Structural invariant
    def test_no_bumpers_configured(self):
        """Without bumpers: interstitial + station_id only."""
        structure = build_break_structure(
            allocated_budget_ms=30000,
            config=NO_BUMPERS,
        )
        types = [s.slot_type for s in structure.slots]
        assert "to_break_bumper" not in types
        assert "from_break_bumper" not in types
        assert "interstitial" in types
        assert "station_id" in types
        assert _slot_order_valid(structure.slots)

    # Tier: 1 | Structural invariant
    def test_no_station_id_configured(self):
        """Without station_id: bumpers + interstitial only."""
        structure = build_break_structure(
            allocated_budget_ms=30000,
            config=NO_STATION_ID,
        )
        types = [s.slot_type for s in structure.slots]
        assert "station_id" not in types
        assert "interstitial" in types
        assert _slot_order_valid(structure.slots)

    # Tier: 1 | Structural invariant
    def test_bare_config(self):
        """No structural elements: single interstitial slot."""
        structure = build_break_structure(
            allocated_budget_ms=30000,
            config=BARE_CONFIG,
        )
        types = [s.slot_type for s in structure.slots]
        assert types == ["interstitial"]


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-BUDGET-EXACT-001 — Budget conservation
# ---------------------------------------------------------------------------

class TestBudgetExact:
    """Slot durations must sum to allocated budget."""

    # Tier: 1 | Structural invariant
    def test_slot_durations_sum_to_budget(self):
        """Full config budget is conserved."""
        budget = 60000
        structure = build_break_structure(
            allocated_budget_ms=budget,
            config=FULL_CONFIG,
        )
        total = sum(s.duration_ms for s in structure.slots)
        assert total == budget
        assert structure.total_duration_ms == budget

    # Tier: 1 | Structural invariant
    def test_zero_budget_empty_structure(self):
        """Zero budget produces no slots."""
        structure = build_break_structure(
            allocated_budget_ms=0,
            config=FULL_CONFIG,
        )
        assert len(structure.slots) == 0
        assert structure.total_duration_ms == 0

    # Tier: 1 | Structural invariant
    @pytest.mark.parametrize("budget", [5000, 10000, 15000, 30000, 90000, 120000])
    def test_various_budgets_conserved(self, budget: int):
        """Budget conservation holds across a range of allocations."""
        structure = build_break_structure(
            allocated_budget_ms=budget,
            config=FULL_CONFIG,
        )
        total = sum(s.duration_ms for s in structure.slots)
        assert total == budget

    # Tier: 1 | Structural invariant
    def test_bare_config_budget_conserved(self):
        """Budget conserved with no structural slots configured."""
        budget = 45000
        structure = build_break_structure(
            allocated_budget_ms=budget,
            config=BARE_CONFIG,
        )
        total = sum(s.duration_ms for s in structure.slots)
        assert total == budget


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 — Interstitial guarantee
# ---------------------------------------------------------------------------

class TestInterstitialRequired:
    """At least one interstitial slot must exist for positive budgets."""

    # Tier: 1 | Structural invariant
    def test_at_least_one_interstitial_slot(self):
        """Positive budget always has interstitial slot."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        interstitial_slots = [s for s in structure.slots if s.slot_type == "interstitial"]
        assert len(interstitial_slots) >= 1

    # Tier: 1 | Structural invariant
    def test_optional_slots_shed_before_interstitial(self):
        """Small budget sheds station_id then bumpers, keeps interstitial."""
        structure = build_break_structure(
            allocated_budget_ms=2000,
            config=FULL_CONFIG,
        )
        interstitial_slots = [s for s in structure.slots if s.slot_type == "interstitial"]
        assert len(interstitial_slots) >= 1

    # Tier: 1 | Structural invariant
    def test_budget_too_small_for_structure(self):
        """Tiny budget degenerates to single interstitial."""
        structure = build_break_structure(
            allocated_budget_ms=500,
            config=FULL_CONFIG,
        )
        assert len(structure.slots) == 1
        assert structure.slots[0].slot_type == "interstitial"
        assert structure.slots[0].duration_ms == 500

    # Tier: 1 | Structural invariant
    def test_station_id_shed_before_bumpers(self):
        """Station ID is shed before bumpers when budget is tight."""
        # Budget = 7000, structural = 3000+3000+5000 = 11000
        # Shed station_id first → 3000+3000 = 6000, pool = 1000
        structure = build_break_structure(
            allocated_budget_ms=7000,
            config=FULL_CONFIG,
        )
        types = [s.slot_type for s in structure.slots]
        assert "station_id" not in types
        assert "interstitial" in types
        interstitial_slots = [s for s in structure.slots if s.slot_type == "interstitial"]
        assert interstitial_slots[0].duration_ms > 0


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 — Traffic fills only interstitial
# ---------------------------------------------------------------------------

class TestTrafficScope:
    """Traffic manager fills only interstitial slots."""

    # Tier: 1 | Structural invariant
    def test_traffic_fills_only_interstitial_slots(self):
        """Non-interstitial slots have non-traffic fill rules."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        for slot in structure.slots:
            if slot.slot_type == "interstitial":
                assert slot.fill_rule == "traffic"
            elif slot.slot_type in ("to_break_bumper", "from_break_bumper"):
                assert slot.fill_rule == "bumper"
            elif slot.slot_type == "station_id":
                assert slot.fill_rule == "station_id"

    # Tier: 1 | Structural invariant
    def test_fill_rules_match_slot_types(self):
        """Every slot type maps to the correct fill rule across configs."""
        for config in [FULL_CONFIG, NO_BUMPERS, NO_STATION_ID, BARE_CONFIG]:
            structure = build_break_structure(
                allocated_budget_ms=60000,
                config=config,
            )
            for slot in structure.slots:
                if slot.slot_type == "interstitial":
                    assert slot.fill_rule == "traffic"
                elif slot.slot_type in ("to_break_bumper", "from_break_bumper"):
                    assert slot.fill_rule == "bumper"
                elif slot.slot_type == "station_id":
                    assert slot.fill_rule == "station_id"

    # Tier: 1 | Structural invariant
    def test_bumpers_and_station_ids_not_traffic(self):
        """Bumpers and station IDs must never have fill_rule='traffic'."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        for slot in structure.slots:
            if slot.slot_type in ("to_break_bumper", "from_break_bumper", "station_id"):
                assert slot.fill_rule != "traffic"


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-DETERMINISTIC-001 — Deterministic output
# ---------------------------------------------------------------------------

class TestDeterministic:
    """Same inputs must produce identical structure."""

    # Tier: 1 | Structural invariant
    def test_deterministic_output(self):
        """Repeated calls produce identical results."""
        results = [
            build_break_structure(
                allocated_budget_ms=60000,
                config=FULL_CONFIG,
            )
            for _ in range(10)
        ]
        first = results[0]
        for r in results[1:]:
            assert len(r.slots) == len(first.slots)
            for a, b in zip(first.slots, r.slots):
                assert a.slot_type == b.slot_type
                assert a.duration_ms == b.duration_ms
                assert a.fill_rule == b.fill_rule


# ---------------------------------------------------------------------------
# INV-BREAKSTRUCTURE-NO-INVENT-001 — No invented breaks
# ---------------------------------------------------------------------------

class TestNoInvent:
    """BreakStructure must not create breaks beyond BreakPlan."""

    # Tier: 1 | Structural invariant
    def test_no_invented_breaks(self):
        """build_break_structure structures a single break, not more."""
        structure = build_break_structure(
            allocated_budget_ms=60000,
            config=FULL_CONFIG,
        )
        assert structure.total_duration_ms == 60000

    # Tier: 1 | Structural invariant
    def test_zero_budget_no_slots(self):
        """Zero-duration opportunity produces no structure at all."""
        structure = build_break_structure(
            allocated_budget_ms=0,
            config=FULL_CONFIG,
        )
        assert len(structure.slots) == 0
        assert structure.total_duration_ms == 0
