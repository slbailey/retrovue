"""
Scheduling Policies — Pure domain layer for scheduling eligibility evaluation.

Contract: docs/contracts/scheduling_policies.md

Evaluates candidate assets against operator-defined scheduling policies before
block assembly. All state needed for evaluation is passed as arguments — no I/O,
no database, no filesystem access.

Policies layer on top of LAW-ELIGIBILITY (state=ready AND approved_for_broadcast=true)
and add further restrictions — they never relax the core gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


class _SchedulableAsset(Protocol):
    """Structural protocol for assets passed to policy evaluation.

    Any object with these attributes is accepted — no coupling to the ORM Asset class.
    """

    asset_id: str
    show_id: str
    episode_id: str
    duration_ms: int | None
    tags: frozenset[str]
    state: str
    approved_for_broadcast: bool


class _AirHistoryEntry(Protocol):
    """Structural protocol for air history records."""

    asset_id: str
    show_id: str
    episode_id: str
    aired_date: date


# ---------------------------------------------------------------------------
# Rule types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepeatWindowRule:
    """Prevents re-airing the same episode within a configurable day window."""

    same_episode_days: int


@dataclass(frozen=True)
class FrequencyCapRule:
    """Limits episodes from the same show within a scheduling day."""

    max_episodes_per_show: int


@dataclass(frozen=True)
class TagEligibilityRule:
    """Requires or excludes assets based on tag membership for a context."""

    context: str
    require_tags: frozenset[str] = frozenset()
    exclude_tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DurationGateRule:
    """Enforces min/max duration constraints for a slot context."""

    context: str
    min_duration_sec: int = 0
    max_duration_sec: int = 0


# ---------------------------------------------------------------------------
# Violation output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyViolation:
    """Structured output from policy evaluation (INV-POLICY-VIOLATION-STRUCTURED-001)."""

    invariant_id: str
    rule_type: str
    message: str
    details: dict[str, Any]


# ---------------------------------------------------------------------------
# Composite policy object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchedulingPolicy:
    """Runtime evaluation object containing resolved policy rules."""

    repeat_window: RepeatWindowRule | None = None
    frequency_cap: FrequencyCapRule | None = None
    tag_eligibility: list[TagEligibilityRule] = field(default_factory=list)
    duration_gate: list[DurationGateRule] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-rule evaluation functions
# ---------------------------------------------------------------------------


def evaluate_repeat_window(
    asset: _SchedulableAsset,
    rule: RepeatWindowRule,
    history: list[_AirHistoryEntry],
    broadcast_date: date,
) -> list[PolicyViolation]:
    """Check a single asset against a repeat window rule."""
    violations: list[PolicyViolation] = []
    for record in history:
        if record.episode_id != asset.episode_id:
            continue
        days_since = (broadcast_date - record.aired_date).days
        if days_since < rule.same_episode_days:
            violations.append(
                PolicyViolation(
                    invariant_id="INV-POLICY-PURE-001",
                    rule_type="repeat_window",
                    message=(
                        f"Episode {asset.episode_id!r} aired {days_since} days ago, "
                        f"within {rule.same_episode_days}-day repeat window"
                    ),
                    details={
                        "asset_id": asset.asset_id,
                        "episode_id": asset.episode_id,
                        "days_since": days_since,
                        "window_days": rule.same_episode_days,
                    },
                )
            )
    return violations


def evaluate_frequency_cap(
    asset: _SchedulableAsset,
    rule: FrequencyCapRule,
    history: list[_AirHistoryEntry],
    broadcast_date: date,
) -> list[PolicyViolation]:
    """Check a single asset against a frequency cap rule."""
    if rule.max_episodes_per_show == 0:
        return []

    count = sum(
        1 for r in history if r.show_id == asset.show_id and r.aired_date == broadcast_date
    )
    if count >= rule.max_episodes_per_show:
        return [
            PolicyViolation(
                invariant_id="INV-POLICY-PURE-001",
                rule_type="frequency_cap",
                message=(
                    f"Show {asset.show_id!r} has {count} episodes on {broadcast_date}, "
                    f"cap is {rule.max_episodes_per_show}"
                ),
                details={
                    "asset_id": asset.asset_id,
                    "show_id": asset.show_id,
                    "count": count,
                    "max_per_day": rule.max_episodes_per_show,
                },
            )
        ]
    return []


def evaluate_tag_eligibility(
    asset: _SchedulableAsset,
    rule: TagEligibilityRule,
    slot_context: str,
) -> list[PolicyViolation]:
    """Check a single asset against a tag eligibility rule."""
    if rule.context != slot_context:
        return []

    violations: list[PolicyViolation] = []
    asset_tags = asset.tags

    if rule.require_tags:
        missing = rule.require_tags - asset_tags
        if missing:
            violations.append(
                PolicyViolation(
                    invariant_id="INV-POLICY-PURE-001",
                    rule_type="tag_eligibility",
                    message=(
                        f"Asset {asset.asset_id!r} missing required tags: {sorted(missing)}"
                    ),
                    details={
                        "asset_id": asset.asset_id,
                        "missing_tags": sorted(missing),
                        "context": rule.context,
                    },
                )
            )

    if rule.exclude_tags:
        present = rule.exclude_tags & asset_tags
        if present:
            violations.append(
                PolicyViolation(
                    invariant_id="INV-POLICY-PURE-001",
                    rule_type="tag_eligibility",
                    message=(
                        f"Asset {asset.asset_id!r} has excluded tags: {sorted(present)}"
                    ),
                    details={
                        "asset_id": asset.asset_id,
                        "excluded_tags": sorted(present),
                        "context": rule.context,
                    },
                )
            )

    return violations


def evaluate_duration_gate(
    asset: _SchedulableAsset,
    rule: DurationGateRule,
    slot_context: str,
) -> list[PolicyViolation]:
    """Check a single asset against a duration gate rule."""
    if rule.context != slot_context:
        return []

    if rule.min_duration_sec == 0 and rule.max_duration_sec == 0:
        return []

    duration_ms = asset.duration_ms or 0
    duration_sec = duration_ms / 1000.0

    violations: list[PolicyViolation] = []

    if rule.min_duration_sec > 0 and duration_sec < rule.min_duration_sec:
        violations.append(
            PolicyViolation(
                invariant_id="INV-POLICY-PURE-001",
                rule_type="duration_gate",
                message=(
                    f"Asset {asset.asset_id!r} duration {duration_sec}s "
                    f"below minimum {rule.min_duration_sec}s for {slot_context!r}"
                ),
                details={
                    "asset_id": asset.asset_id,
                    "duration_sec": duration_sec,
                    "min_duration_sec": rule.min_duration_sec,
                    "context": slot_context,
                },
            )
        )

    if rule.max_duration_sec > 0 and duration_sec > rule.max_duration_sec:
        violations.append(
            PolicyViolation(
                invariant_id="INV-POLICY-PURE-001",
                rule_type="duration_gate",
                message=(
                    f"Asset {asset.asset_id!r} duration {duration_sec}s "
                    f"exceeds maximum {rule.max_duration_sec}s for {slot_context!r}"
                ),
                details={
                    "asset_id": asset.asset_id,
                    "duration_sec": duration_sec,
                    "max_duration_sec": rule.max_duration_sec,
                    "context": slot_context,
                },
            )
        )

    return violations


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def evaluate_scheduling_policies(
    *,
    asset: _SchedulableAsset,
    policy: SchedulingPolicy,
    slot_context: str,
    play_history: list[_AirHistoryEntry],
    broadcast_date: date,
) -> list[PolicyViolation]:
    """Evaluate all policy rules against a single asset.

    INV-POLICY-LAYERED-001: checks LAW-ELIGIBILITY first.
    INV-POLICY-PURE-001: no I/O, no mutation.
    INV-POLICY-IDEMPOTENT-001: deterministic output.
    """
    violations: list[PolicyViolation] = []

    # LAW-ELIGIBILITY gate — policies layer on top, never relax
    if asset.state != "ready" or not asset.approved_for_broadcast:
        violations.append(
            PolicyViolation(
                invariant_id="INV-POLICY-LAYERED-001",
                rule_type="eligibility",
                message=(
                    f"Asset {asset.asset_id!r} fails LAW-ELIGIBILITY: "
                    f"state={asset.state!r}, approved={asset.approved_for_broadcast}"
                ),
                details={
                    "asset_id": asset.asset_id,
                    "state": asset.state,
                    "approved_for_broadcast": asset.approved_for_broadcast,
                },
            )
        )
        return violations

    # Evaluation order per contract: repeat_window → frequency_cap → tag_eligibility → duration_gate
    if policy.repeat_window is not None:
        violations.extend(
            evaluate_repeat_window(asset, policy.repeat_window, play_history, broadcast_date)
        )

    if policy.frequency_cap is not None:
        violations.extend(
            evaluate_frequency_cap(asset, policy.frequency_cap, play_history, broadcast_date)
        )

    for tag_rule in policy.tag_eligibility:
        violations.extend(evaluate_tag_eligibility(asset, tag_rule, slot_context))

    for dur_rule in policy.duration_gate:
        violations.extend(evaluate_duration_gate(asset, dur_rule, slot_context))

    return violations
