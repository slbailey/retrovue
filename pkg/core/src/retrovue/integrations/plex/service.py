"""
Plex HDHomeRun virtual tuner — service layer.

PlexAdapter translates Plex/HDHomeRun protocol requests into existing
RetroVue service calls. It owns no scheduling, EPG, or playout logic.

Authority boundaries:
  - Channel registry → ProgramDirector._load_channels_list()
  - XMLTV generation → retrovue.web.iptv.generate_xmltv()
  - Stream lifecycle → ProgramDirector.stream_channel() / ChannelManager
  - Producer fanout → ChannelManager (one AIR per channel)
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from retrovue.integrations.plex.models import (
    LINEUP_STATUS,
    make_discover_payload,
    make_lineup_entry,
)
from retrovue.web.iptv import generate_xmltv


# ---------------------------------------------------------------------------
# ProgramDirector protocol (for dependency injection in tests)
# ---------------------------------------------------------------------------


class ChannelManagerLike(Protocol):
    def tune_in(self, session_id: str, session_info: dict[str, Any] | None = None) -> None: ...
    def tune_out(self, session_id: str) -> None: ...


class ProgramDirectorLike(Protocol):
    def get_channel_manager(self, channel_id: str) -> ChannelManagerLike: ...


# ---------------------------------------------------------------------------
# PlexAdapter
# ---------------------------------------------------------------------------


class PlexAdapter:
    """HDHomeRun virtual tuner adapter for Plex integration.

    Pure translation layer — delegates all real work to existing RetroVue
    services. Does not own channels, schedules, EPG, or playout.

    Contracts:
      INV-PLEX-DISCOVERY-001 — /discover.json
      INV-PLEX-LINEUP-001   — /lineup.json
      INV-PLEX-TUNER-STATUS-001 — /lineup_status.json
      INV-PLEX-XMLTV-001    — /epg.xml
      INV-PLEX-STREAM-START-001 — stream start lifecycle
      INV-PLEX-STREAM-DISCONNECT-001 — stream disconnect lifecycle
      INV-PLEX-FANOUT-001   — producer fanout preservation
    """

    def __init__(
        self,
        *,
        channels: list[dict[str, Any]],
        base_url: str,
        epg_entries: list[dict[str, Any]] | None = None,
        program_director: ProgramDirectorLike | None = None,
        device_id: str = "52565545",
        friendly_name: str = "RetroVue",
    ) -> None:
        self._channels = channels
        self._base_url = base_url.rstrip("/")
        self._epg_entries = epg_entries if epg_entries is not None else []
        self._program_director = program_director
        self._device_id = device_id
        self._friendly_name = friendly_name

        # INV-PLEX-STREAM-DISCONNECT-001: Track active sessions so
        # stop_stream is idempotent (exactly one tune_out per tune_in).
        self._active_sessions: dict[str, str] = {}  # session_id → channel_id
        self._session_lock = threading.Lock()

    # -------------------------------------------------------------------
    # Discovery endpoints
    # -------------------------------------------------------------------

    def discover(self) -> dict[str, Any]:
        """INV-PLEX-DISCOVERY-001: HDHomeRun device descriptor."""
        return make_discover_payload(
            base_url=self._base_url,
            tuner_count=len(self._channels),
            device_id=self._device_id,
            friendly_name=self._friendly_name,
        )

    def lineup(self) -> list[dict[str, str]]:
        """INV-PLEX-LINEUP-001: One entry per registered channel."""
        return [
            make_lineup_entry(
                channel_id=ch["channel_id"],
                channel_name=ch["name"],
                base_url=self._base_url,
            )
            for ch in self._channels
        ]

    def lineup_status(self) -> dict[str, Any]:
        """INV-PLEX-TUNER-STATUS-001: Static scan status."""
        return dict(LINEUP_STATUS)

    # -------------------------------------------------------------------
    # Guide data
    # -------------------------------------------------------------------

    def epg_xml(self) -> str:
        """INV-PLEX-XMLTV-001: Delegate to generate_xmltv() — no duplication."""
        return generate_xmltv(self._channels, self._epg_entries)

    # -------------------------------------------------------------------
    # Stream lifecycle
    # -------------------------------------------------------------------

    def start_stream(self, channel_id: str, *, session_id: str) -> None:
        """INV-PLEX-STREAM-START-001: Delegate to ProgramDirector.

        Acquires the ChannelManager via ProgramDirector and calls tune_in.
        The adapter does not spawn AIR or compile schedules.
        """
        if self._program_director is None:
            raise RuntimeError("PlexAdapter: no ProgramDirector configured")

        mgr = self._program_director.get_channel_manager(channel_id)
        mgr.tune_in(session_id, {"channel_id": channel_id, "source": "plex"})

        with self._session_lock:
            self._active_sessions[session_id] = channel_id

    def stop_stream(self, channel_id: str, *, session_id: str) -> None:
        """INV-PLEX-STREAM-DISCONNECT-001: Exactly one tune_out per tune_in.

        Idempotent — second call for the same session_id is a no-op.
        """
        with self._session_lock:
            if session_id not in self._active_sessions:
                return  # Already stopped — idempotent guard
            del self._active_sessions[session_id]

        if self._program_director is None:
            return

        mgr = self._program_director.get_channel_manager(channel_id)
        mgr.tune_out(session_id)
