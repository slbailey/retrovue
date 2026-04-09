"""
Integration tests: DSL → Scheduling Policy → Schedule Compilation.

Validates the end-to-end flow from policy declarations in DSL YAML
through compilation, verifying:
- Policy parsing from YAML into SchedulingPolicy objects
- Policy evaluation during compilation (asset filtering)
- Backward compatibility (no policies key = unchanged behavior)
- Violation reporting in compilation output

Contract: docs/contracts/scheduling_policies.md
Task: RETA-108 (Phase 4 Step 4)
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone as tz_mod

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata
from retrovue.dev.stub_asset_resolver import StubAssetResolver
from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.schedule_compiler import (
    compile_schedule,
    parse_dsl,
    resolve_scheduling_policy,
)
from retrovue.scheduling.policies import (
    DurationGateRule,
    FrequencyCapRule,
    RepeatWindowRule,
    SchedulingPolicy,
    TagEligibilityRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver() -> StubAssetResolver:
    """Build a resolver with tagged assets for policy testing."""
    r = StubAssetResolver()
    r.add("col.shows.drama_hd", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.ep.drama_hd_01", "asset.ep.drama_hd_02"),
    ))
    r.register_collection("col.shows.drama_hd", [
        "asset.ep.drama_hd_01", "asset.ep.drama_hd_02",
    ])
    r.add("asset.ep.drama_hd_01", AssetMetadata(
        type="episode", duration_sec=1320, rating="PG",
        tags=("hd", "drama"),
    ))
    r.add("asset.ep.drama_hd_02", AssetMetadata(
        type="episode", duration_sec=1320, rating="PG",
        tags=("hd", "drama"),
    ))

    r.add("col.shows.comedy_sd", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.ep.comedy_sd_01",),
    ))
    r.register_collection("col.shows.comedy_sd", [
        "asset.ep.comedy_sd_01",
    ])
    r.add("asset.ep.comedy_sd_01", AssetMetadata(
        type="episode", duration_sec=1320, rating="PG",
        tags=("sd", "comedy"),
    ))

    r.add("col.shows.short_filler", AssetMetadata(
        type="collection", duration_sec=0,
        tags=("asset.ep.short_01",),
    ))
    r.register_collection("col.shows.short_filler", [
        "asset.ep.short_01",
    ])
    r.add("asset.ep.short_01", AssetMetadata(
        type="episode", duration_sec=300, rating="G",
        tags=("filler",),
    ))
    return r


def _base_dsl() -> dict:
    """Minimal DSL with programs and schedule, no policies."""
    return {
        "channel": "test_policy_ch",
        "broadcast_day": "2026-04-09",
        "timezone": "UTC",
        "pools": {
            "drama_hd": {"match": {"type": "episode", "collection": "col.shows.drama_hd"}},
            "comedy_sd": {"match": {"type": "episode", "collection": "col.shows.comedy_sd"}},
            "short_filler": {"match": {"type": "episode", "collection": "col.shows.short_filler"}},
        },
        "programs": {
            "p_drama": {"pool": "drama_hd", "grid_blocks": 1, "fill_mode": "single"},
            "p_comedy": {"pool": "comedy_sd", "grid_blocks": 1, "fill_mode": "single"},
            "p_short": {"pool": "short_filler", "grid_blocks": 1, "fill_mode": "single"},
        },
        "schedule": {
            "all_day": [
                {"start": "20:00", "slots": 1, "program": "p_drama", "progression": "sequential"},
                {"start": "20:30", "slots": 1, "program": "p_comedy", "progression": "sequential"},
            ],
        },
    }


# ===========================================================================
# resolve_scheduling_policy — YAML → SchedulingPolicy
# ===========================================================================


class TestResolveSchedulingPolicy:
    """Tests for DSL policies: key → SchedulingPolicy parsing."""

    def test_no_policies_returns_none(self):
        """DSL without policies: key returns None."""
        dsl = _base_dsl()
        assert resolve_scheduling_policy(dsl) is None

    def test_empty_policies_returns_none(self):
        """DSL with empty policies: {} returns None."""
        dsl = _base_dsl()
        dsl["policies"] = {}
        assert resolve_scheduling_policy(dsl) is None

    def test_repeat_window_parsed(self):
        """policies.repeat_window is parsed into RepeatWindowRule."""
        dsl = _base_dsl()
        dsl["policies"] = {"repeat_window": {"same_episode_days": 14}}
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert isinstance(policy.repeat_window, RepeatWindowRule)
        assert policy.repeat_window.same_episode_days == 14

    def test_frequency_cap_parsed(self):
        """policies.frequency_cap.per_day is parsed into FrequencyCapRule."""
        dsl = _base_dsl()
        dsl["policies"] = {
            "frequency_cap": {"per_day": {"max_episodes_per_show": 5}},
        }
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert isinstance(policy.frequency_cap, FrequencyCapRule)
        assert policy.frequency_cap.max_episodes_per_show == 5

    def test_tag_eligibility_parsed(self):
        """policies.tag_eligibility list is parsed into TagEligibilityRule objects."""
        dsl = _base_dsl()
        dsl["policies"] = {
            "tag_eligibility": [
                {
                    "context": "primetime",
                    "require_tags": ["hd"],
                    "exclude_tags": ["explicit"],
                },
            ],
        }
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert len(policy.tag_eligibility) == 1
        rule = policy.tag_eligibility[0]
        assert isinstance(rule, TagEligibilityRule)
        assert rule.context == "primetime"
        assert rule.require_tags == frozenset({"hd"})
        assert rule.exclude_tags == frozenset({"explicit"})

    def test_duration_gate_parsed(self):
        """policies.duration_gate list is parsed into DurationGateRule objects."""
        dsl = _base_dsl()
        dsl["policies"] = {
            "duration_gate": [
                {"context": "half_hour_slot", "min_duration_sec": 1200, "max_duration_sec": 1980},
            ],
        }
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert len(policy.duration_gate) == 1
        rule = policy.duration_gate[0]
        assert isinstance(rule, DurationGateRule)
        assert rule.min_duration_sec == 1200
        assert rule.max_duration_sec == 1980

    def test_full_policy_parsed(self):
        """All four rule types parsed together into a single SchedulingPolicy."""
        dsl = _base_dsl()
        dsl["policies"] = {
            "repeat_window": {"same_episode_days": 7},
            "frequency_cap": {"per_day": {"max_episodes_per_show": 3}},
            "tag_eligibility": [
                {"context": "primetime", "require_tags": ["hd"], "exclude_tags": []},
            ],
            "duration_gate": [
                {"context": "half_hour_slot", "min_duration_sec": 1200, "max_duration_sec": 1980},
            ],
        }
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert policy.repeat_window is not None
        assert policy.frequency_cap is not None
        assert len(policy.tag_eligibility) == 1
        assert len(policy.duration_gate) == 1

    def test_policy_object_is_frozen(self):
        """Resolved SchedulingPolicy is frozen (immutable)."""
        dsl = _base_dsl()
        dsl["policies"] = {"repeat_window": {"same_episode_days": 7}}
        policy = resolve_scheduling_policy(dsl)
        with pytest.raises(AttributeError):
            policy.repeat_window = None  # type: ignore[misc]


# ===========================================================================
# Backward compatibility — no policies key
# ===========================================================================


class TestBackwardCompatibility:
    """DSL files without policies: key compile unchanged."""

    def test_no_policies_compiles_normally(self):
        """Existing DSL without policies still compiles successfully."""
        dsl = _base_dsl()
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        assert plan["version"] == "program-schedule.v2"
        assert len(plan["program_blocks"]) == 2
        assert "policy_violations" not in plan

    def test_empty_policies_compiles_normally(self):
        """DSL with empty policies: {} compiles as if no policies."""
        dsl = _base_dsl()
        dsl["policies"] = {}
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
        assert len(plan["program_blocks"]) == 2
        assert "policy_violations" not in plan


# ===========================================================================
# Policy evaluation during compilation
# ===========================================================================


class TestPolicyCompilationIntegration:
    """Policies evaluated during compilation filter blocks and report violations."""

    def test_tag_eligibility_filters_blocks(self):
        """Blocks with assets missing required tags are filtered out."""
        dsl = _base_dsl()
        # Require 'hd' tag in 'single' context (matches fill_mode)
        dsl["policies"] = {
            "tag_eligibility": [
                {"context": "single", "require_tags": ["hd"], "exclude_tags": []},
            ],
        }
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        # drama_hd has 'hd' tag → passes
        # comedy_sd has 'sd' tag only → filtered out
        assert len(plan["program_blocks"]) == 1
        assert plan["program_blocks"][0]["collection"] == "drama_hd"

        # Violations reported
        assert "policy_violations" in plan
        violations = plan["policy_violations"]
        assert len(violations) >= 1
        assert any(v["rule_type"] == "tag_eligibility" for v in violations)

    def test_duration_gate_filters_short_assets(self):
        """Assets shorter than min_duration are filtered out."""
        dsl = _base_dsl()
        # Replace comedy slot with short_filler
        dsl["schedule"]["all_day"][1] = {
            "start": "20:30", "slots": 1,
            "program": "p_short", "progression": "sequential",
        }
        dsl["policies"] = {
            "duration_gate": [
                {"context": "single", "min_duration_sec": 600, "max_duration_sec": 0},
            ],
        }
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        # drama_hd (1320s) passes, short_filler (300s) filtered
        assert len(plan["program_blocks"]) == 1
        assert "policy_violations" in plan
        assert any(v["rule_type"] == "duration_gate" for v in plan["policy_violations"])

    def test_passing_policy_no_violations(self):
        """Assets that pass all policy rules produce no violations."""
        dsl = _base_dsl()
        # Policy that all drama_hd and comedy_sd assets pass
        dsl["policies"] = {
            "duration_gate": [
                {"context": "single", "min_duration_sec": 60, "max_duration_sec": 3600},
            ],
        }
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        assert len(plan["program_blocks"]) == 2
        assert "policy_violations" not in plan

    def test_violations_carry_structured_fields(self):
        """Each violation in output has invariant_id, rule_type, message, details."""
        dsl = _base_dsl()
        dsl["policies"] = {
            "tag_eligibility": [
                {"context": "single", "require_tags": ["nonexistent_tag"], "exclude_tags": []},
            ],
        }
        resolver = _make_resolver()
        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        assert "policy_violations" in plan
        for v in plan["policy_violations"]:
            assert "invariant_id" in v and len(v["invariant_id"]) > 0
            assert "rule_type" in v and v["rule_type"] == "tag_eligibility"
            assert "message" in v and len(v["message"]) > 0
            assert "details" in v and isinstance(v["details"], dict)


# ===========================================================================
# YAML round-trip: parse_dsl + resolve_scheduling_policy
# ===========================================================================


class TestYamlRoundTrip:
    """Verify policies survive YAML parsing."""

    def test_policies_parsed_from_yaml_text(self):
        """Full YAML text with policies: key parses correctly."""
        yaml_text = """\
channel: test_rt
broadcast_day: "2026-04-09"
timezone: UTC

pools:
  drama:
    match:
      type: episode

programs:
  p_drama:
    pool: drama
    grid_blocks: 1
    fill_mode: single

policies:
  repeat_window:
    same_episode_days: 7
  frequency_cap:
    per_day:
      max_episodes_per_show: 3
  tag_eligibility:
    - context: "primetime"
      require_tags: ["hd"]
      exclude_tags: ["explicit"]
  duration_gate:
    - context: "half_hour_slot"
      min_duration_sec: 1200
      max_duration_sec: 1980

schedule:
  all_day:
    - start: "20:00"
      slots: 1
      program: p_drama
      progression: sequential
"""
        dsl = parse_dsl(yaml_text)
        policy = resolve_scheduling_policy(dsl)
        assert policy is not None
        assert policy.repeat_window.same_episode_days == 7
        assert policy.frequency_cap.max_episodes_per_show == 3
        assert len(policy.tag_eligibility) == 1
        assert policy.tag_eligibility[0].context == "primetime"
        assert len(policy.duration_gate) == 1
        assert policy.duration_gate[0].min_duration_sec == 1200
