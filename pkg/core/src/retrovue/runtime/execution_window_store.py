"""Execution Window Store — Read-only execution window for consumers.

Populated by HorizonManager during horizon extension.  Consumers
(e.g. ChannelManager) read from this store; they never trigger
generation.  This enforces the contract principle that automation
consumes pre-built data and never requests planning.

Phase 1: In-memory, no persistence, no eviction.

See: docs/domains/HorizonManager_v0.1.md §6 (Data Flow)
     docs/contracts/ScheduleHorizonManagementContract_v0.1.md §4 (Lock Windows)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Entry type (mirrors TransmissionLogEntry without import dependency)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


@dataclass
class ExecutionEntry:
    """One block's execution-ready data inside the window.

    Structurally identical to TransmissionLogEntry.  Defined here to
    avoid a hard import dependency on the planning pipeline module,
    keeping the store independent of pipeline internals.

    Lineage fields (channel_id, programming_day_date) establish explicit
    traceability to the ResolvedScheduleDay that produced this entry.
    See INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.
    """
    block_id: str
    block_index: int
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict[str, Any]]
    channel_id: str = ""
    programming_day_date: date | None = None
    is_locked: bool = True
    transmission_log_ref: str | None = None
    is_operator_override: bool = False


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

    def __init__(
        self,
        *,
        enforce_derivation_from_playlist: bool = False,
    ) -> None:
        self._entries: list[ExecutionEntry] = []
        self._lock = threading.Lock()
        self._enforce_derivation_from_playlist = enforce_derivation_from_playlist

    # ------------------------------------------------------------------
    # Write (HorizonManager)
    # ------------------------------------------------------------------

    def add_entries(self, entries: list[ExecutionEntry]) -> None:
        """Append entries and maintain sort order.

        Duplicate block_ids are silently ignored (idempotent).

        Raises ValueError if any entry lacks transmission log derivation
        (INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001) when enforcement is enabled.
        Raises ValueError if any entry lacks schedule lineage
        (INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001).
        """
        for entry in entries:
            if self._enforce_derivation_from_playlist:
                if (
                    not entry.is_operator_override
                    and entry.transmission_log_ref is None
                ):
                    raise ValueError(
                        "INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED: "
                        f"ExecutionEntry block_id={entry.block_id!r} has "
                        f"transmission_log_ref=None and is_operator_override=False. "
                        "Every execution artifact must be derived from a "
                        "TransmissionLogEntry or be an explicit operator override."
                    )
            if not entry.channel_id or entry.programming_day_date is None:
                raise ValueError(
                    "INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001-VIOLATED: "
                    f"ExecutionEntry block_id={entry.block_id!r} has "
                    f"channel_id={entry.channel_id!r}, "
                    f"programming_day_date={entry.programming_day_date!r}. "
                    "Every execution artifact must carry explicit schedule lineage."
                )
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

    def get_entry_at(
        self,
        utc_ms: int,
        *,
        locked_only: bool = True,
    ) -> ExecutionEntry | None:
        """Return the entry whose time range contains *utc_ms*.

        An entry matches when ``start_utc_ms <= utc_ms < end_utc_ms``.

        Args:
            utc_ms: Wall-clock instant to look up (epoch milliseconds).
            locked_only: When True (the default), only return entries with
                ``is_locked=True``.  Unlocked entries are treated as if
                they do not exist, and a POLICY_VIOLATION is logged.
                This enforces ScheduleHorizonManagement §4: automation
                must not consume data from the flexible future.
                Defaults to True — callers must explicitly opt out.
        """
        with self._lock:
            for entry in self._entries:
                if entry.start_utc_ms <= utc_ms < entry.end_utc_ms:
                    if locked_only and not entry.is_locked:
                        logger.warning(
                            "POLICY_VIOLATION: Execution entry %s "
                            "(start=%d end=%d) exists but is NOT locked. "
                            "Returning None in authoritative mode.",
                            entry.block_id,
                            entry.start_utc_ms,
                            entry.end_utc_ms,
                        )
                        return None
                    return entry
            return None

    def has_entries_for(
        self,
        channel_id: str,
        programming_day_date: date,
    ) -> bool:
        """Return True if any entry references the given (channel_id, date).

        Used by InMemoryResolvedStore.delete() to enforce
        INV-DERIVATION-ANCHOR-PROTECTED-001: a ScheduleDay with
        downstream execution artifacts must not be deleted.
        """
        with self._lock:
            return any(
                e.channel_id == channel_id
                and e.programming_day_date == programming_day_date
                for e in self._entries
            )

    def mark_locked(self, block_id: str) -> bool:
        """Mark a single entry as locked (execution-eligible).

        Returns True if the entry was found and locked.
        """
        with self._lock:
            for entry in self._entries:
                if entry.block_id == block_id:
                    entry.is_locked = True
                    return True
            return False

    def lock_all(self) -> int:
        """Mark all entries as locked.  Returns count of newly locked entries."""
        count = 0
        with self._lock:
            for entry in self._entries:
                if not entry.is_locked:
                    entry.is_locked = True
                    count += 1
        return count

    def replace_entry(
        self,
        block_id: str,
        new_entry: ExecutionEntry,
        *,
        now_utc_ms: int,
        override_record_id: str | None = None,
    ) -> None:
        """Replace an existing entry by block_id, enforcing immutability guards.

        Guards (INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001):
        1. Past window: if existing entry's end_utc_ms <= now_utc_ms, the entry
           has already aired. Mutation is unconditionally rejected (no override).
        2. Locked without override: if existing entry is_locked and no
           override_record_id is provided, mutation is rejected.
        3. Otherwise: replace the entry and re-sort.
        """
        with self._lock:
            idx = None
            for i, entry in enumerate(self._entries):
                if entry.block_id == block_id:
                    idx = i
                    break
            if idx is None:
                raise ValueError(
                    f"ExecutionEntry block_id={block_id!r} not found in store."
                )

            existing = self._entries[idx]

            # Guard 1: past window — unconditional rejection
            if existing.end_utc_ms <= now_utc_ms:
                raise ValueError(
                    "INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001-VIOLATED: "
                    f"ExecutionEntry block_id={block_id!r} is in the past "
                    f"window (end_utc_ms={existing.end_utc_ms} <= "
                    f"now_utc_ms={now_utc_ms}). "
                    f"Window status: \"past\". "
                    "Past-window entries MUST NOT be mutated under any "
                    "circumstance."
                )

            # Guard 2: locked without override
            if existing.is_locked and override_record_id is None:
                raise ValueError(
                    "INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001-VIOLATED: "
                    f"ExecutionEntry block_id={block_id!r} is locked. "
                    f"Window status: \"locked\". "
                    "Locked entries require an override_record_id for "
                    "mutation."
                )

            # Replace and re-sort
            self._entries[idx] = new_entry
            self._entries.sort(key=lambda e: e.start_utc_ms)


# ---------------------------------------------------------------------------
# Standalone validation functions
# ---------------------------------------------------------------------------


def validate_execution_entry_contiguity(entries: list[ExecutionEntry]) -> None:
    """Validate that ExecutionEntry sequence has no temporal gaps.

    Raises ValueError with tag INV-EXECUTIONENTRY-NO-GAPS-001-VIOLATED if any
    consecutive pair has a gap (entries[i].end_utc_ms != entries[i+1].start_utc_ms).

    Empty or single-entry lists pass trivially.
    """
    if len(entries) <= 1:
        return

    sorted_entries = sorted(entries, key=lambda e: e.start_utc_ms)
    for i in range(len(sorted_entries) - 1):
        current = sorted_entries[i]
        next_entry = sorted_entries[i + 1]
        if current.end_utc_ms != next_entry.start_utc_ms:
            raise ValueError(
                "INV-EXECUTIONENTRY-NO-GAPS-001-VIOLATED: "
                f"Gap detected in ExecutionEntry sequence for "
                f"channel_id={current.channel_id!r}. "
                f"Entry block_id={current.block_id!r} ends at "
                f"{current.end_utc_ms} but next entry "
                f"block_id={next_entry.block_id!r} starts at "
                f"{next_entry.start_utc_ms}. "
                f"Gap: [{current.end_utc_ms}, {next_entry.start_utc_ms}]."
            )
