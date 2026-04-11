"""
RetroVue runtime protocols.

Single source for structural contracts shared across runtime modules.
These Protocols define the interface boundaries — they are NOT implementations.

Authority: channel_manager.py was the original home; moved here to enforce
the rule that production modules contain only production code and shared
contracts live in dedicated boundary modules.

INV-PRODUCTION-BOUNDARY-001: This module contains only Protocol definitions.
No implementations, no test harnesses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class ScheduleService(Protocol):
    """Read-only schedule accessor.

    Implementations: DslScheduleService (production), MockGridScheduleService,
    MockAlternatingScheduleService (retrovue.dev), FakeScheduleService (tests).
    Authority: retrovue/runtime/protocols.py
    """

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return the resolved segment sequence that should be airing 'right now' on this channel.

        Must include correct timing offsets so we can join mid-program instead of restarting at frame 0.
        Must NOT mutate schedule state.
        """
        ...

    def get_block_at(self, channel_id: str, utc_ms: int) -> "Any | None":
        """Return the fully constructed block covering the given wall-clock time.

        READ-ONLY: This is a pure query over pre-built horizon data.
        It MUST NOT trigger schedule generation, pipeline execution, or grid rebuild.
        It MAY perform idempotent day resolution (INV-P5-002) in legacy mode.

        Returns ScheduledBlock or None (planning failure).
        """
        ...


class ProgramDirectorProtocol(Protocol):
    """Global policy/mode provider.

    This Protocol is the structural contract used by ChannelManager to query
    ProgramDirector for mode decisions. It is intentionally minimal.

    Authority: retrovue/runtime/protocols.py
    """

    def get_channel_mode(self, channel_id: str) -> str:
        """
        Return the required mode for this channel: "normal", "emergency", "guide", etc.
        ChannelManager is not allowed to make this decision on its own.
        """
        ...
