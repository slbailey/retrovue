"""Progression Cursor — persistent progression state for schedule blocks.

Contract: docs/contracts/progression_cursor.md

Tracks which asset a schedule block will select next from its program's
pool. Cursor state persists across scheduler restarts, recompilation,
and multi-day schedules.

This module is pure domain logic with no database or scheduler dependencies.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PlanningFault(Exception):
    """Raised when cursor rules are violated during planning."""


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleBlockIdentity:
    channel_id: str
    schedule_layer: str
    start_time: str
    program_ref: str


@dataclass
class ProgressionCursor:
    identity: ScheduleBlockIdentity
    position: int = 0
    cycle: int = 0
    shuffle_seed: int | None = None


@dataclass
class AdvanceResult:
    cursor: ProgressionCursor
    selected_asset: str


@dataclass
class CursorStore:
    """In-process cursor store for schedule compilation.

    Keyed by ScheduleBlockIdentity. Callers may pre-populate cursors
    at computed positions to simulate cross-day persistence.
    """

    _data: dict[tuple, ProgressionCursor] = field(default_factory=dict)

    def _key(self, identity: ScheduleBlockIdentity) -> tuple:
        return (
            identity.channel_id,
            identity.schedule_layer,
            identity.start_time,
            identity.program_ref,
        )

    def load(self, identity: ScheduleBlockIdentity) -> ProgressionCursor | None:
        return self._data.get(self._key(identity))

    def save(self, cursor: ProgressionCursor) -> None:
        self._data[self._key(cursor.identity)] = cursor


# ---------------------------------------------------------------------------
# Seed derivation
# ---------------------------------------------------------------------------


def derive_shuffle_seed(identity: ScheduleBlockIdentity, *, cycle: int) -> int:
    """Deterministically derive a shuffle seed from identity and cycle number."""
    raw = (
        f"{identity.channel_id}:{identity.schedule_layer}:"
        f"{identity.start_time}:{identity.program_ref}:{cycle}"
    )
    return int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)


# ---------------------------------------------------------------------------
# Shuffle order
# ---------------------------------------------------------------------------


def get_shuffle_order(pool_assets: list[str], seed: int) -> list[str]:
    """Return a shuffled copy of pool_assets determined entirely by seed."""
    rng = random.Random(seed)
    order = list(pool_assets)
    rng.shuffle(order)
    return order


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def initialize_cursor(
    identity: ScheduleBlockIdentity,
    *,
    mode: str = "sequential",
) -> ProgressionCursor:
    """Create a fresh cursor at position 0, cycle 0.

    INV-CURSOR-008: initialization is deterministic.
    """
    shuffle_seed: int | None = None
    if mode == "shuffle":
        shuffle_seed = derive_shuffle_seed(identity, cycle=0)

    return ProgressionCursor(
        identity=identity,
        position=0,
        cycle=0,
        shuffle_seed=shuffle_seed,
    )


# ---------------------------------------------------------------------------
# Advance
# ---------------------------------------------------------------------------


def advance_cursor(
    *,
    cursor: ProgressionCursor | None,
    pool_assets: list[str],
    progression: str,
) -> AdvanceResult:
    """Advance cursor by one position and return the selected asset.

    INV-CURSOR-001: cursor must exist for sequential/shuffle.
    INV-CURSOR-002: position advances by exactly 1.
    INV-CURSOR-003: wraps at pool boundary, increments cycle.
    INV-CURSOR-004: shuffle seed unchanged within cycle.
    INV-CURSOR-005: new seed on cycle wrap.
    """
    if cursor is None:
        raise PlanningFault(
            "INV-CURSOR-001: cursor must be resolved before asset selection"
        )

    pool_size = len(pool_assets)
    if pool_size == 0:
        raise PlanningFault("Cannot advance cursor on empty pool")

    # Cursor invalidation: position exceeds current pool size.
    # Recovery path per scheduler_cursor_integration contract —
    # normalize position via modulo, derive cycle from total advances.
    if cursor.position >= pool_size:
        total = cursor.position + cursor.cycle * pool_size
        cursor = ProgressionCursor(
            identity=cursor.identity,
            position=total % pool_size,
            cycle=total // pool_size,
            shuffle_seed=cursor.shuffle_seed,
        )

    # Select asset at current position
    if progression == "shuffle":
        if cursor.shuffle_seed is None:
            raise PlanningFault("Shuffle cursor requires a shuffle_seed")
        order = get_shuffle_order(pool_assets, cursor.shuffle_seed)
        selected = order[cursor.position]
    else:
        selected = pool_assets[cursor.position]

    # Advance position by 1 (INV-CURSOR-002)
    new_position = cursor.position + 1
    new_cycle = cursor.cycle
    new_seed = cursor.shuffle_seed

    # Wrap at pool boundary (INV-CURSOR-003)
    if new_position >= pool_size:
        new_position = 0
        new_cycle += 1
        # INV-CURSOR-005: reshuffle on new cycle
        if progression == "shuffle":
            new_seed = derive_shuffle_seed(cursor.identity, cycle=new_cycle)

    new_cursor = ProgressionCursor(
        identity=cursor.identity,
        position=new_position,
        cycle=new_cycle,
        shuffle_seed=new_seed,
    )

    return AdvanceResult(cursor=new_cursor, selected_asset=selected)


# ---------------------------------------------------------------------------
# Random selection
# ---------------------------------------------------------------------------


def select_random_asset(
    *,
    identity: ScheduleBlockIdentity,
    pool_assets: list[str],
    execution_ts_ms: int,
    cursor: ProgressionCursor | None = None,
) -> str:
    """Select an asset independently of cursor state.

    INV-CURSOR-007: cursor is ignored entirely.
    Selection is derived from identity + execution timestamp.
    """
    raw = (
        f"{identity.channel_id}:{identity.schedule_layer}:"
        f"{identity.start_time}:{identity.program_ref}:{execution_ts_ms}"
    )
    seed = int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    return rng.choice(pool_assets)
