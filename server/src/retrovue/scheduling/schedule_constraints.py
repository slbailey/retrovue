"""Schedule constraint data types and pure evaluation functions.

Defines three constraint families — blackout, adjacency, content restriction —
and idempotent evaluation functions that produce structured violation outputs.

Constraints are pure functions: no side effects, no DB access, no wall-clock reads.

Enforces:
  INV-CONSTRAINT-BLACKOUT-001           — Blackout exclusion windows
  INV-CONSTRAINT-ADJACENCY-001          — Adjacency content restrictions
  INV-CONSTRAINT-CONTENT-RESTRICTION-001 — Content time-window restrictions
  INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001 — Evaluation idempotency
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time as dt_time
from typing import Any


# ---------------------------------------------------------------------------
# Constraint data types (frozen — immutable by construction)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlackoutConstraint:
    """A date/time exclusion window for specific content."""

    asset_ids: frozenset[str]
    start_date: date
    end_date: date
    start_time: dt_time
    end_time: dt_time
    day_filters: frozenset[str] | None
    reason: str


@dataclass(frozen=True)
class AdjacencyConstraint:
    """A back-to-back content restriction between two classifications."""

    classification_a: str
    classification_b: str
    direction: str  # "both" or "a_before_b"
    reason: str

    def __post_init__(self) -> None:
        if self.direction not in ("both", "a_before_b"):
            raise ValueError(
                f"AdjacencyConstraint.direction must be 'both' or 'a_before_b', "
                f"got '{self.direction}'"
            )


@dataclass(frozen=True)
class ContentRestrictionConstraint:
    """A rating/classification gate restricting content to a time window."""

    classification: str
    allowed_start_time: dt_time
    allowed_end_time: dt_time
    day_filters: frozenset[str] | None
    reason: str


@dataclass(frozen=True)
class ConstraintViolation:
    """Structured violation output from constraint evaluation."""

    invariant_id: str
    constraint_type: str
    message: str
    details: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAY_MINUTES = 24 * 60
_END_OF_DAY = dt_time(23, 59, 59, 999999)
_ALL_DAYS = frozenset({"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"})

_DAY_NAME_MAP = {
    0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN",
}


def _time_to_minutes(t: dt_time) -> int:
    if t == _END_OF_DAY:
        return _DAY_MINUTES
    return t.hour * 60 + t.minute + (1 if t.second >= 30 else 0)


def _effective_days(day_filters: frozenset[str] | None) -> frozenset[str]:
    if day_filters:
        return day_filters
    return _ALL_DAYS


def _date_to_day_name(d: date) -> str:
    return _DAY_NAME_MAP[d.weekday()]


def _time_ranges_overlap_wall(
    a_start: int, a_end: int, b_start: int, b_end: int
) -> bool:
    """Check if two wall-clock time ranges overlap (in minutes).

    Handles wrapping ranges (start > end means crosses midnight).
    Full-day ranges (0, 1440) always overlap with any non-empty range.
    """
    # Expand wrapping ranges into sub-intervals in [0, 1440]
    def _intervals(s: int, e: int) -> list[tuple[int, int]]:
        if s == 0 and e == _DAY_MINUTES:
            return [(0, _DAY_MINUTES)]
        if s < e:
            return [(s, e)]
        # Wraps midnight
        parts: list[tuple[int, int]] = []
        if s < _DAY_MINUTES:
            parts.append((s, _DAY_MINUTES))
        if e > 0:
            parts.append((0, e))
        return parts

    for a_s, a_e in _intervals(a_start, a_end):
        for b_s, b_e in _intervals(b_start, b_end):
            if max(a_s, b_s) < min(a_e, b_e):
                return True
    return False


# ---------------------------------------------------------------------------
# Blackout evaluation — INV-CONSTRAINT-BLACKOUT-001
# ---------------------------------------------------------------------------

def check_blackout_constraints(
    zones: list[Any],
    constraints: list[BlackoutConstraint],
    broadcast_date: date,
    programming_day_start: dt_time = dt_time(0, 0),
) -> list[ConstraintViolation]:
    """Check zones against blackout constraints for a specific broadcast date.

    Pure function. Returns a list of violations (empty if clean).
    """
    if not constraints:
        return []

    day_name = _date_to_day_name(broadcast_date)
    violations: list[ConstraintViolation] = []

    for constraint in constraints:
        # Date range check
        if broadcast_date < constraint.start_date or broadcast_date > constraint.end_date:
            continue

        # Day filter check
        constraint_days = _effective_days(constraint.day_filters)
        if day_name not in constraint_days:
            continue

        blackout_start = _time_to_minutes(constraint.start_time)
        blackout_end = _time_to_minutes(constraint.end_time)

        active_zones = [z for z in zones if z.enabled]
        for zone in active_zones:
            zone_days = _effective_days(
                frozenset(zone.day_filters) if zone.day_filters else None
            )
            if day_name not in zone_days:
                continue

            zone_start = _time_to_minutes(zone.start_time)
            zone_end = _time_to_minutes(zone.end_time)

            # Compare in wall-clock coordinates; _time_ranges_overlap_wall
            # handles wrapping and full-day ranges.
            if not _time_ranges_overlap_wall(
                zone_start, zone_end,
                blackout_start, blackout_end,
            ):
                continue

            # Check asset overlap
            zone_assets = frozenset(
                str(a) for a in (getattr(zone, "schedulable_assets", None) or [])
            )
            if not constraint.asset_ids:
                # Empty asset_ids = all assets blocked
                blocked_assets = zone_assets
            else:
                blocked_assets = zone_assets & constraint.asset_ids

            zone_name = getattr(zone, "name", "?")
            for asset_id in sorted(blocked_assets):
                violations.append(ConstraintViolation(
                    invariant_id="INV-CONSTRAINT-BLACKOUT-001-VIOLATED",
                    constraint_type="blackout",
                    message=(
                        f"Asset '{asset_id}' in zone '{zone_name}' is blacked out "
                        f"on {broadcast_date} ({constraint.reason})"
                    ),
                    details={
                        "asset_id": asset_id,
                        "zone_name": zone_name,
                        "broadcast_date": str(broadcast_date),
                        "blackout_start": str(constraint.start_time),
                        "blackout_end": str(constraint.end_time),
                        "reason": constraint.reason,
                    },
                ))

    return violations


# ---------------------------------------------------------------------------
# Adjacency evaluation — INV-CONSTRAINT-ADJACENCY-001
# ---------------------------------------------------------------------------

def check_adjacency_constraints(
    block_classifications: list[tuple[str, str]],
    constraints: list[AdjacencyConstraint],
) -> list[ConstraintViolation]:
    """Check adjacent block pairs against adjacency constraints.

    block_classifications: ordered list of (block_id, classification) tuples
    representing the compiled schedule in air order.

    Pure function. Returns a list of violations (empty if clean).
    """
    if not constraints or len(block_classifications) < 2:
        return []

    violations: list[ConstraintViolation] = []

    for i in range(len(block_classifications) - 1):
        leading_id, leading_class = block_classifications[i]
        trailing_id, trailing_class = block_classifications[i + 1]

        for constraint in constraints:
            violated = False

            if constraint.direction == "both":
                if (
                    (leading_class == constraint.classification_a
                     and trailing_class == constraint.classification_b)
                    or (leading_class == constraint.classification_b
                        and trailing_class == constraint.classification_a)
                ):
                    violated = True
            elif constraint.direction == "a_before_b":
                if (leading_class == constraint.classification_a
                        and trailing_class == constraint.classification_b):
                    violated = True

            if violated:
                violations.append(ConstraintViolation(
                    invariant_id="INV-CONSTRAINT-ADJACENCY-001-VIOLATED",
                    constraint_type="adjacency",
                    message=(
                        f"Block '{leading_id}' ({leading_class}) followed by "
                        f"block '{trailing_id}' ({trailing_class}) violates "
                        f"adjacency constraint ({constraint.reason})"
                    ),
                    details={
                        "leading_block_id": leading_id,
                        "leading_classification": leading_class,
                        "trailing_block_id": trailing_id,
                        "trailing_classification": trailing_class,
                        "direction": constraint.direction,
                        "reason": constraint.reason,
                    },
                ))

    return violations


# ---------------------------------------------------------------------------
# Content restriction evaluation — INV-CONSTRAINT-CONTENT-RESTRICTION-001
# ---------------------------------------------------------------------------

def check_content_restriction_constraints(
    block_classifications: list[tuple[str, str, int]],
    constraints: list[ContentRestrictionConstraint],
    broadcast_date: date,
    programming_day_start: dt_time = dt_time(0, 0),
) -> list[ConstraintViolation]:
    """Check blocks against content restriction (watershed) constraints.

    block_classifications: ordered list of (block_id, classification, start_utc_ms)
    tuples. start_utc_ms is used to determine the broadcast-day-relative time.

    Pure function. Returns a list of violations (empty if clean).
    """
    if not constraints or not block_classifications:
        return []

    day_name = _date_to_day_name(broadcast_date)
    pds_min = _time_to_minutes(programming_day_start)
    violations: list[ConstraintViolation] = []

    for block_id, classification, start_utc_ms in block_classifications:
        for constraint in constraints:
            if classification != constraint.classification:
                continue

            constraint_days = _effective_days(constraint.day_filters)
            if day_name not in constraint_days:
                continue

            # Convert block start to broadcast-day-relative minutes
            # start_utc_ms is absolute; we need the time-of-day portion
            block_minutes_in_day = (start_utc_ms // 60_000) % _DAY_MINUTES
            block_norm = (block_minutes_in_day - pds_min) % _DAY_MINUTES

            allowed_start = (_time_to_minutes(constraint.allowed_start_time) - pds_min) % _DAY_MINUTES
            allowed_end = (_time_to_minutes(constraint.allowed_end_time) - pds_min) % _DAY_MINUTES
            if allowed_end == 0:
                allowed_end = _DAY_MINUTES

            # Check if block falls within allowed window
            if allowed_start < allowed_end:
                in_window = allowed_start <= block_norm < allowed_end
            else:
                # Wrapping window (e.g. 21:00 - 06:00)
                in_window = block_norm >= allowed_start or block_norm < allowed_end

            if not in_window:
                violations.append(ConstraintViolation(
                    invariant_id="INV-CONSTRAINT-CONTENT-RESTRICTION-001-VIOLATED",
                    constraint_type="content_restriction",
                    message=(
                        f"Block '{block_id}' ({classification}) scheduled outside "
                        f"allowed window ({constraint.reason})"
                    ),
                    details={
                        "block_id": block_id,
                        "classification": classification,
                        "broadcast_date": str(broadcast_date),
                        "allowed_start": str(constraint.allowed_start_time),
                        "allowed_end": str(constraint.allowed_end_time),
                        "reason": constraint.reason,
                    },
                ))

    return violations


__all__ = [
    "BlackoutConstraint",
    "AdjacencyConstraint",
    "ContentRestrictionConstraint",
    "ConstraintViolation",
    "check_blackout_constraints",
    "check_adjacency_constraints",
    "check_content_restriction_constraints",
]
