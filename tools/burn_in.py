#!/usr/bin/env python3
"""
Standalone burn-in harness using the Canonical AIR Bootstrap Path.

Block model (30-minute, wall-clock aligned):
  Every block is exactly 30 minutes, aligned to hh:00:00 / hh:30:00 UTC.
  Three segment types fill the block with zero gaps:

    [ episode ][ filler ][ pad (10 s) ]
    |<--- sum(segment_duration_ms) == 1,800,000 --->|

  Episode:  real asset, plays first (full length or JIP-seeked)
  Filler:   real asset, fills time from episode end to T-10 s
  Pad:      planned segment (segment_type="pad"), NOT an asset —
            no asset_uri, no decoder probe, no internal:// URI.

  When serialized to AIR, only asset segments (episode + filler) are
  included.  Content exhausts 10 s before the fence; PadProducer fills
  the remaining ticks via INV-TICK-GUARANTEED-OUTPUT.  The plan
  predicted this; the runtime executes it.

  Invariant: sum(segment_duration_ms for all segments) == block_duration_ms

JIP:
  All entries carry duration_ms = BLOCK_DURATION_MS so compute_jip_position
  walks 30-minute blocks.  Three JIP cases:
    offset < episode_duration  → seek episode, filler + pad follow
    offset < episode + filler  → skip episode, seek filler, pad follows
    offset >= episode + filler → skip episode + filler, pad only

Usage:
    source pkg/core/.venv/bin/activate
    python tools/burn_in.py [--schedule PATH]

Arguments:
    --schedule PATH  -- static schedule JSON (default: tools/static_schedule.json)

Environment variables:
    RETROVUE_BURN_IN_PORT        -- HTTP server port (default: 8000)
    RETROVUE_BURN_IN_TEST_ASSETS -- "1" to use SampleA/B instead of playlist
    RETROVUE_BURN_IN_FILLER      -- filler asset path (default: assets/filler.mp4)
"""

import argparse
import json
import logging
import os
import signal
import threading
from pathlib import Path

from retrovue.runtime.config import (
    ChannelConfig,
    InlineChannelConfigProvider,
    ProgramFormat,
)
from retrovue.runtime.program_director import ProgramDirector

CHANNEL_ID = "retrovue-classic"

# ---------------------------------------------------------------------------
# Block timing
# ---------------------------------------------------------------------------
BLOCK_DURATION_MS = 30 * 60 * 1000                             # 1,800,000 ms
PAD_TAIL_MS = 10_000                                            # 10 s
PLANNED_WINDOW_MS = BLOCK_DURATION_MS - PAD_TAIL_MS             # 1,790,000 ms

FILLER_PATH = os.environ.get(
    "RETROVUE_BURN_IN_FILLER",
    "/opt/retrovue/assets/filler.mp4",
)

logger = logging.getLogger("burn_in")


# ===========================================================================
# Schedule adapters
# ===========================================================================
# Every entry carries duration_ms = BLOCK_DURATION_MS so that
# compute_jip_position() walks 30-minute blocks.  episode_duration_ms
# carries real content length for the block composer.
# ===========================================================================

class _TestAssetScheduleService:
    """SampleA/SampleB for pipeline isolation testing.

    No episode_duration_ms — segment_duration_ms is set to
    PLANNED_WINDOW_MS and content plays until EOF.  Filler and pad
    account for the rest.
    """

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return [
            {
                "asset_path": "/opt/retrovue/assets/SampleA.mp4",
                "asset_start_offset_ms": 0,
                "segment_type": "content",
                "duration_ms": BLOCK_DURATION_MS,
            },
            {
                "asset_path": "/opt/retrovue/assets/SampleB.mp4",
                "asset_start_offset_ms": 0,
                "segment_type": "content",
                "duration_ms": BLOCK_DURATION_MS,
            },
        ]

    def load_schedule(self, channel_id: str):
        return True, None


class _StaticScheduleAdapter:
    """Load a static schedule JSON and serve it as a playout plan.

    The JSON must contain an "episodes" array where each entry has
    at minimum "asset_path" and "duration_ms" (episode duration in ms).

    The same file is used for every day — the schedule is day-independent.
    """

    def __init__(self, schedule_path: str):
        path = Path(schedule_path)
        if not path.is_file():
            raise RuntimeError(
                f"BURN_IN: Schedule file not found: {schedule_path}"
            )

        with open(path) as f:
            data = json.load(f)

        episodes = data.get("episodes")
        if not episodes:
            raise RuntimeError(
                f"BURN_IN: Schedule file has no episodes: {schedule_path}"
            )

        self._entries = []
        for ep in episodes:
            ep_ms = ep["duration_ms"]
            if ep_ms > PLANNED_WINDOW_MS:
                logger.warning(
                    "BURN_IN: %s (%d ms) exceeds planned window (%d ms) "
                    "— episode truncated to preserve %d ms pad",
                    ep["asset_path"], ep_ms, PLANNED_WINDOW_MS, PAD_TAIL_MS,
                )
            self._entries.append({
                "asset_path": ep["asset_path"],
                "asset_start_offset_ms": ep.get("asset_start_offset_ms", 0),
                "segment_type": ep.get("segment_type", "content"),
                "duration_ms": BLOCK_DURATION_MS,
                "episode_duration_ms": ep_ms,
            })
        logger.info(
            "BURN_IN: Static schedule loaded: %s (%d episodes, "
            "30-min blocks, %d ms pad, filler=%s)",
            schedule_path, len(self._entries), PAD_TAIL_MS, FILLER_PATH,
        )

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        return self._entries

    def load_schedule(self, channel_id: str):
        return True, None


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="RetroVue burn-in harness")
    parser.add_argument(
        "--schedule",
        default="tools/static_schedule.json",
        help="Path to static schedule JSON (default: tools/static_schedule.json)",
    )
    args = parser.parse_args()

    port = int(os.environ.get("RETROVUE_BURN_IN_PORT", "8000"))
    use_test_assets = os.environ.get("RETROVUE_BURN_IN_TEST_ASSETS", "") == "1"

    logger.info(
        "BURN_IN: block=%d ms, planned_window=%d ms, pad=%d ms",
        BLOCK_DURATION_MS, PLANNED_WINDOW_MS, PAD_TAIL_MS,
    )
    has_filler = os.path.isfile(FILLER_PATH)
    if not has_filler:
        logger.warning(
            "BURN_IN: Filler not found: %s — pad starts after episode",
            FILLER_PATH,
        )

    # =====================================================================
    # 1. Build schedule service
    # =====================================================================
    cycle_origin_utc_ms = 0

    if use_test_assets:
        logger.info("BURN_IN: Using test assets (SampleA.mp4, SampleB.mp4)")
        schedule_service = _TestAssetScheduleService()
    else:
        schedule_service = _StaticScheduleAdapter(args.schedule)

    # =====================================================================
    # 2. Create ProgramDirector
    # =====================================================================
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
        schedule_config={"cycle_origin_utc_ms": cycle_origin_utc_ms},
        blockplan_only=True,
    )
    provider = InlineChannelConfigProvider([channel_config])

    director = ProgramDirector(
        channel_config_provider=provider,
        port=port,
    )
    director._schedule_service = schedule_service

    # =====================================================================
    # 3. Canonical bootstrap hook
    # =====================================================================
    from retrovue.runtime.channel_manager import BlockPlanProducer

    original_get_or_create = director._get_or_create_manager

    def get_or_create_with_blockplan(channel_id: str):
        manager = original_get_or_create(channel_id)

        if hasattr(manager, "set_blockplan_mode") and not getattr(
            manager, "_blockplan_mode", False
        ):
            manager.set_blockplan_mode(True)
            manager.schedule_service = schedule_service

            def build_blockplan_producer(
                mode: str, mgr=manager, ch_config=channel_config
            ):
                logger.info(
                    "BURN_IN: Building BlockPlanProducer for %s "
                    "(30-min wall-clock blocks)",
                    channel_id,
                )
                producer = BlockPlanProducer(
                    channel_id=channel_id,
                    configuration={"block_duration_ms": BLOCK_DURATION_MS},
                    channel_config=ch_config,
                    schedule_service=schedule_service,
                    clock=mgr.clock,
                )

                # -------------------------------------------------------
                # _compose_block: replaces _generate_next_block
                #
                # Builds a gap-free plan of exactly block_dur_ms:
                #
                #   [ episode ][ filler ][ pad ]
                #
                # All three segment types are in the plan (for the
                # duration invariant).  Only asset segments (episode,
                # filler) go into the BlockPlan proto — pad has no
                # asset_uri and never reaches a decoder.
                # -------------------------------------------------------
                _ch_id_str = channel_id
                _ch_id_int = ch_config.channel_id_int

                def _compose_block(playout_plan, *, jip_offset_ms=0):
                    from retrovue.runtime.playout_session import BlockPlan

                    idx = producer._block_index
                    start_ms = producer._next_block_start_ms
                    entry = playout_plan[idx % len(playout_plan)]

                    ep_path = entry["asset_path"]
                    ep_total_ms = entry.get(
                        "episode_duration_ms", PLANNED_WINDOW_MS
                    )
                    # Cap episode to planned window so pad is guaranteed.
                    ep_total_ms = min(ep_total_ms, PLANNED_WINDOW_MS)

                    # INV-JIP-WALLCLOCK-001: Block duration is NEVER reduced.
                    # JIP only affects content offsets within the block;
                    # the block container is always exactly BLOCK_DURATION_MS.
                    # The pad segment absorbs any extra time from JIP.
                    block_dur_ms = BLOCK_DURATION_MS

                    end_ms = start_ms + block_dur_ms

                    # ---- INV-BLOCK-ALIGNMENT-001: Wall-clock boundary ----
                    # block.start_utc_ms must sit on a :00/:30 UTC boundary.
                    # Checked for ALL blocks including JIP.  JIP only affects
                    # content offsets within the block, never block boundaries.
                    if cycle_origin_utc_ms > 0:
                        grid_offset = start_ms - cycle_origin_utc_ms
                        if grid_offset >= 0:
                            assert grid_offset % BLOCK_DURATION_MS == 0, (
                                f"BURN_IN: block start_utc_ms={start_ms} not "
                                f"aligned to 30-min boundary "
                                f"(grid_offset={grid_offset}, "
                                f"cycle_origin={cycle_origin_utc_ms})"
                            )

                    # JIP diagnostic (non-asserting)
                    if jip_offset_ms > 0:
                        logger.info(
                            "BURN_IN: JIP block idx=%d "
                            "jip_offset_ms=%d (%.1fs into block)",
                            idx, jip_offset_ms, jip_offset_ms / 1000.0,
                        )

                    # Filler occupies [episode_end .. episode_end + filler_ms]
                    # within the full 30-min block timeline.  Its total
                    # allocation (before JIP) is the gap between episode and
                    # the pad zone.
                    filler_total_ms = PLANNED_WINDOW_MS - ep_total_ms

                    # ----- Place segments for this (possibly JIP) block -----
                    plan_segments = []
                    placed_ms = 0

                    # Phase boundaries within the original 30-min block:
                    #   [0 .. ep_total_ms)              = episode
                    #   [ep_total_ms .. PLANNED_WINDOW)  = filler
                    #   [PLANNED_WINDOW .. BLOCK_DUR)     = pad

                    # Episode
                    if jip_offset_ms < ep_total_ms:
                        ep_offset = jip_offset_ms if jip_offset_ms > 0 else 0
                        ep_remaining = ep_total_ms - ep_offset
                        # Content budget is always block_dur_ms (the whole
                        # block); we place segments in order and pad absorbs
                        # whatever is left (including any JIP gap).
                        ep_seg_ms = ep_remaining
                        plan_segments.append({
                            "segment_type": "episode",
                            "segment_index": 0,
                            "asset_uri": ep_path,
                            "asset_start_offset_ms": ep_offset,
                            "segment_duration_ms": ep_seg_ms,
                        })
                        placed_ms += ep_seg_ms
                    else:
                        ep_seg_ms = 0

                    # Filler
                    if filler_total_ms > 0 and has_filler:
                        if jip_offset_ms <= ep_total_ms:
                            # JIP was inside (or before) the episode —
                            # filler plays from its beginning.
                            filler_offset = 0
                            filler_seg_ms = filler_total_ms
                        elif jip_offset_ms < ep_total_ms + filler_total_ms:
                            # JIP is inside the filler zone.
                            filler_offset = jip_offset_ms - ep_total_ms
                            filler_seg_ms = filler_total_ms - filler_offset
                        else:
                            # JIP is past filler (in pad zone).
                            filler_offset = 0
                            filler_seg_ms = 0

                        if filler_seg_ms > 0:
                            plan_segments.append({
                                "segment_type": "filler",
                                "segment_index": len(plan_segments),
                                "asset_uri": FILLER_PATH,
                                "asset_start_offset_ms": filler_offset,
                                "segment_duration_ms": filler_seg_ms,
                            })
                            placed_ms += filler_seg_ms
                    else:
                        filler_seg_ms = 0

                    # Pad — always last, absorbs remaining time
                    pad_ms = block_dur_ms - placed_ms
                    assert pad_ms >= 0, (
                        f"negative pad: placed={placed_ms} "
                        f"block_dur={block_dur_ms}"
                    )
                    plan_segments.append({
                        "segment_type": "pad",
                        "segment_duration_ms": pad_ms,
                    })

                    # ---- Invariant: gap-free block ---------------------
                    total_ms = sum(
                        s["segment_duration_ms"] for s in plan_segments
                    )
                    assert total_ms == block_dur_ms, (
                        f"BURN_IN: segment sum {total_ms} != "
                        f"block_dur {block_dur_ms}"
                    )

                    # ---- Validation: no internal:// URIs ---------------
                    for seg in plan_segments:
                        uri = seg.get("asset_uri", "")
                        assert "internal://" not in uri, (
                            f"BURN_IN: internal:// forbidden, got '{uri}'"
                        )

                    # ---- Log -------------------------------------------
                    block_id = f"BLOCK-{_ch_id_str}-{idx}"
                    logger.info(
                        "BURN_IN: %s episode=%dms filler=%dms pad=%dms "
                        "segs=%d",
                        block_id, ep_seg_ms, filler_seg_ms, pad_ms,
                        len(plan_segments),
                    )

                    # ---- Build BlockPlan (all segments, including pad) ---
                    # Re-index contiguously (pad is now first-class in AIR)
                    for i, seg in enumerate(plan_segments):
                        seg["segment_index"] = i

                    return BlockPlan(
                        block_id=block_id,
                        channel_id=_ch_id_int,
                        start_utc_ms=start_ms,
                        end_utc_ms=end_ms,
                        segments=plan_segments,
                    )

                producer._generate_next_block = _compose_block
                return producer

            manager._build_producer_for_mode = build_blockplan_producer

            # =============================================================
            # Tripwires
            # =============================================================
            def _forbidden_load_playlist(*args, **kwargs):
                raise RuntimeError(
                    "TRIPWIRE: manager.load_playlist() called during "
                    "burn_in.  burn_in uses the canonical "
                    "BlockPlanProducer path exclusively."
                )

            manager.load_playlist = _forbidden_load_playlist

            def _forbidden_playlist_path(*args, **kwargs):
                raise RuntimeError(
                    "TRIPWIRE: _ensure_producer_running_playlist called "
                    "during burn_in."
                )

            manager._ensure_producer_running_playlist = _forbidden_playlist_path

            if getattr(manager, "_playlist", None) is not None:
                raise RuntimeError(
                    "TRIPWIRE: manager._playlist is already set after "
                    "_get_or_create_manager."
                )

            logger.info(
                "BURN_IN: Canonical bootstrap for %s "
                "(30-min blocks, cycle_origin_utc_ms=%d)",
                channel_id, cycle_origin_utc_ms,
            )
        return manager

    director._get_or_create_manager = get_or_create_with_blockplan

    # =====================================================================
    # 4. Start runtime
    # =====================================================================
    director.start()

    url = f"http://localhost:{port}/channel/{CHANNEL_ID}.ts"
    logger.info("Burn-in running.  Connect with:")
    logger.info("  vlc %s", url)
    logger.info("  ffplay -fflags nobuffer -flags low_delay %s", url)
    logger.info("Press Ctrl+C to stop.")

    # =====================================================================
    # 5. Block until signal
    # =====================================================================
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
