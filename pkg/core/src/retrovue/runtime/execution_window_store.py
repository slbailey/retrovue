"""Execution Window Store — Read-only execution window for consumers.

Populated by HorizonManager during horizon extension.  Consumers
(e.g. ChannelManager) read from this store; they never trigger
generation.  This enforces the contract principle that automation
consumes pre-built data and never requests planning.

Phase 1: In-memory, no persistence, no eviction.

See: docs/domains/HorizonManager_v0.1.md §6 (Data Flow)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Entry type (mirrors TransmissionLogEntry without import dependency)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionEntry:
    """One block's execution-ready data inside the window.

    Structurally identical to TransmissionLogEntry.  Defined here to
    avoid a hard import dependency on the planning pipeline module,
    keeping the store independent of pipeline internals.
    """
    block_id: str
    block_index: int
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict[str, Any]]


@dataclass
class ExecutionDayResult:
    """Rich return type from ExecutionExtender when store population is needed.

    Carries both the end_utc_ms (for HorizonManager's depth tracking)
    and the entries (for store population).  Legacy implementations
    may still return a plain int; HorizonManager handles both.
    """
    end_utc_ms: int
    entries: list[ExecutionEntry]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ExecutionWindowStore:
    """Read-only execution window for consumers; populated by HorizonManager.

    Thread-safe.  Entries are maintained in start_utc_ms order.

    Write path (HorizonManager only):
        add_entries(entries)

    Read path (consumers):
        get_next_entry(after_utc_ms)
        get_window_start()
        get_window_end()
        get_all_entries()
    """

    def __init__(self) -> None:
        self._entries: list[ExecutionEntry] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write (HorizonManager)
    # ------------------------------------------------------------------

    def add_entries(self, entries: list[ExecutionEntry]) -> None:
        """Append entries and maintain sort order.

        Duplicate block_ids are silently ignored (idempotent).
        """
        with self._lock:
            existing_ids = {e.block_id for e in self._entries}
            new = [e for e in entries if e.block_id not in existing_ids]
            if not new:
                return
            self._entries.extend(new)
            self._entries.sort(key=lambda e: e.start_utc_ms)

    # ------------------------------------------------------------------
    # Read (consumers)
    # ------------------------------------------------------------------

    def get_next_entry(self, after_utc_ms: int) -> ExecutionEntry | None:
        """Return the first entry starting strictly after *after_utc_ms*.

        Returns None if no such entry exists.
        """
        with self._lock:
            for entry in self._entries:
                if entry.start_utc_ms > after_utc_ms:
                    return entry
            return None

    def get_window_start(self) -> int:
        """Return start_utc_ms of the earliest entry, or 0 if empty."""
        with self._lock:
            if not self._entries:
                return 0
            return self._entries[0].start_utc_ms

    def get_window_end(self) -> int:
        """Return end_utc_ms of the latest entry, or 0 if empty."""
        with self._lock:
            if not self._entries:
                return 0
            return self._entries[-1].end_utc_ms

    def get_all_entries(self) -> list[ExecutionEntry]:
        """Return a shallow copy of all entries, sorted by start_utc_ms."""
        with self._lock:
            return list(self._entries)
