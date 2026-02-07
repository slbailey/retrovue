#!/usr/bin/env python3
"""
Standalone burn-in harness using the Canonical AIR Bootstrap Path.

Uses the EXACT SAME bootstrap pattern as verify_first_on_air --server:
  BlockPlanProducer + PlayoutSession
  gRPC: GetVersion → AttachStream → StartBlockPlanSession → SubscribeBlockEvents → FeedBlockPlan

The Playlist from PlaylistScheduleManager is consumed ONLY by a schedule-service
adapter that returns playout-plan dicts.  manager._playlist is NEVER set.

Usage:
    source pkg/core/.venv/bin/activate
    python tools/burn_in.py

Environment variables:
    RETROVUE_BURN_IN_HOURS  — playlist window duration (default: 24)
    RETROVUE_BURN_IN_PORT   — HTTP server port (default: 8000)
    RETROVUE_BURN_IN_TEST_ASSETS — set to "1" to use SampleA/B instead of playlist
"""

import logging
import os
import signal
import threading
from datetime import datetime, timedelta, timezone

from retrovue.runtime.config import (
    ChannelConfig,
    InlineChannelConfigProvider,
    ProgramFormat,
)
from retrovue.runtime.program_director import ProgramDirector
from retrovue.scheduling.playlist_schedule_manager import PlaylistScheduleManager

CHANNEL_ID = "retrovue-classic"

logger = logging.getLogger("burn_in")


# =============================================================================
# Schedule-service adapter: exposes the full Playlist as playout-plan dicts.
# BlockPlanProducer consumes this list and cycles round-robin.
# =============================================================================

class _TestAssetScheduleService:
    """Same assets as verify_first_on_air: SampleA.mp4 and SampleB.mp4.

    Used with RETROVUE_BURN_IN_TEST_ASSETS=1 to isolate bootstrap/pipeline
    behavior from content-specific issues.
    """

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return [
            {
                "asset_path": "/opt/retrovue/assets/SampleA.mp4",
                "asset_start_offset_ms": 0,
                "segment_type": "content",
            },
            {
                "asset_path": "/opt/retrovue/assets/SampleB.mp4",
                "asset_start_offset_ms": 0,
                "segment_type": "content",
            },
        ]

    def load_schedule(self, channel_id: str):
        return True, None


class _PlaylistScheduleAdapter:
    """Translates a Playlist into playout-plan entries for BlockPlanProducer.

    The full playlist.segments list is returned from get_playout_plan_now().
    BlockPlanProducer retains this list at start time and cycles through it
    round-robin via _generate_next_block().  No slicing, no shortcuts.
    """

    def __init__(self, playlist):
        if not playlist.segments:
            raise RuntimeError(
                "BURN_IN: Playlist has zero segments.  Cannot proceed."
            )
        self._entries = [
            {
                "asset_path": seg.asset_path,
                "asset_start_offset_ms": 0,
                "segment_type": seg.type if hasattr(seg, "type") else "content",
                "duration_ms": int(seg.duration_seconds * 1000),
            }
            for seg in playlist.segments
        ]
        logger.info(
            "BURN_IN: Schedule adapter created with %d entries from playlist",
            len(self._entries),
        )

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return self._entries

    def load_schedule(self, channel_id: str):
        return True, None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    burn_in_hours = int(os.environ.get("RETROVUE_BURN_IN_HOURS", "24"))
    port = int(os.environ.get("RETROVUE_BURN_IN_PORT", "8000"))
    use_test_assets = os.environ.get("RETROVUE_BURN_IN_TEST_ASSETS", "") == "1"

    # =========================================================================
    # 1. Build schedule service (consumed ONLY by BlockPlanProducer, never
    #    loaded into ChannelManager)
    # =========================================================================
    if use_test_assets:
        # Use SampleA/SampleB — same assets as verify_first_on_air.
        # Isolates bootstrap/pipeline behavior from content-specific issues.
        logger.info("BURN_IN: Using test assets (SampleA.mp4, SampleB.mp4)")
        schedule_service = _TestAssetScheduleService()
    else:
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=burn_in_hours)
        logger.info("Generating playlist: %s -> %s (%dh)", now, end, burn_in_hours)

        psm = PlaylistScheduleManager()
        playlists = psm.get_playlists(CHANNEL_ID, now, end)
        playlist = playlists[0]
        logger.info(
            "Playlist: %d segments, %s -> %s",
            len(playlist.segments),
            playlist.window_start_at,
            playlist.window_end_at,
        )

        schedule_service = _PlaylistScheduleAdapter(playlist)

    # =========================================================================
    # 2. Create ProgramDirector in embedded mode
    # =========================================================================
    # Use 640x480@30fps — same as verify_first_on_air.
    # DEFAULT_PROGRAM_FORMAT is 1920x1080 which software x264 cannot encode
    # in real-time, causing periodic stutter from encoder backpressure.
    program_format = ProgramFormat(
        video_width=640,
        video_height=480,
        frame_rate="30/1",
        audio_sample_rate=48000,
        audio_channels=2,
    )

    channel_config = ChannelConfig(
        channel_id=CHANNEL_ID,
        channel_id_int=1,
        name="RetroVue Classic (burn-in)",
        program_format=program_format,
        schedule_source="mock",
    )
    provider = InlineChannelConfigProvider([channel_config])

    director = ProgramDirector(
        channel_config_provider=provider,
        port=port,
    )

    # ProgramDirector._get_or_create_manager calls load_schedule() on the
    # default schedule service BEFORE our monkey-patch hook runs.  The built-in
    # Phase8MockScheduleService only accepts channel "mock".  Replace it so
    # load_schedule("retrovue-classic") succeeds.
    director._schedule_service = schedule_service

    # =========================================================================
    # 3. Canonical bootstrap hook — EXACT same pattern as verify_first_on_air
    #    lines 115-166
    # =========================================================================
    from retrovue.runtime.channel_manager import BlockPlanProducer

    original_get_or_create = director._get_or_create_manager

    def get_or_create_with_blockplan(channel_id: str):
        manager = original_get_or_create(channel_id)

        if hasattr(manager, "set_blockplan_mode") and not getattr(
            manager, "_blockplan_mode", False
        ):
            manager.set_blockplan_mode(True)

            # Override schedule service with our playlist adapter
            manager.schedule_service = schedule_service

            # Override producer factory to return BlockPlanProducer
            def build_blockplan_producer(mode: str, mgr=manager, ch_config=channel_config):
                logger.info(
                    "BURN_IN: Building BlockPlanProducer for channel %s (canonical path)",
                    channel_id,
                )
                return BlockPlanProducer(
                    channel_id=channel_id,
                    configuration={"block_duration_ms": 30_000},
                    channel_config=ch_config,
                    schedule_service=schedule_service,
                    clock=mgr.clock,
                )

            manager._build_producer_for_mode = build_blockplan_producer

            # =================================================================
            # TRIPWIRE 1: manager._playlist must NEVER be set.
            # Monkey-patch load_playlist to raise immediately.
            # =================================================================
            def _forbidden_load_playlist(*args, **kwargs):
                raise RuntimeError(
                    "TRIPWIRE: manager.load_playlist() called during burn_in. "
                    "manager._playlist must remain None.  burn_in uses the "
                    "canonical BlockPlanProducer path exclusively."
                )

            manager.load_playlist = _forbidden_load_playlist

            # =================================================================
            # TRIPWIRE 2: _ensure_producer_running_playlist must never execute.
            # =================================================================
            def _forbidden_playlist_path(*args, **kwargs):
                raise RuntimeError(
                    "TRIPWIRE: _ensure_producer_running_playlist called during "
                    "burn_in.  This means manager._playlist was set, which is "
                    "FORBIDDEN.  burn_in MUST use the canonical BlockPlanProducer "
                    "path."
                )

            manager._ensure_producer_running_playlist = _forbidden_playlist_path

            # =================================================================
            # TRIPWIRE 3: Assert _playlist is None right now.
            # =================================================================
            if getattr(manager, "_playlist", None) is not None:
                raise RuntimeError(
                    "TRIPWIRE: manager._playlist is already set after "
                    "_get_or_create_manager.  This violates the canonical "
                    "bootstrap path."
                )

            logger.info(
                "BURN_IN: Canonical bootstrap enabled for channel %s "
                "(BlockPlanProducer, _playlist=None, tripwires armed)",
                channel_id,
            )
        return manager

    director._get_or_create_manager = get_or_create_with_blockplan

    # =========================================================================
    # 4. Start runtime (HTTP server + health loop + pacing)
    #    ChannelManager is created LAZILY on first HTTP request, same as
    #    verify_first_on_air.
    # =========================================================================
    director.start()

    url = f"http://localhost:{port}/channel/{CHANNEL_ID}.ts"
    logger.info("Burn-in running.  Connect with:")
    logger.info("  vlc %s", url)
    logger.info("  ffplay -fflags nobuffer -flags low_delay %s", url)
    logger.info("Press Ctrl+C to stop.")

    # =========================================================================
    # 5. Block until signal
    # =========================================================================
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    stop_event.wait()

    logger.info("Shutting down...")
    director.stop()
    logger.info("Done.")


if __name__ == "__main__":
    main()
