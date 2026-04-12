"""Execution entry types and derivation functions.

An ExecutionEntry is the runtime-ready execution unit derived from a
TransmissionLogEntry. Each entry carries a traceability reference back
to its source transmission log entry.

Invariants enforced:
    INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001: traceability ref required.
    INV-EXECUTIONENTRY-NO-GAPS-001: entries must be temporally contiguous.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrovue.scheduling.transmission_log import TransmissionLogEntry


@dataclass(frozen=True)
class ExecutionEntry:
    """One runtime execution entry, derived from a TransmissionLogEntry.

    Immutable once created (frozen=True).
    """

    entry_id: str
    channel_id: str
    start_utc_ms: int
    end_utc_ms: int
    asset_path: str
    transmission_log_ref: str  # entry_id of source TransmissionLogEntry
    is_operator_override: bool = False


def derive_execution_entries(
    tl_entries: list[TransmissionLogEntry],
) -> list[ExecutionEntry]:
    """Derive execution entries from transmission log entries.

    Pure function — no DB, no side effects.
    Each TransmissionLogEntry becomes one ExecutionEntry with a
    traceability reference.
    """
    return [
        ExecutionEntry(
            entry_id=f"ex-{tl.entry_id}",
            channel_id=tl.channel_id,
            start_utc_ms=tl.start_utc_ms,
            end_utc_ms=tl.end_utc_ms,
            asset_path=tl.asset_path,
            transmission_log_ref=tl.entry_id,
        )
        for tl in tl_entries
    ]


def validate_execution_entry_contiguity(
    entries: list[ExecutionEntry],
) -> None:
    """Validate INV-EXECUTIONENTRY-NO-GAPS-001.

    Sorts entries by start_utc_ms and checks that each entry's end
    equals the next entry's start. Raises ValueError on gap.
    """
    if len(entries) < 2:
        return

    sorted_entries = sorted(entries, key=lambda e: e.start_utc_ms)

    for i in range(len(sorted_entries) - 1):
        current = sorted_entries[i]
        next_entry = sorted_entries[i + 1]
        if current.end_utc_ms != next_entry.start_utc_ms:
            gap_ms = next_entry.start_utc_ms - current.end_utc_ms
            raise ValueError(
                f"INV-EXECUTIONENTRY-NO-GAPS-001-VIOLATED: "
                f"gap of {gap_ms}ms between entry {current.entry_id} "
                f"(end={current.end_utc_ms}) and {next_entry.entry_id} "
                f"(start={next_entry.start_utc_ms})"
            )
