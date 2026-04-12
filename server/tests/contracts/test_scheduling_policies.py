"""
Contract tests: Scheduling Policies -- INV-POLICY-*

Validates that the scheduling policy layer correctly enforces:
- Repeat window (same episode within N days blocked)
- Frequency cap (max N episodes per show per day)
- Tag eligibility (require/exclude tags by context)
- Duration gate (min/max duration per slot context)
- Purity (INV-POLICY-PURE-001)
- Idempotency (INV-POLICY-IDEMPOTENT-001)
- Layering (INV-POLICY-LAYERED-001)
- Structured violations (INV-POLICY-VIOLATION-STRUCTURED-001)

Contract: docs/contracts/scheduling_policies.md
Design reference: RETA-104 plan (Phase 4)
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

try:
    from retrovue.scheduling.policies import (
        DurationGateRule,
        FrequencyCapRule,
        PolicyViolation,
        RepeatWindowRule,
        SchedulingPolicy,
        TagEligibilityRule,
        evaluate_duration_gate,
        evaluate_frequency_cap,
        evaluate_repeat_window,
        evaluate_scheduling_policies,
        evaluate_tag_eligibility,
    )
except ImportError:
    pytest.skip(
        "retrovue.scheduling.policies not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Test input helpers (frozen-style plain objects for test isolation)
# ---------------------------------------------------------------------------


class _AssetStub:
    """Minimal asset stub for policy evaluation tests.

    Not a mock -- a plain value object carrying only the fields policies inspect.
    """

    __slots__ = (
        "asset_id",
        "show_id",
        "episode_id",
        "duration_ms",
        "tags",
        "state",
        "approved_for_broadcast",
    )

    def __init__(
        self,
        asset_id: str,
        *,
        show_id: str = "show-1",
        episode_id: str | None = None,
        duration_ms: int = 1_800_000,
        tags: frozenset[str] | None = None,
        state: str = "ready",
        approved_for_broadcast: bool = True,
    ):
        self.asset_id = asset_id
        self.show_id = show_id
        self.episode_id = episode_id or asset_id
        self.duration_ms = duration_ms
        self.tags = tags or frozenset()
        self.state = state
        self.approved_for_broadcast = approved_for_broadcast

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _AssetStub):
            return NotImplemented
        return self.asset_id == other.asset_id

    def __repr__(self) -> str:
        return f"_AssetStub({self.asset_id!r})"


class _PlayHistoryEntry:
    """A record of a past airing for repeat-window / frequency-cap checks."""

    __slots__ = ("asset_id", "show_id", "episode_id", "aired_date")

    def __init__(
        self,
        asset_id: str,
        *,
        show_id: str = "show-1",
        episode_id: str | None = None,
        aired_date: date | None = None,
    ):
        self.asset_id = asset_id
        self.show_id = show_id
        self.episode_id = episode_id or asset_id
        self.aired_date = aired_date or date(2026, 4, 9)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _PlayHistoryEntry):
            return NotImplemented
        return self.asset_id == other.asset_id and self.aired_date == other.aired_date

    def __repr__(self) -> str:
        return f"_PlayHistoryEntry({self.asset_id!r}, {self.aired_date})"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TODAY = date(2026, 4, 9)
SLOT_CONTEXT = "primetime"


# ===========================================================================
# RepeatWindowRule -- same episode within N days blocked
# ===========================================================================


class TestRepeatWindow:
    """Policy tests for repeat-window enforcement."""

    # Tier: 2 | Scheduling logic invariant
    def test_episode_within_window_blocked(self):
        """Episode aired 3 days ago blocked by 7-day repeat window."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 4, 6)),
        ]
        violations = evaluate_repeat_window(asset, rule, history, TODAY)
        assert len(violations) >= 1
        assert any(v.rule_type == "repeat_window" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_episode_outside_window_allowed(self):
        """Episode aired 10 days ago passes a 7-day repeat window."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 3, 30)),
        ]
        violations = evaluate_repeat_window(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_different_episode_same_show_not_blocked(self):
        """Different episode of same show is not blocked by repeat window."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep2", show_id="show-1", episode_id="ep2")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", episode_id="ep1", aired_date=date(2026, 4, 8)),
        ]
        violations = evaluate_repeat_window(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_episode_aired_exactly_on_boundary_allowed(self):
        """Episode aired exactly N days ago is outside the window (boundary inclusive)."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 4, 2)),  # exactly 7 days
        ]
        violations = evaluate_repeat_window(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_no_history_no_violation(self):
        """No play history means no repeat-window violation."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        violations = evaluate_repeat_window(asset, rule, [], TODAY)
        assert violations == []


# ===========================================================================
# FrequencyCapRule -- max N episodes per show per day
# ===========================================================================


class TestFrequencyCap:
    """Policy tests for frequency-cap enforcement."""

    # Tier: 2 | Scheduling logic invariant
    def test_show_at_daily_cap_blocked(self):
        """Show with 3 episodes today blocked when cap is 3."""
        rule = FrequencyCapRule(max_episodes_per_show=3)
        asset = _AssetStub("ep4", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep2", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep3", show_id="show-1", aired_date=TODAY),
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert len(violations) >= 1
        assert any(v.rule_type == "frequency_cap" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_show_below_cap_passes(self):
        """Show with 2 episodes today passes when cap is 3."""
        rule = FrequencyCapRule(max_episodes_per_show=3)
        asset = _AssetStub("ep3", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep2", show_id="show-1", aired_date=TODAY),
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_zero_cap_means_unlimited(self):
        """max_episodes_per_show=0 disables frequency cap entirely."""
        rule = FrequencyCapRule(max_episodes_per_show=0)
        asset = _AssetStub("ep100", show_id="show-1")
        history = [
            _PlayHistoryEntry(f"ep{i}", show_id="show-1", aired_date=TODAY)
            for i in range(50)
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_different_show_not_counted(self):
        """Episodes from a different show do not count toward this show's cap."""
        rule = FrequencyCapRule(max_episodes_per_show=1)
        asset = _AssetStub("ep1", show_id="show-2")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep2", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep3", show_id="show-1", aired_date=TODAY),
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_previous_day_not_counted(self):
        """Episodes from a previous day do not count toward today's cap."""
        rule = FrequencyCapRule(max_episodes_per_show=1)
        asset = _AssetStub("ep2", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=date(2026, 4, 8)),
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert violations == []


# ===========================================================================
# TagEligibilityRule -- require/exclude tags by context
# ===========================================================================


class TestTagEligibility:
    """Policy tests for tag-based eligibility enforcement."""

    # Tier: 2 | Scheduling logic invariant
    def test_require_tags_pass(self):
        """Asset with required tags passes."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset({"hd"}),
            exclude_tags=frozenset(),
        )
        asset = _AssetStub("a1", tags=frozenset({"hd", "drama"}))
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_require_tags_missing_blocked(self):
        """Asset missing required tags is blocked."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset({"hd"}),
            exclude_tags=frozenset(),
        )
        asset = _AssetStub("a1", tags=frozenset({"sd", "drama"}))
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert len(violations) >= 1
        assert any(v.rule_type == "tag_eligibility" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_tags_present_blocked(self):
        """Asset with excluded tags is blocked."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset(),
            exclude_tags=frozenset({"explicit"}),
        )
        asset = _AssetStub("a1", tags=frozenset({"hd", "explicit"}))
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert len(violations) >= 1
        assert any(v.rule_type == "tag_eligibility" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_tags_absent_passes(self):
        """Asset without excluded tags passes."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset(),
            exclude_tags=frozenset({"explicit"}),
        )
        asset = _AssetStub("a1", tags=frozenset({"hd", "drama"}))
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_context_mismatch_skips_rule(self):
        """Rule for a different context does not apply."""
        rule = TagEligibilityRule(
            context="late_night",
            require_tags=frozenset({"hd"}),
            exclude_tags=frozenset(),
        )
        asset = _AssetStub("a1", tags=frozenset())  # no hd tag
        violations = evaluate_tag_eligibility(asset, rule, "primetime")
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_require_tags_all_needed(self):
        """All required tags must be present, not just one."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset({"hd", "family"}),
            exclude_tags=frozenset(),
        )
        asset = _AssetStub("a1", tags=frozenset({"hd"}))  # missing "family"
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert len(violations) >= 1


# ===========================================================================
# DurationGateRule -- min/max duration per slot context
# ===========================================================================


class TestDurationGate:
    """Policy tests for duration-gate enforcement."""

    # Tier: 2 | Scheduling logic invariant
    def test_within_range_passes(self):
        """Asset duration within min/max passes."""
        rule = DurationGateRule(
            context="half_hour_slot",
            min_duration_sec=1200,
            max_duration_sec=1980,
        )
        asset = _AssetStub("a1", duration_ms=1_500_000)  # 1500s
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_too_short_blocked(self):
        """Asset shorter than min_duration is blocked."""
        rule = DurationGateRule(
            context="half_hour_slot",
            min_duration_sec=1200,
            max_duration_sec=1980,
        )
        asset = _AssetStub("a1", duration_ms=600_000)  # 600s < 1200s
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert len(violations) >= 1
        assert any(v.rule_type == "duration_gate" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_too_long_blocked(self):
        """Asset longer than max_duration is blocked."""
        rule = DurationGateRule(
            context="half_hour_slot",
            min_duration_sec=1200,
            max_duration_sec=1980,
        )
        asset = _AssetStub("a1", duration_ms=2_400_000)  # 2400s > 1980s
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert len(violations) >= 1
        assert any(v.rule_type == "duration_gate" for v in violations)

    # Tier: 2 | Scheduling logic invariant
    def test_context_mismatch_skips_rule(self):
        """Duration gate for a different context does not apply."""
        rule = DurationGateRule(
            context="hour_slot",
            min_duration_sec=3000,
            max_duration_sec=3600,
        )
        asset = _AssetStub("a1", duration_ms=600_000)  # way too short for hour_slot
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_exact_min_boundary_passes(self):
        """Asset at exactly min_duration passes."""
        rule = DurationGateRule(
            context="half_hour_slot",
            min_duration_sec=1200,
            max_duration_sec=1980,
        )
        asset = _AssetStub("a1", duration_ms=1_200_000)  # exactly 1200s
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_exact_max_boundary_passes(self):
        """Asset at exactly max_duration passes."""
        rule = DurationGateRule(
            context="half_hour_slot",
            min_duration_sec=1200,
            max_duration_sec=1980,
        )
        asset = _AssetStub("a1", duration_ms=1_980_000)  # exactly 1980s
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert violations == []


# ===========================================================================
# INV-POLICY-PURE-001 -- Purity: evaluation does not mutate inputs
# ===========================================================================


class TestPurity:
    """INV-POLICY-PURE-001: Policy evaluation must not mutate inputs."""

    # Tier: 2 | Scheduling logic invariant
    def test_repeat_window_inputs_not_mutated(self):
        """evaluate_repeat_window does not mutate asset or history."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 4, 8)),
        ]
        asset_copy = copy.deepcopy(asset)
        history_copy = copy.deepcopy(history)

        evaluate_repeat_window(asset, rule, history, TODAY)

        assert asset.asset_id == asset_copy.asset_id
        assert asset.episode_id == asset_copy.episode_id
        assert len(history) == len(history_copy)
        assert history[0].aired_date == history_copy[0].aired_date

    # Tier: 2 | Scheduling logic invariant
    def test_frequency_cap_inputs_not_mutated(self):
        """evaluate_frequency_cap does not mutate asset or history."""
        rule = FrequencyCapRule(max_episodes_per_show=3)
        asset = _AssetStub("ep1", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
        ]
        asset_copy = copy.deepcopy(asset)
        history_copy = copy.deepcopy(history)

        evaluate_frequency_cap(asset, rule, history, TODAY)

        assert asset.show_id == asset_copy.show_id
        assert len(history) == len(history_copy)

    # Tier: 2 | Scheduling logic invariant
    def test_tag_eligibility_inputs_not_mutated(self):
        """evaluate_tag_eligibility does not mutate asset."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset({"hd"}),
            exclude_tags=frozenset({"explicit"}),
        )
        asset = _AssetStub("a1", tags=frozenset({"hd", "drama"}))
        tags_before = asset.tags

        evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)

        assert asset.tags == tags_before

    # Tier: 2 | Scheduling logic invariant
    def test_orchestrator_inputs_not_mutated(self):
        """evaluate_scheduling_policies does not mutate any inputs."""
        policy = SchedulingPolicy(
            repeat_window=RepeatWindowRule(same_episode_days=7),
            frequency_cap=FrequencyCapRule(max_episodes_per_show=3),
            tag_eligibility=[
                TagEligibilityRule(
                    context="primetime",
                    require_tags=frozenset({"hd"}),
                    exclude_tags=frozenset(),
                ),
            ],
            duration_gate=[
                DurationGateRule(context="half_hour_slot", min_duration_sec=1200, max_duration_sec=1980),
            ],
        )
        asset = _AssetStub("ep1", tags=frozenset({"hd"}), duration_ms=1_500_000)
        history = [
            _PlayHistoryEntry("ep1", aired_date=date(2026, 4, 8)),
        ]

        asset_copy = copy.deepcopy(asset)
        history_copy = copy.deepcopy(history)

        evaluate_scheduling_policies(
            asset=asset,
            policy=policy,
            slot_context=SLOT_CONTEXT,
            play_history=history,
            broadcast_date=TODAY,
        )

        assert asset.asset_id == asset_copy.asset_id
        assert asset.tags == asset_copy.tags
        assert len(history) == len(history_copy)


# ===========================================================================
# INV-POLICY-IDEMPOTENT-001 -- Same inputs produce same violations
# ===========================================================================


class TestIdempotency:
    """INV-POLICY-IDEMPOTENT-001: Same inputs must produce same violations."""

    # Tier: 2 | Scheduling logic invariant
    def test_repeat_window_idempotent(self):
        """Two evaluations with identical inputs produce identical violations."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 4, 8)),
        ]
        v1 = evaluate_repeat_window(asset, rule, history, TODAY)
        v2 = evaluate_repeat_window(asset, rule, history, TODAY)
        assert len(v1) == len(v2)
        for a, b in zip(v1, v2):
            assert a.invariant_id == b.invariant_id
            assert a.rule_type == b.rule_type
            assert a.message == b.message

    # Tier: 2 | Scheduling logic invariant
    def test_orchestrator_idempotent(self):
        """Full policy evaluation is idempotent."""
        policy = SchedulingPolicy(
            repeat_window=RepeatWindowRule(same_episode_days=7),
            frequency_cap=FrequencyCapRule(max_episodes_per_show=3),
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep2", show_id="show-1", aired_date=TODAY),
            _PlayHistoryEntry("ep3", show_id="show-1", aired_date=TODAY),
        ]
        v1 = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=history, broadcast_date=TODAY,
        )
        v2 = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=history, broadcast_date=TODAY,
        )
        assert len(v1) == len(v2)
        for a, b in zip(v1, v2):
            assert a.invariant_id == b.invariant_id
            assert a.rule_type == b.rule_type


# ===========================================================================
# INV-POLICY-LAYERED-001 -- Policies cannot override LAW-ELIGIBILITY
# ===========================================================================


class TestLayering:
    """INV-POLICY-LAYERED-001: Policies add restrictions on top of LAW-ELIGIBILITY.

    An asset that is ineligible under LAW-ELIGIBILITY (state != ready OR
    approved_for_broadcast == false) must NOT be made eligible by policies.
    Policies can only add violations, never remove core ineligibility.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_ineligible_asset_not_made_eligible(self):
        """Asset with state != 'ready' remains ineligible regardless of policies."""
        policy = SchedulingPolicy(
            repeat_window=None,
            frequency_cap=None,
            tag_eligibility=[],
            duration_gate=[],
        )
        # Asset is NOT ready -- LAW-ELIGIBILITY says ineligible
        asset = _AssetStub("ep1", state="new", approved_for_broadcast=False)
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=[], broadcast_date=TODAY,
        )
        # Even with an empty policy (no policy rules to trigger), the asset
        # should still carry a violation because it fails LAW-ELIGIBILITY.
        # Policies layer on top -- they cannot produce an "eligible" result
        # for a LAW-ELIGIBILITY-ineligible asset.
        assert len(violations) >= 1
        assert any(
            v.invariant_id == "INV-POLICY-LAYERED-001" or "eligibility" in v.message.lower()
            for v in violations
        )

    # Tier: 2 | Scheduling logic invariant
    def test_unapproved_asset_not_made_eligible(self):
        """Asset with approved_for_broadcast=False remains ineligible."""
        policy = SchedulingPolicy(
            repeat_window=None,
            frequency_cap=None,
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1", state="ready", approved_for_broadcast=False)
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=[], broadcast_date=TODAY,
        )
        assert len(violations) >= 1

    # Tier: 2 | Scheduling logic invariant
    def test_eligible_asset_with_empty_policy_passes(self):
        """A LAW-ELIGIBILITY-eligible asset with no policy rules has no violations."""
        policy = SchedulingPolicy(
            repeat_window=None,
            frequency_cap=None,
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1", state="ready", approved_for_broadcast=True)
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=[], broadcast_date=TODAY,
        )
        assert violations == []


# ===========================================================================
# INV-POLICY-VIOLATION-STRUCTURED-001 -- Structured violation output
# ===========================================================================


class TestStructuredViolations:
    """INV-POLICY-VIOLATION-STRUCTURED-001: Every violation must carry
    invariant_id, rule_type, message, and details.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_repeat_window_violation_structure(self):
        """Repeat-window violation has all required fields."""
        rule = RepeatWindowRule(same_episode_days=7)
        asset = _AssetStub("ep1", episode_id="ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=date(2026, 4, 8)),
        ]
        violations = evaluate_repeat_window(asset, rule, history, TODAY)
        assert len(violations) >= 1
        v = violations[0]
        assert hasattr(v, "invariant_id") and isinstance(v.invariant_id, str) and len(v.invariant_id) > 0
        assert hasattr(v, "rule_type") and v.rule_type == "repeat_window"
        assert hasattr(v, "message") and isinstance(v.message, str) and len(v.message) > 0
        assert hasattr(v, "details") and isinstance(v.details, dict)

    # Tier: 2 | Scheduling logic invariant
    def test_frequency_cap_violation_structure(self):
        """Frequency-cap violation has all required fields."""
        rule = FrequencyCapRule(max_episodes_per_show=1)
        asset = _AssetStub("ep2", show_id="show-1")
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", aired_date=TODAY),
        ]
        violations = evaluate_frequency_cap(asset, rule, history, TODAY)
        assert len(violations) >= 1
        v = violations[0]
        assert hasattr(v, "invariant_id") and isinstance(v.invariant_id, str) and len(v.invariant_id) > 0
        assert hasattr(v, "rule_type") and v.rule_type == "frequency_cap"
        assert hasattr(v, "message") and isinstance(v.message, str) and len(v.message) > 0
        assert hasattr(v, "details") and isinstance(v.details, dict)

    # Tier: 2 | Scheduling logic invariant
    def test_tag_eligibility_violation_structure(self):
        """Tag-eligibility violation has all required fields."""
        rule = TagEligibilityRule(
            context="primetime",
            require_tags=frozenset({"hd"}),
            exclude_tags=frozenset(),
        )
        asset = _AssetStub("a1", tags=frozenset({"sd"}))
        violations = evaluate_tag_eligibility(asset, rule, SLOT_CONTEXT)
        assert len(violations) >= 1
        v = violations[0]
        assert hasattr(v, "invariant_id") and isinstance(v.invariant_id, str) and len(v.invariant_id) > 0
        assert hasattr(v, "rule_type") and v.rule_type == "tag_eligibility"
        assert hasattr(v, "message") and isinstance(v.message, str) and len(v.message) > 0
        assert hasattr(v, "details") and isinstance(v.details, dict)

    # Tier: 2 | Scheduling logic invariant
    def test_duration_gate_violation_structure(self):
        """Duration-gate violation has all required fields."""
        rule = DurationGateRule(context="half_hour_slot", min_duration_sec=1200, max_duration_sec=1980)
        asset = _AssetStub("a1", duration_ms=600_000)
        violations = evaluate_duration_gate(asset, rule, "half_hour_slot")
        assert len(violations) >= 1
        v = violations[0]
        assert hasattr(v, "invariant_id") and isinstance(v.invariant_id, str) and len(v.invariant_id) > 0
        assert hasattr(v, "rule_type") and v.rule_type == "duration_gate"
        assert hasattr(v, "message") and isinstance(v.message, str) and len(v.message) > 0
        assert hasattr(v, "details") and isinstance(v.details, dict)


# ===========================================================================
# Edge cases -- empty policy, no candidates, all filtered
# ===========================================================================


class TestEdgeCases:
    """Edge case coverage for scheduling policies."""

    # Tier: 2 | Scheduling logic invariant
    def test_empty_policy_no_violations(self):
        """A fully empty policy (no rules) produces no violations for eligible asset."""
        policy = SchedulingPolicy(
            repeat_window=None,
            frequency_cap=None,
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1", state="ready", approved_for_broadcast=True)
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=[], broadcast_date=TODAY,
        )
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_all_rules_trigger_multiple_violations(self):
        """Asset that violates every rule type produces violations from each."""
        policy = SchedulingPolicy(
            repeat_window=RepeatWindowRule(same_episode_days=7),
            frequency_cap=FrequencyCapRule(max_episodes_per_show=1),
            tag_eligibility=[
                TagEligibilityRule(
                    context="primetime",
                    require_tags=frozenset({"hd"}),
                    exclude_tags=frozenset(),
                ),
            ],
            duration_gate=[
                DurationGateRule(context="primetime", min_duration_sec=1200, max_duration_sec=1980),
            ],
        )
        # Asset: no hd tag, too short, recently aired, show at cap
        asset = _AssetStub(
            "ep1",
            show_id="show-1",
            episode_id="ep1",
            tags=frozenset(),
            duration_ms=300_000,  # 300s < 1200s min
        )
        history = [
            _PlayHistoryEntry("ep1", show_id="show-1", episode_id="ep1", aired_date=TODAY),
        ]
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context="primetime",
            play_history=history, broadcast_date=TODAY,
        )
        rule_types = {v.rule_type for v in violations}
        assert "repeat_window" in rule_types
        assert "frequency_cap" in rule_types
        assert "tag_eligibility" in rule_types
        assert "duration_gate" in rule_types

    # Tier: 2 | Scheduling logic invariant
    def test_empty_history_with_all_rules(self):
        """No history means repeat-window and frequency-cap cannot trigger."""
        policy = SchedulingPolicy(
            repeat_window=RepeatWindowRule(same_episode_days=7),
            frequency_cap=FrequencyCapRule(max_episodes_per_show=3),
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1", state="ready", approved_for_broadcast=True)
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=[], broadcast_date=TODAY,
        )
        assert violations == []

    # Tier: 2 | Scheduling logic invariant
    def test_none_rules_treated_as_disabled(self):
        """None for optional rules (repeat_window, frequency_cap) means rule is disabled."""
        policy = SchedulingPolicy(
            repeat_window=None,
            frequency_cap=None,
            tag_eligibility=[],
            duration_gate=[],
        )
        asset = _AssetStub("ep1")
        history = [
            _PlayHistoryEntry("ep1", episode_id="ep1", aired_date=TODAY),
        ]
        violations = evaluate_scheduling_policies(
            asset=asset, policy=policy, slot_context=SLOT_CONTEXT,
            play_history=history, broadcast_date=TODAY,
        )
        assert violations == []
