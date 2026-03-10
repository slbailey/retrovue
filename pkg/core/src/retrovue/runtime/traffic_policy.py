"""
Traffic Policy — Pure domain layer for interstitial candidate evaluation.

Contract: docs/contracts/traffic_policy.md

Evaluates candidate interstitial assets against channel rules before selection.
All state needed for evaluation is passed as arguments — no I/O, no database,
no filesystem access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrafficPolicy:
    """Channel-level traffic rules."""

    allowed_types: list[str]
    default_cooldown_ms: int = 3_600_000
    type_cooldowns_ms: dict[str, int] | None = None
    max_plays_per_day: int = 0

    def __post_init__(self) -> None:
        if self.allowed_types is None:
            object.__setattr__(self, "allowed_types", [])
        if self.type_cooldowns_ms is None:
            object.__setattr__(self, "type_cooldowns_ms", {})


@dataclass(frozen=True)
class PlayRecord:
    """A single historical play event."""

    asset_id: str
    asset_type: str
    played_at_ms: int


@dataclass(frozen=True)
class TrafficCandidate:
    """A candidate interstitial asset offered for selection."""

    asset_id: str
    asset_type: str
    duration_ms: int
    asset_category: str | None = None


def evaluate_candidates(
    candidates: list[TrafficCandidate],
    policy: TrafficPolicy,
    play_history: list[PlayRecord],
    now_ms: int,
    day_start_ms: int,
) -> list[TrafficCandidate]:
    """Return eligible candidates sorted by rotation priority.

    Filters applied in order: allowed type, cooldown, daily cap, rotation sort.
    """
    if not candidates:
        return []

    allowed = set(policy.allowed_types)
    type_cooldowns = policy.type_cooldowns_ms or {}

    # Precompute history lookups: O(history) once, then O(1) per candidate.
    last_play: dict[str, int] = {}
    daily_count: dict[str, int] = {}
    for r in play_history:
        last_play[r.asset_id] = max(last_play.get(r.asset_id, -1), r.played_at_ms)
        if r.played_at_ms >= day_start_ms:
            daily_count[r.asset_id] = daily_count.get(r.asset_id, 0) + 1

    # Step 1: Allowed type filter
    eligible = [c for c in candidates if c.asset_type in allowed]

    # Step 2: Cooldown filter
    if policy.default_cooldown_ms > 0 or type_cooldowns:
        cooled: list[TrafficCandidate] = []
        for c in eligible:
            cooldown_ms = type_cooldowns.get(c.asset_type, policy.default_cooldown_ms)
            if cooldown_ms <= 0:
                cooled.append(c)
                continue
            most_recent = last_play.get(c.asset_id)
            if most_recent is None or now_ms - most_recent >= cooldown_ms:
                cooled.append(c)
        eligible = cooled

    # Step 3: Daily cap filter
    if policy.max_plays_per_day > 0:
        capped: list[TrafficCandidate] = []
        for c in eligible:
            if daily_count.get(c.asset_id, 0) < policy.max_plays_per_day:
                capped.append(c)
        eligible = capped

    # Step 4: Rotation sort — least-recently-played first, ties by asset_id
    eligible.sort(key=lambda c: (last_play.get(c.asset_id, -1), c.asset_id))
    return eligible


def select_next(
    candidates: list[TrafficCandidate],
    policy: TrafficPolicy,
    play_history: list[PlayRecord],
    now_ms: int,
    day_start_ms: int,
) -> TrafficCandidate | None:
    """Return the first eligible candidate, or None if none pass."""
    result = evaluate_candidates(candidates, policy, play_history, now_ms, day_start_ms)
    return result[0] if result else None
