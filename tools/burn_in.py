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
    python tools/burn_in.py --pipeline
    python tools/burn_in.py --horizon
    python tools/burn_in.py --dump

Arguments:
    --schedule PATH  -- static schedule JSON (default: tools/static_schedule.json)
    --pipeline       -- use planning pipeline with rolling day adapter (legacy)
    --horizon        -- use HorizonManager with ExecutionWindowStore (contract-aligned)
    --dump           -- print transmission log and exit (implies --pipeline)

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
import re
import threading
from datetime import date, datetime, time as time_type, timedelta, timezone
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
FILLER_DURATION_MS = 3_650_455

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "config" / "asset_catalog.json"
PROGRAMS_DIR = REPO_ROOT / "config" / "programs"

logger = logging.getLogger("burn_in")


# ===========================================================================
# Pipeline helpers
# ===========================================================================


def _apply_jip_to_segments(segments, jip_offset_ms, block_dur_ms):
    """Apply JIP offset to N pre-composed segments.

    Walks segments from the start, skipping fully elapsed ones and trimming
    the partially elapsed one.  Extends (or appends) a trailing pad so the
    result sums to exactly block_dur_ms.
    """
    result = []
    remaining = jip_offset_ms
    for seg in segments:
        seg = dict(seg)
        dur = seg["segment_duration_ms"]
        if remaining >= dur:
            remaining -= dur
            continue  # fully elapsed — skip
        if remaining > 0:
            if seg.get("asset_uri"):
                seg["asset_start_offset_ms"] = (
                    seg.get("asset_start_offset_ms", 0) + remaining
                )
            seg["segment_duration_ms"] -= remaining
            remaining = 0
        result.append(seg)
    # Extend pad to fill block
    placed = sum(s["segment_duration_ms"] for s in result)
    gap = block_dur_ms - placed
    if gap > 0:
        if result and result[-1].get("segment_type") == "pad":
            result[-1]["segment_duration_ms"] += gap
        else:
            result.append({"segment_type": "pad", "segment_duration_ms": gap})
    return result


class _PipelineContext:
    """Shared pipeline state that persists across broadcast days.

    Sequence and resolved stores are shared so that episode cursors
    advance correctly from one day to the next.
    """

    def __init__(self):
        from retrovue.catalog.static_asset_library import StaticAssetLibrary
        from retrovue.runtime.phase3_schedule_service import (
            InMemoryResolvedStore,
            InMemorySequenceStore,
            JsonFileProgramCatalog,
        )
        from retrovue.runtime.planning_pipeline import (
            PlanningDirective,
            ZoneDirective,
        )
        from retrovue.runtime.schedule_types import (
            Phase3Config,
            ProgramRef,
            ProgramRefType,
        )

        self.catalog = JsonFileProgramCatalog(PROGRAMS_DIR)
        self.catalog.load_all()

        self.asset_library = StaticAssetLibrary(CATALOG_PATH)

        self.sequence_store = InMemorySequenceStore()
        self.resolved_store = InMemoryResolvedStore()

        self.config = Phase3Config(
            grid_minutes=30,
            program_catalog=self.catalog,
            sequence_store=self.sequence_store,
            resolved_store=self.resolved_store,
            filler_path=FILLER_PATH,
            filler_duration_seconds=FILLER_DURATION_MS / 1000.0,
            programming_day_start_hour=6,
        )

        self.directive = PlanningDirective(
            channel_id=CHANNEL_ID,
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(
                    start_time=time_type(6, 0),
                    end_time=time_type(6, 0),  # same = full 24h wrap
                    programs=[ProgramRef(ProgramRefType.PROGRAM, "cheers")],
                    label="Cheers 24/7",
                ),
            ],
        )

    def generate_day(self, broadcast_date: date):
        """Run the full planning pipeline for one broadcast date.

        Returns a TransmissionLog.  Sequence cursors in the shared
        store advance, so the next call picks up where this one left off.
        """
        from retrovue.runtime.planning_pipeline import (
            PlanningRunRequest,
            run_planning_pipeline,
        )

        run_req = PlanningRunRequest(
            directive=self.directive,
            broadcast_date=broadcast_date,
            resolution_time=datetime(
                broadcast_date.year, broadcast_date.month,
                broadcast_date.day, 5, 0, 0,
            ),
        )
        lock_time = datetime(
            broadcast_date.year, broadcast_date.month,
            broadcast_date.day, 5, 30, 0,
        )
        return run_planning_pipeline(
            run_req, self.config, self.asset_library, lock_time=lock_time,
        )


def _run_pipeline():
    """Run the planning pipeline for today (convenience wrapper).

    Returns a TransmissionLog (48 blocks, Cheers 24/7, today's date).
    Used by --dump and as the initial day in pipeline mode.
    """
    ctx = _PipelineContext()
    return ctx.generate_day(date.today())


def _episode_label(uri):
    """Extract 'S01E01 Give Me a Ring Sometime' from asset URI."""
    m = re.search(r"(S\d+E\d+)\s*-\s*([^[]+)", uri or "")
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    return os.path.basename(uri or "unknown")[:40]


def _print_transmission_log(log):
    """Print human-readable grid of the transmission log."""
    print()
    print(
        f"Transmission Log: {log.channel_id}  "
        f"date={log.broadcast_date}  locked={log.is_locked}"
    )
    print(f"Blocks: {len(log.entries)}")
    print()
    print(f"{'Block':>5}  {'Time':<13}  {'Episode':<40}  Segments")
    print(f"{'─' * 5}  {'─' * 13}  {'─' * 40}  {'─' * 60}")

    total_content_ms = 0
    total_filler_ms = 0
    total_pad_ms = 0
    episode_uris: set[str] = set()

    for entry in log.entries:
        start_dt = datetime.fromtimestamp(
            entry.start_utc_ms / 1000.0, tz=timezone.utc,
        ).astimezone()
        end_dt = datetime.fromtimestamp(
            entry.end_utc_ms / 1000.0, tz=timezone.utc,
        ).astimezone()
        time_str = f"{start_dt:%H:%M}-{end_dt:%H:%M}"

        # Episode label from first episode segment
        ep_label = "\u2014"
        for seg in entry.segments:
            if seg["segment_type"] == "episode":
                ep_label = _episode_label(seg.get("asset_uri"))
                episode_uris.add(seg.get("asset_uri", ""))
                break

        # Segment summary
        seg_parts = []
        for seg in entry.segments:
            t = seg["segment_type"]
            dur_s = seg["segment_duration_ms"] // 1000
            abbr = {
                "episode": "ep", "filler": "fl", "pad": "pad",
                "promo": "pr", "ad": "ad",
            }.get(t, t[:3])
            seg_parts.append(f"{abbr}:{dur_s}s")

            if t == "episode":
                total_content_ms += seg["segment_duration_ms"]
            elif t in ("filler", "promo", "ad"):
                total_filler_ms += seg["segment_duration_ms"]
            elif t == "pad":
                total_pad_ms += seg["segment_duration_ms"]

        total_s = sum(
            s["segment_duration_ms"] for s in entry.segments
        ) // 1000
        seg_str = " + ".join(seg_parts) + f" = {total_s}s"
        print(
            f"{entry.block_index:>5}  {time_str:<13}  "
            f"{ep_label:<40}  {seg_str}"
        )

    print()
    print(
        f"Summary: {len(log.entries)} blocks, "
        f"{len(episode_uris)} unique episodes"
    )
    print(
        f"  Content: {total_content_ms / 1000:.0f}s "
        f"({total_content_ms / 3_600_000:.1f}h)"
    )
    print(
        f"  Filler:  {total_filler_ms / 1000:.0f}s "
        f"({total_filler_ms / 3_600_000:.1f}h)"
    )
    print(
        f"  Pad:     {total_pad_ms / 1000:.0f}s "
        f"({total_pad_ms / 3_600_000:.1f}h)"
    )
    print()


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


class _RollingPipelineAdapter:
    """Rolling schedule adapter that generates new days on demand.

    Uses ``at_station_time`` (passed by ``_resolve_plan_for_block``) to
    determine the broadcast date, then lazily generates and caches that
    day's TransmissionLog via the shared ``_PipelineContext``.

    Episode cursors advance correctly across day boundaries because
    the context's sequence store persists across ``generate_day()`` calls.
    """

    def __init__(self, ctx: _PipelineContext, programming_day_start_hour: int = 6):
        self._ctx = ctx
        self._start_hour = programming_day_start_hour
        self._day_cache: dict[date, list[dict]] = {}
        self._lock = threading.Lock()

    def _broadcast_date_for(self, dt: datetime) -> date:
        """Determine which broadcast day a wall-clock time falls in.

        Times before the programming day start hour belong to the
        previous calendar day's broadcast day.
        """
        if dt.hour < self._start_hour:
            return (dt - timedelta(days=1)).date()
        return dt.date()

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        bd = self._broadcast_date_for(at_station_time)
        with self._lock:
            if bd not in self._day_cache:
                log = self._ctx.generate_day(bd)
                self._day_cache[bd] = [
                    {"segments": e.segments, "duration_ms": BLOCK_DURATION_MS}
                    for e in log.entries
                ]
                logger.info(
                    "BURN_IN: Generated schedule for %s (%d blocks)",
                    bd.isoformat(), len(log.entries),
                )
            return self._day_cache[bd]

    def load_schedule(self, channel_id: str):
        return True, None


# ===========================================================================
# Horizon mode adapters
# ===========================================================================


class _PipelineScheduleExtender:
    """Adapts _PipelineContext for HorizonManager's ScheduleExtender protocol.

    Tracks which broadcast dates have been resolved.  The planning
    pipeline resolves EPG as a side effect of generate_day().
    """

    def __init__(self):
        self._resolved_dates: set[date] = set()

    def epg_day_exists(self, broadcast_date: date) -> bool:
        return broadcast_date in self._resolved_dates

    def extend_epg_day(self, broadcast_date: date) -> None:
        self._resolved_dates.add(broadcast_date)


class _PipelineExecutionExtender:
    """Adapts _PipelineContext for HorizonManager's ExecutionExtender protocol.

    Returns ExecutionDayResult with entries for store population.
    """

    def __init__(self, ctx: _PipelineContext):
        self._ctx = ctx

    def extend_execution_day(self, broadcast_date: date):
        from retrovue.runtime.execution_window_store import (
            ExecutionDayResult,
            ExecutionEntry,
        )

        log = self._ctx.generate_day(broadcast_date)
        entries = [
            ExecutionEntry(
                block_id=e.block_id,
                block_index=e.block_index,
                start_utc_ms=e.start_utc_ms,
                end_utc_ms=e.end_utc_ms,
                segments=e.segments,
            )
            for e in log.entries
        ]
        end_ms = log.entries[-1].end_utc_ms if log.entries else 0
        logger.info(
            "HORIZON: Generated execution data for %s (%d blocks, "
            "end_utc_ms=%d)",
            broadcast_date.isoformat(), len(entries), end_ms,
        )
        return ExecutionDayResult(end_utc_ms=end_ms, entries=entries)


class _HorizonScheduleAdapter:
    """Schedule adapter that reads from ExecutionWindowStore.

    Used in --horizon mode.  Entries are looked up by wall-clock time,
    not by index modulo.  No direct pipeline calls.
    """

    def __init__(self, store):
        self._store = store

    def get_playout_plan_now(self, channel_id: str, at_station_time) -> list[dict]:
        entries = self._store.get_all_entries()
        return [
            {
                "segments": e.segments,
                "duration_ms": BLOCK_DURATION_MS,
                "start_utc_ms": e.start_utc_ms,
            }
            for e in entries
        ]

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
    parser.add_argument(
        "--pipeline", action="store_true",
        help="Use planning pipeline with rolling day adapter (legacy)",
    )
    parser.add_argument(
        "--horizon", action="store_true",
        help=(
            "Use HorizonManager with ExecutionWindowStore "
            "(contract-aligned, no modulo wrapping)"
        ),
    )
    parser.add_argument(
        "--dump", action="store_true",
        help="Print transmission log and exit (implies --pipeline)",
    )
    args = parser.parse_args()

    horizon_mode = args.horizon
    pipeline_mode = (args.pipeline or args.dump) and not horizon_mode

    if args.dump:
        log = _run_pipeline()
        _print_transmission_log(log)
        return

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
    today = date.today()
    day_start_dt = datetime(
        today.year, today.month, today.day, 6, 0, 0, tzinfo=timezone.utc,
    )
    cycle_origin_utc_ms = int(day_start_dt.timestamp() * 1000)

    horizon_manager = None  # set only in --horizon mode

    if horizon_mode:
        from retrovue.runtime.clock import MasterClock
        from retrovue.runtime.execution_window_store import ExecutionWindowStore
        from retrovue.runtime.horizon_manager import HorizonManager

        ctx = _PipelineContext()
        # Generate today's log for the initial grid printout.
        # The resolved store caches this, so HorizonManager won't re-resolve.
        log = ctx.generate_day(today)
        _print_transmission_log(log)

        execution_store = ExecutionWindowStore()
        schedule_extender = _PipelineScheduleExtender()
        execution_extender = _PipelineExecutionExtender(ctx)

        horizon_manager = HorizonManager(
            schedule_manager=schedule_extender,
            planning_pipeline=execution_extender,
            master_clock=MasterClock(),
            min_epg_days=3,
            min_execution_hours=6,
            evaluation_interval_seconds=30,
            programming_day_start_hour=6,
            execution_store=execution_store,
        )

        # Synchronous initial evaluation — populates the store before
        # any viewer can connect.
        horizon_manager.evaluate_once()
        logger.info(
            "HORIZON: Initial store populated: %d entries, "
            "exec_depth=%.1fh, epg_depth=%.1fh",
            len(execution_store.get_all_entries()),
            horizon_manager.get_execution_depth_hours(),
            horizon_manager.get_epg_depth_hours(),
        )

        schedule_service = _HorizonScheduleAdapter(execution_store)

    elif pipeline_mode:
        ctx = _PipelineContext()
        log = ctx.generate_day(today)
        _print_transmission_log(log)
        schedule_service = _RollingPipelineAdapter(ctx)
        # Seed the cache so the initial day isn't re-generated
        schedule_service._day_cache[today] = [
            {"segments": e.segments, "duration_ms": BLOCK_DURATION_MS}
            for e in log.entries
        ]
    elif use_test_assets:
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

                # -------------------------------------------------------
                # _compose_block_pipeline: pre-composed segments from
                # the planning pipeline.  No episode/filler/pad rebuild;
                # segments arrive ready-made.
                # -------------------------------------------------------
                def _compose_block_pipeline(playout_plan, *, jip_offset_ms=0):
                    from retrovue.runtime.playout_session import BlockPlan

                    idx = producer._block_index
                    start_ms = producer._next_block_start_ms
                    entry = playout_plan[idx % len(playout_plan)]
                    block_dur_ms = BLOCK_DURATION_MS
                    end_ms = start_ms + block_dur_ms

                    # Deep-copy pre-composed segments
                    plan_segments = [dict(s) for s in entry["segments"]]

                    if jip_offset_ms > 0:
                        plan_segments = _apply_jip_to_segments(
                            plan_segments, jip_offset_ms, block_dur_ms,
                        )
                        logger.info(
                            "BURN_IN: JIP block idx=%d "
                            "jip_offset_ms=%d (%.1fs into block)",
                            idx, jip_offset_ms, jip_offset_ms / 1000.0,
                        )

                    # Re-index contiguously
                    for i, seg in enumerate(plan_segments):
                        seg["segment_index"] = i

                    # ---- Invariant: gap-free block -----------------
                    total_ms = sum(
                        s["segment_duration_ms"] for s in plan_segments
                    )
                    assert total_ms == block_dur_ms, (
                        f"BURN_IN: segment sum {total_ms} != "
                        f"block_dur {block_dur_ms}"
                    )

                    # ---- Validation: no internal:// URIs -----------
                    for seg in plan_segments:
                        uri = seg.get("asset_uri", "")
                        assert "internal://" not in uri, (
                            f"BURN_IN: internal:// forbidden, got '{uri}'"
                        )

                    block_id = f"BLOCK-{_ch_id_str}-{idx}"
                    type_sums: dict[str, int] = {}
                    for seg in plan_segments:
                        t = seg["segment_type"]
                        type_sums[t] = (
                            type_sums.get(t, 0)
                            + seg["segment_duration_ms"]
                        )
                    type_summary = " ".join(
                        f"{t}={ms}ms" for t, ms in type_sums.items()
                    )
                    logger.info(
                        "BURN_IN: %s %s segs=%d",
                        block_id, type_summary, len(plan_segments),
                    )

                    return BlockPlan(
                        block_id=block_id,
                        channel_id=_ch_id_int,
                        start_utc_ms=start_ms,
                        end_utc_ms=end_ms,
                        segments=plan_segments,
                    )

                # -------------------------------------------------------
                # _compose_block_horizon: time-based lookup from
                # ExecutionWindowStore.  No modulo wrapping — the
                # correct entry is found by matching start_utc_ms.
                # -------------------------------------------------------
                def _compose_block_horizon(playout_plan, *, jip_offset_ms=0):
                    from retrovue.runtime.playout_session import BlockPlan

                    idx = producer._block_index
                    start_ms = producer._next_block_start_ms
                    block_dur_ms = BLOCK_DURATION_MS
                    end_ms = start_ms + block_dur_ms

                    # Time-based lookup — find the entry whose
                    # start_utc_ms matches this block's start time.
                    entry = None
                    for e in playout_plan:
                        if e.get("start_utc_ms") == start_ms:
                            entry = e
                            break

                    if entry is None:
                        raise RuntimeError(
                            f"HORIZON: No execution entry for "
                            f"start_utc_ms={start_ms} (block idx={idx}). "
                            f"ExecutionWindowStore has "
                            f"{len(playout_plan)} entries."
                        )

                    # Deep-copy pre-composed segments
                    plan_segments = [dict(s) for s in entry["segments"]]

                    if jip_offset_ms > 0:
                        plan_segments = _apply_jip_to_segments(
                            plan_segments, jip_offset_ms, block_dur_ms,
                        )
                        logger.info(
                            "HORIZON: JIP block idx=%d "
                            "jip_offset_ms=%d (%.1fs into block)",
                            idx, jip_offset_ms, jip_offset_ms / 1000.0,
                        )

                    # Re-index contiguously
                    for i, seg in enumerate(plan_segments):
                        seg["segment_index"] = i

                    # ---- Invariant: gap-free block -----------------
                    total_ms = sum(
                        s["segment_duration_ms"] for s in plan_segments
                    )
                    assert total_ms == block_dur_ms, (
                        f"HORIZON: segment sum {total_ms} != "
                        f"block_dur {block_dur_ms}"
                    )

                    # ---- Validation: no internal:// URIs -----------
                    for seg in plan_segments:
                        uri = seg.get("asset_uri", "")
                        assert "internal://" not in uri, (
                            f"HORIZON: internal:// forbidden, got '{uri}'"
                        )

                    block_id = f"BLOCK-{_ch_id_str}-{idx}"
                    type_sums: dict[str, int] = {}
                    for seg in plan_segments:
                        t = seg["segment_type"]
                        type_sums[t] = (
                            type_sums.get(t, 0)
                            + seg["segment_duration_ms"]
                        )
                    type_summary = " ".join(
                        f"{t}={ms}ms" for t, ms in type_sums.items()
                    )
                    logger.info(
                        "HORIZON: %s %s segs=%d",
                        block_id, type_summary, len(plan_segments),
                    )

                    return BlockPlan(
                        block_id=block_id,
                        channel_id=_ch_id_int,
                        start_utc_ms=start_ms,
                        end_utc_ms=end_ms,
                        segments=plan_segments,
                    )

                if horizon_mode:
                    producer._generate_next_block = _compose_block_horizon
                elif pipeline_mode:
                    producer._generate_next_block = _compose_block_pipeline
                else:
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
    if horizon_manager is not None:
        horizon_manager.start()
        logger.info("HORIZON: Background horizon maintenance started")

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
    if horizon_manager is not None:
        horizon_manager.stop()
    director.stop()
    logger.info("Done.")


if __name__ == "__main__":
    main()
