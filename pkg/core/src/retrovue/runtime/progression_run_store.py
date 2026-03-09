"""Progression Run Store — persistence layer for episode progression runs.

Contract: docs/contracts/episode_progression.md § Progression Run Model

Provides load/create semantics for ProgressionRun records.  The store
is threaded through the schedule compilation pipeline so that
_apply_sequential_progression can resolve anchors from persistence
instead of using a bootstrap epoch.

Three implementations:

    InMemoryProgressionRunStore  — tests and ephemeral compilation
    DbProgressionRunStore        — production (Postgres)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, time
from typing import Protocol

from retrovue.runtime.serial_episode_resolver import SerialRunInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ProgressionRunStore(Protocol):
    """Abstract store for ProgressionRun records.

    Implementations must be safe to call multiple times for the same
    (channel_id, run_id) within a single compilation — load returns
    the previously created run without re-creating it.
    """

    def load(self, channel_id: str, run_id: str) -> SerialRunInfo | None:
        """Load an active ProgressionRun by (channel_id, run_id).

        Returns a SerialRunInfo snapshot, or None if no active run exists.
        """
        ...

    def create(
        self,
        *,
        channel_id: str,
        run_id: str,
        content_source_id: str,
        anchor_date: date,
        anchor_episode_index: int,
        placement_days: int,
        exhaustion_policy: str,
    ) -> SerialRunInfo:
        """Create and persist a new ProgressionRun.  Returns a snapshot."""
        ...


# ---------------------------------------------------------------------------
# In-memory implementation (tests and ephemeral compilation)
# ---------------------------------------------------------------------------


class InMemoryProgressionRunStore:
    """In-process store for schedule compilation without a database.

    Used by tests and by callers that don't provide a DB-backed store.
    Records persist for the lifetime of this object only.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], SerialRunInfo] = {}

    def load(self, channel_id: str, run_id: str) -> SerialRunInfo | None:
        return self._runs.get((channel_id, run_id))

    def create(
        self,
        *,
        channel_id: str,
        run_id: str,
        content_source_id: str,
        anchor_date: date,
        anchor_episode_index: int,
        placement_days: int,
        exhaustion_policy: str,
    ) -> SerialRunInfo:
        info = SerialRunInfo(
            channel_id=channel_id,
            placement_time=time(0, 0),
            placement_days=placement_days,
            content_source_id=content_source_id,
            anchor_date=anchor_date,
            anchor_episode_index=anchor_episode_index,
            wrap_policy=exhaustion_policy,
        )
        self._runs[(channel_id, run_id)] = info
        return info


# ---------------------------------------------------------------------------
# Database implementation (production)
# ---------------------------------------------------------------------------


class DbProgressionRunStore:
    """Postgres-backed store using the progression_runs table.

    Requires an active SQLAlchemy Session.  Writes are committed by
    the caller's Unit of Work boundary (``with session() as db:``).
    """

    def __init__(self, db: object) -> None:
        # Accept any SQLAlchemy Session-like object.
        self._db = db

    def load(self, channel_id: str, run_id: str) -> SerialRunInfo | None:
        from sqlalchemy import select
        from retrovue.domain.entities import ProgressionRun

        stmt = select(ProgressionRun).where(
            ProgressionRun.channel_id == channel_id,
            ProgressionRun.run_id == run_id,
            ProgressionRun.is_active.is_(True),
        )
        row = self._db.scalar(stmt)
        if row is None:
            return None

        return SerialRunInfo(
            channel_id=row.channel_id,
            placement_time=time(0, 0),
            placement_days=row.placement_days,
            content_source_id=row.content_source_id,
            anchor_date=row.anchor_date,
            anchor_episode_index=row.anchor_episode_index,
            wrap_policy=row.exhaustion_policy,
        )

    def create(
        self,
        *,
        channel_id: str,
        run_id: str,
        content_source_id: str,
        anchor_date: date,
        anchor_episode_index: int,
        placement_days: int,
        exhaustion_policy: str,
    ) -> SerialRunInfo:
        from retrovue.domain.entities import ProgressionRun

        row = ProgressionRun(
            run_id=run_id,
            channel_id=channel_id,
            content_source_id=content_source_id,
            anchor_date=anchor_date,
            anchor_episode_index=anchor_episode_index,
            placement_days=placement_days,
            exhaustion_policy=exhaustion_policy,
            is_active=True,
        )
        self._db.add(row)
        self._db.flush()

        logger.info(
            "Created ProgressionRun: channel=%s run_id=%s anchor=%s days=%s policy=%s",
            channel_id, run_id, anchor_date.isoformat(),
            placement_days, exhaustion_policy,
        )

        return SerialRunInfo(
            channel_id=channel_id,
            placement_time=time(0, 0),
            placement_days=placement_days,
            content_source_id=content_source_id,
            anchor_date=anchor_date,
            anchor_episode_index=anchor_episode_index,
            wrap_policy=exhaustion_policy,
        )
