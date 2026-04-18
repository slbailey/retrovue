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

from typing import Any, Protocol


class ExecutionRuntimeReader(Protocol):
    """Read-only execution data accessor.

    Runtime authority boundary:
    - reads only precomputed execution blocks / PlaylistEvent rows
    - never compiles, fills, extends, reconciles, or repairs
    """

    def get_current_execution_block(
        self,
        channel_id: str,
        now_ms: int,
    ) -> "Any | None":
        """Return the execution block covering now_ms, or None if missing."""
        ...

    def get_next_execution_block(
        self,
        channel_id: str,
        after_utc_ms: int,
    ) -> "Any | None":
        """Return the next execution block beginning at or after after_utc_ms."""
        ...

    def get_execution_depth_ms(
        self,
        channel_id: str,
        now_ms: int,
    ) -> int:
        """Return forward execution depth in milliseconds."""
        ...

    def get_playlist_event_by_block_id(
        self,
        channel_id: str,
        block_id: str,
    ) -> "Any | None":
        """Return the authoritative execution block for block_id, or None."""
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
