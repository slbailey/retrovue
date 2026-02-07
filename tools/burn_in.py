#!/usr/bin/env python3
"""
Standalone burn-in harness for Playlist-driven ChannelManager.

Assembles the ProgramDirector runtime stack, injects a Playlist from
PlaylistScheduleManager into a ChannelManager, and starts the HTTP server
so you can point VLC at http://localhost:8000/channel/retrovue-classic.ts
for overnight burn-in testing with real media.

Usage:
    source pkg/core/.venv/bin/activate
    python tools/burn_in.py

Environment variables:
    RETROVUE_BURN_IN_HOURS  — playlist window duration (default: 24)
    RETROVUE_BURN_IN_PORT   — HTTP server port (default: 8000)
"""

import logging
import os
import signal
import threading
from datetime import datetime, timedelta, timezone

from retrovue.runtime.config import (
    ChannelConfig,
    DEFAULT_PROGRAM_FORMAT,
    InlineChannelConfigProvider,
)
from retrovue.runtime.program_director import ProgramDirector
from retrovue.scheduling.playlist_schedule_manager import PlaylistScheduleManager

CHANNEL_ID = "retrovue-classic"

logger = logging.getLogger("burn_in")


class _BurnInScheduleService:
    """Stub schedule service. Never used for playout — the Playlist path overrides it."""

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        return (True, None)

    def get_playout_plan_now(
        self, channel_id: str, at_station_time: datetime
    ) -> list[dict]:
        return []


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    burn_in_hours = int(os.environ.get("RETROVUE_BURN_IN_HOURS", "24"))
    port = int(os.environ.get("RETROVUE_BURN_IN_PORT", "8000"))

    # 1. Build Playlist
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=burn_in_hours)
    logger.info("Generating playlist: %s → %s (%dh)", now, end, burn_in_hours)

    psm = PlaylistScheduleManager()
    playlists = psm.get_playlists(CHANNEL_ID, now, end)
    playlist = playlists[0]
    logger.info(
        "Playlist: %d segments, %s → %s",
        len(playlist.segments),
        playlist.window_start_at,
        playlist.window_end_at,
    )

    # 2. Create ProgramDirector in embedded mode with our channel config
    config = ChannelConfig(
        channel_id=CHANNEL_ID,
        channel_id_int=1,
        name="RetroVue Classic (burn-in)",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="burn-in",
    )
    provider = InlineChannelConfigProvider([config])

    pd = ProgramDirector(
        channel_config_provider=provider,
        port=port,
    )

    # 3. Replace schedule service with stub
    pd._schedule_service = _BurnInScheduleService()

    # 4. Pre-create manager and inject playlist
    manager = pd._get_or_create_manager(CHANNEL_ID)
    manager.load_playlist(playlist)
    logger.info("Playlist loaded into ChannelManager for %s", CHANNEL_ID)

    # 5. Start runtime (HTTP server + health loop + pacing)
    pd.start()

    url = f"http://localhost:{port}/channel/{CHANNEL_ID}.ts"
    logger.info("Burn-in running. Connect with:")
    logger.info("  vlc %s", url)
    logger.info("Press Ctrl+C to stop.")

    # 6. Block until signal
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    stop_event.wait()

    logger.info("Shutting down...")
    pd.stop()
    logger.info("Done.")


if __name__ == "__main__":
    main()
