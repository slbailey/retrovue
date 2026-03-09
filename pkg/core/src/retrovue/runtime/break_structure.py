"""
Break Structure.

Expands a break opportunity's allocated budget into a sequence of typed
slots: optional bumpers, a time-based interstitial pool, and an optional
station ID.

Bumpers are transition elements framing the break. Station IDs are legal
identifiers with fixed structural placement (after the interstitial pool,
before the from_break bumper). Neither bumpers nor station IDs are traffic
inventory — they are selected by dedicated mechanisms, not the traffic
policy engine.

This module implements the BreakStructure contract (break_structure.md).
It sits between BreakPlan (WHERE breaks occur) and Traffic Manager
(WHAT fills each slot).

Pure function — no DB, no I/O, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreakConfig:
    """Channel-level break structure configuration.

    Durations of zero mean the slot type is not used.
    """
    to_break_bumper_ms: int = 0
    from_break_bumper_ms: int = 0
    station_id_ms: int = 0


@dataclass(frozen=True)
class BreakSlot:
    """A single typed slot within a break."""
    slot_type: str   # "to_break_bumper" | "interstitial" | "station_id" | "from_break_bumper"
    duration_ms: int
    fill_rule: str   # "bumper" | "traffic" | "station_id"


@dataclass(frozen=True)
class BreakStructure:
    """The internal shape of a single commercial break."""
    slots: tuple[BreakSlot, ...]
    total_duration_ms: int


def build_break_structure(
    allocated_budget_ms: int,
    config: BreakConfig,
) -> BreakStructure:
    """Build a BreakStructure from the allocated budget and channel config.

    INV-BREAKSTRUCTURE-BUDGET-EXACT-001: slot durations sum to budget.
    INV-BREAKSTRUCTURE-ORDERED-001: canonical slot order maintained.
    INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001: at least one interstitial
        slot for any positive budget.
    INV-BREAKSTRUCTURE-DETERMINISTIC-001: pure function, no randomness.
    """
    if allocated_budget_ms <= 0:
        return BreakStructure(slots=(), total_duration_ms=0)

    # Attempt to reserve structural slots. Shed in reverse priority
    # (station_id first, then from_break, then to_break) until
    # interstitial pool is positive.
    to_break = config.to_break_bumper_ms if config.to_break_bumper_ms > 0 else 0
    from_break = config.from_break_bumper_ms if config.from_break_bumper_ms > 0 else 0
    station_id = config.station_id_ms if config.station_id_ms > 0 else 0

    structural = to_break + from_break + station_id
    interstitial_pool = allocated_budget_ms - structural

    # Shed optional slots to ensure interstitial_pool > 0
    if interstitial_pool <= 0:
        # Shed station_id first
        station_id = 0
        interstitial_pool = allocated_budget_ms - to_break - from_break
    if interstitial_pool <= 0:
        # Shed from_break_bumper
        from_break = 0
        interstitial_pool = allocated_budget_ms - to_break
    if interstitial_pool <= 0:
        # Shed to_break_bumper — entire budget goes to interstitial
        to_break = 0
        interstitial_pool = allocated_budget_ms

    slots: list[BreakSlot] = []

    if to_break > 0:
        slots.append(BreakSlot(
            slot_type="to_break_bumper",
            duration_ms=to_break,
            fill_rule="bumper",
        ))

    # Single interstitial slot gets the remaining pool
    slots.append(BreakSlot(
        slot_type="interstitial",
        duration_ms=interstitial_pool,
        fill_rule="traffic",
    ))

    if station_id > 0:
        slots.append(BreakSlot(
            slot_type="station_id",
            duration_ms=station_id,
            fill_rule="station_id",
        ))

    if from_break > 0:
        slots.append(BreakSlot(
            slot_type="from_break_bumper",
            duration_ms=from_break,
            fill_rule="bumper",
        ))

    return BreakStructure(
        slots=tuple(slots),
        total_duration_ms=allocated_budget_ms,
    )
