"""
Deterministic serial episode resolver.

Contract: docs/contracts/runtime/INV-SERIAL-EPISODE-PROGRESSION.md

All functions in this module are pure — no mutable state, no I/O, no
system-time access.  They implement the occurrence-counting model that
makes serial episode progression survive scheduler downtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


# =============================================================================
# Domain value object — mirrors the persistent SerialRun entity but is a
# lightweight frozen dataclass for use in the scheduling hot path.
# =============================================================================


@dataclass(frozen=True)
class SerialRunInfo:
    """Read-only snapshot of a serial_runs record for the resolver.

    Constructed from the DB entity at lookup time; the resolver never
    touches the database itself.
    """

    channel_id: str
    placement_time: time
    placement_days: int  # 7-bit DOW bitmask, bit 0 = Monday
    content_source_id: str
    anchor_date: date
    anchor_episode_index: int
    wrap_policy: str  # "wrap", "hold_last", "stop"


# =============================================================================
# Occurrence counter  (OC-001 through OC-005)
# =============================================================================


def count_occurrences(anchor: date, target: date, placement_days: int) -> int:
    """Count matching days in the half-open interval [anchor, target).

    Pure function.  Returns the number of dates *d* where
    ``anchor <= d < target`` and ``d.weekday()`` bit is set in
    *placement_days*.

    OC-001: Calendar-based only — no playlog, as-run, or resolution history.
    OC-002: anchor date yields 0 (half-open: [anchor, anchor) is empty).
    OC-003: Half-open interval semantics.
    OC-004: Deterministic — same inputs always produce same output.
    OC-005: Arithmetic (full-weeks × bits-per-week + partial remainder).
    """
    if target <= anchor:
        return 0

    total_days = (target - anchor).days
    full_weeks, remainder = divmod(total_days, 7)

    bits_per_week = bin(placement_days).count("1")
    count = full_weeks * bits_per_week

    anchor_dow = anchor.weekday()  # 0 = Monday
    for i in range(remainder):
        if placement_days & (1 << ((anchor_dow + i) % 7)):
            count += 1

    return count


# =============================================================================
# Wrap policy  (WP-001 through WP-003)
# =============================================================================

# Sentinel: returned when policy is "stop" and the series is exhausted.
FILLER: int | None = None


def apply_wrap_policy(
    raw_index: int,
    episode_count: int,
    policy: str,
) -> int | None:
    """Map *raw_index* to an effective episode index under *policy*.

    Returns an ``int`` index, or ``None`` (FILLER) for the ``stop``
    policy when the series is exhausted.

    WP-001 wrap      → ``raw_index % episode_count``
    WP-002 hold_last → ``min(raw_index, episode_count - 1)``
    WP-003 stop      → ``None`` when ``raw_index >= episode_count``
    """
    if episode_count <= 0:
        return FILLER

    if policy == "wrap":
        return raw_index % episode_count
    if policy == "hold_last":
        return min(raw_index, episode_count - 1)
    if policy == "stop":
        if raw_index >= episode_count:
            return FILLER
        return raw_index

    msg = f"Unknown wrap policy: {policy!r}"
    raise ValueError(msg)


# =============================================================================
# Episode resolver  (INV-SERIAL-001 through INV-SERIAL-008)
# =============================================================================


def resolve_serial_episode(
    run: SerialRunInfo,
    target_broadcast_day: date,
    episode_count: int,
) -> int | None:
    """Select the episode index for *target_broadcast_day*.

    Pure function.  Returns an episode index, or ``None`` (FILLER) under
    the ``stop`` policy when the series is exhausted.

    INV-SERIAL-001: Deterministic — same inputs always produce same output.
    INV-SERIAL-002: Independent of scheduler uptime.
    INV-SERIAL-003: Anchor date resolves to anchor episode.
    INV-SERIAL-006: Calendar-based occurrence counting.
    INV-SERIAL-008: Flat episode list — no season awareness.
    """
    occ = count_occurrences(run.anchor_date, target_broadcast_day, run.placement_days)
    raw_index = run.anchor_episode_index + occ
    return apply_wrap_policy(raw_index, episode_count, run.wrap_policy)


# =============================================================================
# Anchor validation  (INV-SERIAL-007)
# =============================================================================


def validate_anchor(anchor_date: date, placement_days: int) -> None:
    """Raise ``ValueError`` if *anchor_date* does not match *placement_days*.

    INV-SERIAL-007: The anchor datetime's day-of-week MUST have its bit
    set in the serial run's placement_days bitmask.
    """
    if not (1 << anchor_date.weekday()) & placement_days:
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        raise ValueError(
            f"INV-SERIAL-007 VIOLATION: anchor {anchor_date.isoformat()} "
            f"({dow_names[anchor_date.weekday()]}) does not match "
            f"placement_days mask {placement_days:#09b}"
        )


# =============================================================================
# Day-of-week bitmask constants (convenience, also used by integration code)
# =============================================================================

MONDAY = 1 << 0
TUESDAY = 1 << 1
WEDNESDAY = 1 << 2
THURSDAY = 1 << 3
FRIDAY = 1 << 4
SATURDAY = 1 << 5
SUNDAY = 1 << 6

DAILY = 0b1111111  # 127
WEEKDAY = 0b0011111  # 31
WEEKEND = 0b1100000  # 96

# Mapping from Zone.day_filters 3-letter codes to bit positions.
DOW_CODE_TO_BIT: dict[str, int] = {
    "MON": MONDAY,
    "TUE": TUESDAY,
    "WED": WEDNESDAY,
    "THU": THURSDAY,
    "FRI": FRIDAY,
    "SAT": SATURDAY,
    "SUN": SUNDAY,
}

# Mapping from DSL schedule layer keys to bitmasks.
DSL_KEY_TO_MASK: dict[str, int] = {
    "all_day": DAILY,
    "weekdays": WEEKDAY,
    "weekends": WEEKEND,
    "monday": MONDAY,
    "tuesday": TUESDAY,
    "wednesday": WEDNESDAY,
    "thursday": THURSDAY,
    "friday": FRIDAY,
    "saturday": SATURDAY,
    "sunday": SUNDAY,
}


def zone_day_filters_to_mask(day_filters: list[str] | None) -> int:
    """Convert ``Zone.day_filters`` (e.g. ``["MON","TUE"]``) to bitmask.

    ``None`` means all days → 127.
    """
    if day_filters is None:
        return DAILY
    mask = 0
    for code in day_filters:
        bit = DOW_CODE_TO_BIT.get(code.upper())
        if bit is None:
            raise ValueError(f"Unknown day code: {code!r}")
        mask |= bit
    return mask


def dsl_layer_key_to_mask(key: str) -> int:
    """Convert a DSL schedule layer key (e.g. ``"weekdays"``) to bitmask."""
    mask = DSL_KEY_TO_MASK.get(key)
    if mask is None:
        raise ValueError(f"Unknown DSL schedule key: {key!r}")
    return mask
