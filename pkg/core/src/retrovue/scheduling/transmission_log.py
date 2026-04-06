"""Transmission log types and derivation functions.

A TransmissionLogEntry is the grid-aligned record of what is scheduled to air
in a single grid slot. Derived purely from a ResolvedScheduleDay — no DB, no
side effects.

Invariants enforced:
    INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001: start/end must align to grid boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from retrovue.runtime.schedule_types import ResolvedScheduleDay


@dataclass(frozen=True)
class TransmissionLogEntry:
    """One grid-aligned transmission log entry.

    Derived from a single ResolvedSlot within a ResolvedScheduleDay.
    Immutable once created (frozen=True).
    """

    entry_id: str
    channel_id: str
    broadcast_day: date
    start_utc_ms: int
    end_utc_ms: int
    asset_id: str | None
    asset_path: str
    title: str
    plan_id: str | None
    schedule_day_date: date


def derive_transmission_log(
    *,
    channel_id: str,
    schedule_day: ResolvedScheduleDay,
    broadcast_day_start_utc_ms: int,
    grid_block_minutes: int,
) -> list[TransmissionLogEntry]:
    """Derive a transmission log from a ResolvedScheduleDay.

    Pure function — no DB, no side effects.

    Each ResolvedSlot becomes one TransmissionLogEntry with absolute UTC
    millisecond boundaries computed from the broadcast day start and slot
    position in the grid.
    """
    grid_ms = grid_block_minutes * 60 * 1000
    entries: list[TransmissionLogEntry] = []

    for i, slot in enumerate(schedule_day.resolved_slots):
        start_ms = broadcast_day_start_utc_ms + i * grid_ms
        end_ms = start_ms + int(slot.duration_seconds * 1000)

        entries.append(
            TransmissionLogEntry(
                entry_id=f"tl-{schedule_day.programming_day_date.isoformat()}-{i:03d}",
                channel_id=channel_id,
                broadcast_day=schedule_day.programming_day_date,
                start_utc_ms=start_ms,
                end_utc_ms=end_ms,
                asset_id=slot.resolved_asset.asset_id,
                asset_path=slot.resolved_asset.file_path,
                title=slot.resolved_asset.title,
                plan_id=schedule_day.plan_id,
                schedule_day_date=schedule_day.programming_day_date,
            )
        )

    return entries


def validate_transmission_log_grid_alignment(
    entries: list[TransmissionLogEntry],
    grid_block_minutes: int,
) -> None:
    """Validate INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001.

    Raises ValueError if any entry has start_utc_ms or end_utc_ms that
    is not a multiple of the grid block duration in milliseconds.
    """
    grid_ms = grid_block_minutes * 60 * 1000

    for entry in entries:
        if entry.start_utc_ms % grid_ms != 0:
            floor_ms = (entry.start_utc_ms // grid_ms) * grid_ms
            ceil_ms = floor_ms + grid_ms
            raise ValueError(
                f"INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001-VIOLATED: "
                f"entry {entry.entry_id} start_utc_ms={entry.start_utc_ms} "
                f"is not grid-aligned (nearest: {floor_ms}, {ceil_ms})"
            )
        if entry.end_utc_ms % grid_ms != 0:
            floor_ms = (entry.end_utc_ms // grid_ms) * grid_ms
            ceil_ms = floor_ms + grid_ms
            raise ValueError(
                f"INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001-VIOLATED: "
                f"entry {entry.entry_id} end_utc_ms={entry.end_utc_ms} "
                f"is not grid-aligned (nearest: {floor_ms}, {ceil_ms})"
            )
