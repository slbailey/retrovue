"""ExecutionEntry window store with derivation and contiguity enforcement.

Stores ExecutionEntries for a channel and enforces:
    INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001: derivation traceability
    INV-EXECUTIONENTRY-NO-GAPS-001: temporal contiguity within lookahead window

HorizonManager is the sole writer. Playout consumers are readers only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from retrovue.scheduling.execution_entry import (
    ExecutionEntry,
    validate_execution_entry_contiguity,
)


@dataclass
class GapFault:
    """Describes a temporal gap in the ExecutionEntry sequence."""

    channel_id: str
    gap_start_ms: int
    gap_end_ms: int
    fault_class: str  # "runtime" or "planning"
    upstream_source: str | None = None  # e.g. "ResolvedScheduleDay" if traceable


@dataclass
class DerivationFault:
    """Describes an ExecutionEntry that lacks derivation traceability."""

    entry_id: str
    channel_id: str
    fault_class: str = "planning"


@dataclass
class ExecutionWindowStore:
    """In-memory store of ExecutionEntries for a single channel.

    Enforces derivation and contiguity invariants on add.
    """

    channel_id: str
    entries: list[ExecutionEntry] = field(default_factory=list)
    enforce_derivation_from_playlist: bool = True

    def add_entries(
        self,
        new_entries: list[ExecutionEntry],
    ) -> None:
        """Add entries to the store, enforcing derivation and contiguity.

        Raises ValueError if any entry violates derivation or contiguity.
        """
        # INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001: derivation check
        if self.enforce_derivation_from_playlist:
            for entry in new_entries:
                if not entry.transmission_log_ref and not entry.is_operator_override:
                    raise ValueError(
                        f"INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED: "
                        f"entry {entry.entry_id} has no transmission_log_ref and "
                        f"is not an operator override"
                    )

        combined = sorted(
            self.entries + new_entries, key=lambda e: e.start_utc_ms
        )

        # INV-EXECUTIONENTRY-NO-GAPS-001: contiguity check on combined set
        validate_execution_entry_contiguity(combined)

        self.entries = combined

    def window_end_ms(self) -> int | None:
        """Return the end_utc_ms of the last entry, or None if empty."""
        if not self.entries:
            return None
        return max(e.end_utc_ms for e in self.entries)

    def window_start_ms(self) -> int | None:
        """Return the start_utc_ms of the first entry, or None if empty."""
        if not self.entries:
            return None
        return min(e.start_utc_ms for e in self.entries)

    def depth_ms(self, now_ms: int) -> int:
        """Return remaining execution depth from now_ms in milliseconds."""
        end = self.window_end_ms()
        if end is None:
            return 0
        return max(0, end - now_ms)

    def detect_gaps(self) -> list[GapFault]:
        """Detect gaps without raising. Returns list of GapFault."""
        if len(self.entries) < 2:
            return []

        sorted_entries = sorted(self.entries, key=lambda e: e.start_utc_ms)
        faults = []
        for i in range(len(sorted_entries) - 1):
            curr = sorted_entries[i]
            nxt = sorted_entries[i + 1]
            if curr.end_utc_ms != nxt.start_utc_ms:
                faults.append(
                    GapFault(
                        channel_id=self.channel_id,
                        gap_start_ms=curr.end_utc_ms,
                        gap_end_ms=nxt.start_utc_ms,
                        fault_class="runtime",
                    )
                )
        return faults
