"""Override Record — INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.

An override record MUST be durably persisted before the override artifact
is committed. This module provides the canonical OverrideRecord type and
an in-memory store for Phase 1.

See: docs/contracts/invariants/core/INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.md
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class OverrideRecord:
    """Durable record of an operator override action."""

    id: int
    layer: str
    target_id: str
    reason_code: str
    created_utc_ms: int


class InMemoryOverrideStore:
    """In-memory override record store.

    Thread-safe. persist() creates and returns an OverrideRecord.
    Set fail_next_persist=True to simulate persistence failure in tests.
    """

    def __init__(self) -> None:
        self._records: list[OverrideRecord] = []
        self._next_id: int = 1
        self._lock = threading.Lock()
        self.fail_next_persist: bool = False

    def persist(
        self,
        layer: str,
        target_id: str,
        reason_code: str,
        now_ms: int,
    ) -> OverrideRecord:
        """Persist an override record. Raises on failure injection."""
        with self._lock:
            if self.fail_next_persist:
                self.fail_next_persist = False
                raise RuntimeError("OVERRIDE_RECORD_PERSIST_FAILED")
            record = OverrideRecord(
                id=self._next_id,
                layer=layer,
                target_id=target_id,
                reason_code=reason_code,
                created_utc_ms=now_ms,
            )
            self._records.append(record)
            self._next_id += 1
            return record

    @property
    def records(self) -> list[OverrideRecord]:
        """Return a copy of all persisted records."""
        with self._lock:
            return list(self._records)
