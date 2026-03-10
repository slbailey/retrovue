"""
Contract tests: Traffic Policy — INV-TRAFFIC-*

Validates that the traffic policy layer correctly enforces:
- Allowed type filtering (INV-TRAFFIC-ALLOWED-TYPE-001)
- Cooldown enforcement (INV-TRAFFIC-COOLDOWN-001)
- Daily cap enforcement (INV-TRAFFIC-DAILY-CAP-001)
- Deterministic rotation (INV-TRAFFIC-ROTATION-001)
- Filter evaluation order (INV-TRAFFIC-FILTER-ORDER-001)
- Purity (INV-TRAFFIC-PURE-001)
- Empty input handling (INV-TRAFFIC-EMPTY-001)
- No eligible asset (INV-TRAFFIC-NONE-001)

Contract: docs/contracts/traffic_policy.md
"""

from __future__ import annotations

import copy

import pytest

try:
    from retrovue.runtime.traffic_policy import (
        PlayRecord,
        TrafficCandidate,
        TrafficPolicy,
        evaluate_candidates,
        select_next,
    )
except ImportError:
    pytest.skip(
        "retrovue.runtime.traffic_policy not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _policy(**overrides) -> TrafficPolicy:
    defaults = dict(
        allowed_types=["commercial", "promo", "filler"],
        default_cooldown_seconds=3_600,
        type_cooldowns_seconds={},
        max_plays_per_day=0,
    )
    defaults.update(overrides)
    return TrafficPolicy(**defaults)


def _candidate(asset_id: str, asset_type: str = "commercial", duration_ms: int = 30_000) -> TrafficCandidate:
    return TrafficCandidate(asset_id=asset_id, asset_type=asset_type, duration_ms=duration_ms)


def _play(asset_id: str, played_at_ms: int, asset_type: str = "commercial") -> PlayRecord:
    return PlayRecord(asset_id=asset_id, asset_type=asset_type, played_at_ms=played_at_ms)


NOW_MS = 10_000_000_000  # arbitrary "now"
DAY_START_MS = 9_900_000_000  # arbitrary channel traffic day start


# ===========================================================================
# INV-TRAFFIC-ALLOWED-TYPE-001 — Allowed type filtering
# ===========================================================================


class TestAllowedTypeFiltering:
    """TRAFFIC-001..004: Candidates filtered by allowed_types."""

    # Tier: 2 | Scheduling logic invariant
    def test_disallowed_type_excluded(self):
        """TRAFFIC-001: Candidate with disallowed type is excluded."""
        policy = _policy(allowed_types=["promo"])
        candidates = [_candidate("ad1", asset_type="commercial")]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert result == []

    # Tier: 2 | Scheduling logic invariant
    def test_allowed_type_passes(self):
        """TRAFFIC-002: Candidate with allowed type passes."""
        policy = _policy(allowed_types=["commercial"])
        candidates = [_candidate("ad1", asset_type="commercial")]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert len(result) == 1
        assert result[0].asset_id == "ad1"

    # Tier: 2 | Scheduling logic invariant
    def test_empty_allowed_types_excludes_all(self):
        """TRAFFIC-003: Empty allowed_types excludes all candidates."""
        policy = _policy(allowed_types=[])
        candidates = [
            _candidate("ad1", asset_type="commercial"),
            _candidate("ad2", asset_type="promo"),
        ]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert result == []

    # Tier: 2 | Scheduling logic invariant
    def test_mixed_types_only_allowed_survive(self):
        """TRAFFIC-004: Only candidates with allowed types survive."""
        policy = _policy(allowed_types=["promo"])
        candidates = [
            _candidate("ad1", asset_type="commercial"),
            _candidate("promo1", asset_type="promo"),
            _candidate("ad2", asset_type="commercial"),
            _candidate("promo2", asset_type="promo"),
        ]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["promo1", "promo2"]


# ===========================================================================
# INV-TRAFFIC-COOLDOWN-001 — Cooldown enforcement
# ===========================================================================


class TestCooldownEnforcement:
    """TRAFFIC-005..009: Cooldown blocks recently played assets."""

    # Tier: 2 | Scheduling logic invariant
    def test_asset_within_cooldown_excluded(self):
        """TRAFFIC-005: Asset played within default cooldown is excluded."""
        policy = _policy(default_cooldown_seconds=3_600)
        history = [_play("ad1", played_at_ms=NOW_MS - 1_800_000)]  # 30min ago
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result == []

    # Tier: 2 | Scheduling logic invariant
    def test_asset_outside_cooldown_passes(self):
        """TRAFFIC-006: Asset played outside cooldown window passes."""
        policy = _policy(default_cooldown_seconds=3_600)
        history = [_play("ad1", played_at_ms=NOW_MS - 4_000_000)]  # >1hr ago
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1
        assert result[0].asset_id == "ad1"

    # Tier: 2 | Scheduling logic invariant
    def test_type_cooldown_overrides_default(self):
        """TRAFFIC-007: Type-specific cooldown overrides default cooldown."""
        policy = _policy(
            default_cooldown_seconds=3_600,
            type_cooldowns_seconds={"promo": 600},  # 10min for promos
        )
        # Promo played 15min ago: outside 10min type cooldown -> passes
        history = [_play("promo1", played_at_ms=NOW_MS - 900_000, asset_type="promo")]
        candidates = [_candidate("promo1", asset_type="promo")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_zero_cooldown_skips_filter(self):
        """TRAFFIC-008: Zero default cooldown with no type overrides skips cooldown."""
        policy = _policy(default_cooldown_seconds=0, type_cooldowns_seconds={})
        history = [_play("ad1", played_at_ms=NOW_MS - 1_000)]  # 1s ago
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_type_cooldown_only_applies_to_that_type(self):
        """TRAFFIC-028: Type cooldown does not bleed to other types."""
        policy = _policy(
            default_cooldown_seconds=3_600,
            type_cooldowns_seconds={"promo": 600},
        )
        history = [
            _play("promo1", played_at_ms=NOW_MS - 900_000, asset_type="promo"),
            _play("ad1", played_at_ms=NOW_MS - 900_000, asset_type="commercial"),
        ]
        candidates = [
            _candidate("promo1", asset_type="promo"),
            _candidate("ad1", asset_type="commercial"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        ids = [c.asset_id for c in result]
        assert "promo1" in ids
        assert "ad1" not in ids

    # Tier: 2 | Scheduling logic invariant
    def test_most_recent_play_determines_cooldown(self):
        """TRAFFIC-009: Multiple plays — most recent determines cooldown."""
        policy = _policy(default_cooldown_seconds=3_600)
        history = [
            _play("ad1", played_at_ms=NOW_MS - 7_200_000),  # 2hr ago
            _play("ad1", played_at_ms=NOW_MS - 1_800_000),  # 30min ago (most recent)
        ]
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result == []


# ===========================================================================
# INV-TRAFFIC-DAILY-CAP-001 — Daily play cap enforcement
# ===========================================================================


class TestDailyCapEnforcement:
    """TRAFFIC-010..013: Daily cap limits per-asset plays per channel traffic day."""

    # Tier: 2 | Scheduling logic invariant
    def test_asset_at_cap_excluded(self):
        """TRAFFIC-010: Asset at daily cap is excluded."""
        policy = _policy(max_plays_per_day=3)
        history = [
            _play("ad1", played_at_ms=DAY_START_MS + 1_000),
            _play("ad1", played_at_ms=DAY_START_MS + 2_000),
            _play("ad1", played_at_ms=DAY_START_MS + 3_000),
        ]
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result == []

    # Tier: 2 | Scheduling logic invariant
    def test_asset_below_cap_passes(self):
        """TRAFFIC-011: Asset below daily cap passes."""
        policy = _policy(max_plays_per_day=3)
        history = [
            _play("ad1", played_at_ms=DAY_START_MS + 1_000),
            _play("ad1", played_at_ms=DAY_START_MS + 2_000),
        ]
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_zero_cap_disables_enforcement(self):
        """TRAFFIC-012: max_plays_per_day=0 disables cap entirely."""
        policy = _policy(max_plays_per_day=0)
        history = [_play("ad1", played_at_ms=DAY_START_MS + i * 1000) for i in range(100)]
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1

    # Tier: 2 | Scheduling logic invariant
    def test_plays_before_day_start_not_counted(self):
        """TRAFFIC-013: Plays before day_start_ms are not counted toward cap."""
        policy = _policy(max_plays_per_day=2)
        history = [
            _play("ad1", played_at_ms=DAY_START_MS - 100_000),  # previous day
            _play("ad1", played_at_ms=DAY_START_MS - 50_000),   # previous day
            _play("ad1", played_at_ms=DAY_START_MS + 1_000),    # today (1 play)
        ]
        candidates = [_candidate("ad1")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 1


# ===========================================================================
# INV-TRAFFIC-ROTATION-001 — Deterministic round-robin rotation
# ===========================================================================


class TestRotation:
    """TRAFFIC-014..016, TRAFFIC-021, TRAFFIC-023..024: Deterministic rotation."""

    # Tier: 2 | Scheduling logic invariant
    def test_least_recently_played_first(self):
        """TRAFFIC-014: Least-recently-played candidate selected first."""
        policy = _policy(default_cooldown_seconds=0)
        history = [
            _play("ad1", played_at_ms=NOW_MS - 5_000),    # most recent
            _play("ad2", played_at_ms=NOW_MS - 100_000),  # oldest
            _play("ad3", played_at_ms=NOW_MS - 50_000),   # middle
        ]
        candidates = [_candidate("ad1"), _candidate("ad2"), _candidate("ad3")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["ad2", "ad3", "ad1"]

    # Tier: 2 | Scheduling logic invariant
    def test_never_played_preferred(self):
        """TRAFFIC-015: Never-played candidates preferred over played."""
        policy = _policy(default_cooldown_seconds=0)
        history = [_play("ad1", played_at_ms=NOW_MS - 100_000)]
        candidates = [_candidate("ad1"), _candidate("ad2")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result[0].asset_id == "ad2"

    # Tier: 2 | Scheduling logic invariant
    def test_equal_history_sorted_by_asset_id(self):
        """TRAFFIC-016: Equal play history — sorted by asset_id lexical order."""
        policy = _policy(default_cooldown_seconds=0)
        ts = NOW_MS - 100_000
        history = [
            _play("cc", played_at_ms=ts),
            _play("aa", played_at_ms=ts),
            _play("bb", played_at_ms=ts),
        ]
        # Input order is deliberately NOT sorted by asset_id
        candidates = [_candidate("cc"), _candidate("aa"), _candidate("bb")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["aa", "bb", "cc"]

    # Tier: 2 | Scheduling logic invariant
    def test_round_robin_across_selections(self):
        """TRAFFIC-021: Three rounds of select_next produce round-robin."""
        policy = _policy(default_cooldown_seconds=0)
        candidates = [_candidate("ad1"), _candidate("ad2"), _candidate("ad3")]
        history: list[PlayRecord] = []

        picks: list[str] = []
        for i in range(3):
            pick = select_next(candidates, policy, history, NOW_MS + i, DAY_START_MS)
            assert pick is not None
            picks.append(pick.asset_id)
            history.append(_play(pick.asset_id, played_at_ms=NOW_MS + i))

        # All three distinct assets selected
        assert len(set(picks)) == 3

    # Tier: 2 | Scheduling logic invariant
    def test_different_candidate_order_same_result(self):
        """TRAFFIC-023: Different candidate input order produces same output order."""
        policy = _policy(default_cooldown_seconds=0)
        history = [
            _play("ad1", played_at_ms=NOW_MS - 5_000),
            _play("ad2", played_at_ms=NOW_MS - 100_000),
            _play("ad3", played_at_ms=NOW_MS - 50_000),
        ]

        order_a = [_candidate("ad1"), _candidate("ad2"), _candidate("ad3")]
        order_b = [_candidate("ad3"), _candidate("ad1"), _candidate("ad2")]
        order_c = [_candidate("ad2"), _candidate("ad3"), _candidate("ad1")]

        result_a = evaluate_candidates(order_a, policy, history, NOW_MS, DAY_START_MS)
        result_b = evaluate_candidates(order_b, policy, history, NOW_MS, DAY_START_MS)
        result_c = evaluate_candidates(order_c, policy, history, NOW_MS, DAY_START_MS)

        ids_a = [c.asset_id for c in result_a]
        ids_b = [c.asset_id for c in result_b]
        ids_c = [c.asset_id for c in result_c]

        assert ids_a == ids_b == ids_c

    # Tier: 2 | Scheduling logic invariant
    def test_no_history_sorted_by_asset_id(self):
        """TRAFFIC-024: No play history — candidates sorted by asset_id."""
        policy = _policy(default_cooldown_seconds=0)
        candidates = [_candidate("zz"), _candidate("aa"), _candidate("mm")]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["aa", "mm", "zz"]


# ===========================================================================
# INV-TRAFFIC-FILTER-ORDER-001 — Filter evaluation order
# ===========================================================================


class TestFilterOrder:
    """TRAFFIC-017: Type filter applied before cooldown."""

    # Tier: 2 | Scheduling logic invariant
    def test_mixed_filter_exclusions(self):
        """TRAFFIC-029: Each candidate excluded by a different filter; only clean one survives."""
        policy = _policy(
            allowed_types=["commercial"],
            default_cooldown_seconds=3_600,
            max_plays_per_day=1,
        )
        history = [
            _play("ad1", played_at_ms=NOW_MS - 100_000),    # cooldown
            _play("ad3", played_at_ms=DAY_START_MS + 100),   # cap
        ]
        candidates = [
            _candidate("ad1"),                                # excluded: cooldown
            _candidate("ad2", asset_type="promo"),            # excluded: wrong type
            _candidate("ad3"),                                # excluded: daily cap
            _candidate("ad4"),                                # passes all
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["ad4"]

    # Tier: 2 | Scheduling logic invariant
    def test_type_filter_before_cooldown(self):
        """TRAFFIC-017: Asset with wrong type never reaches cooldown check."""
        policy = _policy(
            allowed_types=["promo"],
            default_cooldown_seconds=0,
        )
        # commercial type is not allowed — excluded by type filter
        # even though cooldown is 0 (would pass cooldown)
        candidates = [_candidate("ad1", asset_type="commercial")]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert result == []


# ===========================================================================
# INV-TRAFFIC-PURE-001 — Purity
# ===========================================================================


class TestPurity:
    """TRAFFIC-018: evaluate_candidates does not mutate inputs."""

    # Tier: 2 | Scheduling logic invariant
    def test_inputs_not_mutated(self):
        """TRAFFIC-018: Original candidates and history are unchanged after evaluation."""
        policy = _policy(default_cooldown_seconds=0)
        candidates = [_candidate("ad1"), _candidate("ad2"), _candidate("ad3")]
        history = [_play("ad2", played_at_ms=NOW_MS - 100_000)]

        candidates_copy = copy.deepcopy(candidates)
        history_copy = copy.deepcopy(history)

        evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)

        assert candidates == candidates_copy
        assert history == history_copy


# ===========================================================================
# INV-TRAFFIC-EMPTY-001 — Empty inputs
# ===========================================================================


class TestEmptyInputs:
    """TRAFFIC-019..020: Empty candidates and empty history handling."""

    # Tier: 2 | Scheduling logic invariant
    def test_empty_candidates_returns_empty(self):
        """TRAFFIC-019: Empty candidates -> empty result."""
        policy = _policy()
        result = evaluate_candidates([], policy, [], NOW_MS, DAY_START_MS)
        assert result == []

    # Tier: 2 | Scheduling logic invariant
    def test_select_next_empty_returns_none(self):
        """TRAFFIC-019: select_next with empty candidates -> None."""
        policy = _policy()
        result = select_next([], policy, [], NOW_MS, DAY_START_MS)
        assert result is None

    # Tier: 2 | Scheduling logic invariant
    def test_duplicate_candidates_handled(self):
        """TRAFFIC-030: Duplicate candidate IDs are preserved, not deduped."""
        policy = _policy(default_cooldown_seconds=0)
        candidates = [
            _candidate("ad1"),
            _candidate("ad1"),
            _candidate("ad2"),
        ]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        ids = [c.asset_id for c in result]
        assert ids.count("ad1") == 2

    # Tier: 2 | Scheduling logic invariant
    def test_empty_history_all_pass(self):
        """TRAFFIC-020: Empty play_history — all candidates pass cooldown and cap."""
        policy = _policy(default_cooldown_seconds=3_600, max_plays_per_day=5)
        candidates = [_candidate("ad1"), _candidate("ad2"), _candidate("ad3")]
        result = evaluate_candidates(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert len(result) == 3


# ===========================================================================
# INV-TRAFFIC-NONE-001 — No eligible asset
# ===========================================================================


class TestNoEligibleAsset:
    """TRAFFIC-025..026: select_next returns None when no candidates pass."""

    # Tier: 2 | Scheduling logic invariant
    def test_all_excluded_by_type_returns_none(self):
        """TRAFFIC-025: All excluded by type -> select_next returns None."""
        policy = _policy(allowed_types=["promo"])
        candidates = [
            _candidate("ad1", asset_type="commercial"),
            _candidate("ad2", asset_type="commercial"),
        ]
        result = select_next(candidates, policy, [], NOW_MS, DAY_START_MS)
        assert result is None

    # Tier: 2 | Scheduling logic invariant
    def test_all_excluded_by_cooldown_returns_none(self):
        """TRAFFIC-026: All in cooldown -> select_next returns None."""
        policy = _policy(default_cooldown_seconds=3_600)
        history = [
            _play("ad1", played_at_ms=NOW_MS - 100_000),
            _play("ad2", played_at_ms=NOW_MS - 200_000),
        ]
        candidates = [_candidate("ad1"), _candidate("ad2")]
        result = select_next(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result is None

    # Tier: 2 | Scheduling logic invariant
    def test_all_excluded_by_cap_returns_none(self):
        """All at daily cap -> select_next returns None."""
        policy = _policy(max_plays_per_day=1, default_cooldown_seconds=0)
        history = [
            _play("ad1", played_at_ms=DAY_START_MS + 1_000),
            _play("ad2", played_at_ms=DAY_START_MS + 2_000),
        ]
        candidates = [_candidate("ad1"), _candidate("ad2")]
        result = select_next(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result is None


# ===========================================================================
# INV-TRAFFIC-GROUP-COOLDOWN-001 — Group-aware cooldown key
# ===========================================================================


class TestGroupCooldown:
    """Cooldown key is cooldown_group when present, asset_id otherwise.

    cooldown_group is derived from filenames at ingest and flows through
    the data model internally. No user-facing config references it.
    """

    def test_group_member_played_cools_entire_group(self):
        """Playing Die Hard (1) cools Die Hard (2) for the same cooldown."""
        policy = _policy(allowed_types=["commercial", "promo", "filler", "trailer"], default_cooldown_seconds=3_600)
        history = [
            PlayRecord(asset_id="diehard-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 1_000_000, cooldown_group="Die Hard"),
        ]
        candidates = [
            TrafficCandidate(asset_id="diehard-1", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
            TrafficCandidate(asset_id="diehard-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert result == []

    def test_group_cooldown_expired_admits_all_members(self):
        """After cooldown expires, all group members are eligible again."""
        policy = _policy(allowed_types=["commercial", "promo", "filler", "trailer"], default_cooldown_seconds=3_600)
        history = [
            PlayRecord(asset_id="diehard-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 3_600_001, cooldown_group="Die Hard"),
        ]
        candidates = [
            TrafficCandidate(asset_id="diehard-1", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
            TrafficCandidate(asset_id="diehard-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert len(result) == 2

    def test_ungrouped_asset_uses_asset_id_as_key(self):
        """Asset without cooldown_group still uses asset_id for cooldown."""
        policy = _policy(default_cooldown_seconds=3_600)
        history = [_play("solo-trailer", played_at_ms=NOW_MS - 1_000_000)]
        candidates = [_candidate("solo-trailer"), _candidate("other-trailer")]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["other-trailer"]

    def test_different_groups_independent(self):
        """Playing a Die Hard trailer does not cool Alien trailers."""
        policy = _policy(allowed_types=["commercial", "promo", "filler", "trailer"], default_cooldown_seconds=3_600)
        history = [
            PlayRecord(asset_id="diehard-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 1_000_000, cooldown_group="Die Hard"),
        ]
        candidates = [
            TrafficCandidate(asset_id="diehard-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
            TrafficCandidate(asset_id="alien-1", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Alien"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["alien-1"]

    def test_grouped_and_ungrouped_coexist(self):
        """Grouped and ungrouped candidates evaluated correctly together."""
        policy = _policy(allowed_types=["commercial", "promo", "filler", "trailer"], default_cooldown_seconds=3_600)
        history = [
            PlayRecord(asset_id="diehard-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 1_000_000, cooldown_group="Die Hard"),
            _play("solo", played_at_ms=NOW_MS - 1_000_000),
        ]
        candidates = [
            TrafficCandidate(asset_id="diehard-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
            _candidate("solo"),
            _candidate("fresh"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        assert [c.asset_id for c in result] == ["fresh"]

    def test_rotation_sort_uses_group_key(self):
        """Rotation sort (least-recently-played first) uses group key."""
        policy = _policy(allowed_types=["commercial", "promo", "filler", "trailer"], default_cooldown_seconds=0)
        history = [
            PlayRecord(asset_id="alien-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 5000, cooldown_group="Alien"),
            PlayRecord(asset_id="diehard-1", asset_type="trailer",
                       played_at_ms=NOW_MS - 2000, cooldown_group="Die Hard"),
        ]
        candidates = [
            TrafficCandidate(asset_id="diehard-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Die Hard"),
            TrafficCandidate(asset_id="alien-2", asset_type="trailer",
                             duration_ms=30_000, cooldown_group="Alien"),
        ]
        result = evaluate_candidates(candidates, policy, history, NOW_MS, DAY_START_MS)
        # Alien played longer ago -> sorts first
        assert result[0].asset_id == "alien-2"
        assert result[1].asset_id == "diehard-2"
