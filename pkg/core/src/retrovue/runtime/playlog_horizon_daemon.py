"""Playlog Horizon Daemon — Tier 2 of the Two-Tier Horizon Architecture.

Maintains a rolling window of fully-filled playout log entries 2–3+ hours
ahead of the current wall-clock time.  Consumes pre-segmented blocks from
Tier 1 (CompiledProgramLog.segmented_blocks), fills ad break placeholders
via the traffic manager, and writes the result to TransmissionLog (Postgres).

ChannelManager reads TransmissionLog directly — no ad fill or schedule
compilation at feed time.

See: docs/architecture/two-tier-horizon.md
     INV-PLAYLOG-HORIZON-001: Tier 2 maintains ≥2 hours coverage
     INV-PLAYLOG-PREFILL-001: Ad fill at Tier 2 generation, never at feed time
     INV-CHANNEL-NO-COMPILE-001: ChannelManager never compiles or fills ads

Lifecycle: start()/stop() run a background daemon thread.
           evaluate_once() can be called manually for testing.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class PlaylogHealthReport:
    """Point-in-time health snapshot of the Playlog Horizon."""
    depth_hours: float
    min_hours: int
    farthest_block_end_utc_ms: int
    blocks_in_window: int
    last_evaluation_utc_ms: int
    is_healthy: bool
    last_fill_block_id: str | None
    fill_errors_since_start: int


class PlaylogHorizonDaemon:
    """Rolling Tier 2 horizon: pre-filled playout logs in Postgres.

    Write path:
        evaluate_once() → reads Tier 1, fills ads, writes TransmissionLog

    Read path (ChannelManager):
        SELECT FROM transmission_log WHERE channel_slug=? AND start_utc_ms <= ? AND end_utc_ms > ?

    Thread-safe.  All DB access uses short-lived sessions.
    """

    def __init__(
        self,
        channel_id: str,
        *,
        min_hours: int = 3,
        evaluation_interval_seconds: int = 30,
        programming_day_start_hour: int = 6,
        grid_minutes: int = 30,
        filler_path: str = "/opt/retrovue/assets/filler.mp4",
        filler_duration_ms: int = 3_650_000,
        master_clock=None,
        channel_tz: str = "UTC",
    ):
        self._channel_id = channel_id
        self._min_hours = min_hours
        self._eval_interval_s = evaluation_interval_seconds
        self._day_start_hour = programming_day_start_hour
        self._grid_minutes = grid_minutes
        self._filler_path = filler_path
        self._filler_duration_ms = filler_duration_ms
        self._clock = master_clock
        self._channel_tz = ZoneInfo(channel_tz)

        # State
        self._consecutive_zero_fills: int = 0
        self._farthest_end_utc_ms: int = 0
        self._last_evaluation_utc_ms: int = 0
        self._last_fill_block_id: str | None = None
        self._fill_errors: int = 0

        # Lifecycle
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_once(self) -> int:
        """Evaluate Tier 2 depth and extend if below threshold.

        INV-PLAYLOG-COVERAGE-HOLE-001: Ensures Tier 2 always covers the block
        containing now_ms (backfill current block if missing) before forward fill.

        Returns the number of blocks filled in this evaluation.
        """
        now_ms = self._now_utc_ms()
        self._last_evaluation_utc_ms = now_ms

        # Pre-step: ensure Tier 2 covers the block containing now (backfill if hole)
        backfill_count = self._ensure_tier2_covers_now(now_ms)

        # Discover current Tier 2 frontier
        frontier_ms = self._get_frontier_utc_ms()
        if frontier_ms > self._farthest_end_utc_ms:
            self._farthest_end_utc_ms = frontier_ms

        depth_ms = max(0, self._farthest_end_utc_ms - now_ms)
        target_ms = self._min_hours * 3_600_000

        if depth_ms >= target_ms:
            self._consecutive_zero_fills = 0
            logger.debug(
                "PlaylogHorizon[%s]: depth=%.1fh >= %.1fh — no extension needed",
                self._channel_id, depth_ms / 3_600_000, target_ms / 3_600_000,
            )
            return backfill_count

        # Need to extend: find blocks from Tier 1 that don't yet have Tier 2 entries
        blocks_filled = backfill_count + self._extend_to_target(now_ms, target_ms)

        if blocks_filled > 0:
            self._consecutive_zero_fills = 0
            logger.info(
                "PlaylogHorizon[%s]: filled %d blocks, depth now %.1fh",
                self._channel_id, blocks_filled,
                max(0, self._farthest_end_utc_ms - now_ms) / 3_600_000,
            )
        else:
            self._consecutive_zero_fills += 1
            frontier_dt = datetime.fromtimestamp(
                self._farthest_end_utc_ms / 1000.0, tz=timezone.utc
            ) if self._farthest_end_utc_ms > 0 else None
            now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
            logger.warning(
                "PlaylogHorizon[%s]: INV-PLAYLOG-HORIZON-002 VIOLATION: "
                "depth=%.1fh < target=%.1fh but 0 blocks filled "
                "(consecutive_zeros=%d, frontier=%s, now=%s, "
                "scan_start_bd=%s, errors=%d)",
                self._channel_id,
                depth_ms / 3_600_000, target_ms / 3_600_000,
                self._consecutive_zero_fills,
                frontier_dt.isoformat() if frontier_dt else "none",
                now_dt.isoformat(),
                self._broadcast_date_for(now_dt).isoformat(),
                self._fill_errors,
            )

        return blocks_filled

    def get_health_report(self) -> PlaylogHealthReport:
        now_ms = self._now_utc_ms()
        depth_ms = max(0, self._farthest_end_utc_ms - now_ms)
        block_count = self._count_blocks_in_window(now_ms)
        return PlaylogHealthReport(
            depth_hours=round(depth_ms / 3_600_000, 2),
            min_hours=self._min_hours,
            farthest_block_end_utc_ms=self._farthest_end_utc_ms,
            blocks_in_window=block_count,
            last_evaluation_utc_ms=self._last_evaluation_utc_ms,
            is_healthy=depth_ms >= self._min_hours * 3_600_000,
            last_fill_block_id=self._last_fill_block_id,
            fill_errors_since_start=self._fill_errors,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"PlaylogHorizon-{self._channel_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "PlaylogHorizon[%s]: started (interval=%ds, min_hours=%d)",
            self._channel_id, self._eval_interval_s, self._min_hours,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._eval_interval_s + 5)
            self._thread = None
        logger.info("PlaylogHorizon[%s]: stopped", self._channel_id)

    # ------------------------------------------------------------------
    # Internal: extension logic
    # ------------------------------------------------------------------

    def _extend_to_target(self, now_ms: int, target_ms: int) -> int:
        """Fill blocks from Tier 1 until Tier 2 depth reaches target."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import CompiledProgramLog, TransmissionLog
        from retrovue.runtime.traffic_manager import fill_ad_blocks
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        target_end_ms = now_ms + target_ms
        blocks_filled = 0

        # Start from current frontier (or now if no frontier)
        cursor_ms = max(self._farthest_end_utc_ms, now_ms)

        # Determine broadcast days we need to scan
        cursor_dt = datetime.fromtimestamp(cursor_ms / 1000.0, tz=timezone.utc)
        target_dt = datetime.fromtimestamp(target_end_ms / 1000.0, tz=timezone.utc)

        # INV-PLAYLOG-HORIZON-TZ-001: Start scan 1 day earlier than computed
        # broadcast day to handle blocks near the day boundary that might
        # belong to the previous broadcast day's compiled schedule.
        scan_date = self._broadcast_date_for(cursor_dt) - timedelta(days=1)
        end_date = self._broadcast_date_for(target_dt) + timedelta(days=1)

        while scan_date <= end_date and cursor_ms < target_end_ms:
            # Load Tier 1 segmented blocks for this day
            segmented_blocks = self._load_tier1_blocks(scan_date)
            if segmented_blocks is None:
                logger.warning(
                    "PlaylogHorizon[%s]: No Tier 1 data for %s — cannot extend",
                    self._channel_id, scan_date.isoformat(),
                )
                scan_date += timedelta(days=1)
                continue

            for sb_dict in segmented_blocks:
                block_start = sb_dict["start_utc_ms"]
                block_end = sb_dict["end_utc_ms"]
                block_id = sb_dict["block_id"]

                # Skip blocks we've already filled or that are in the past
                if block_end <= cursor_ms:
                    continue
                if block_start >= target_end_ms:
                    break

                # Check if already in TransmissionLog
                if self._block_exists_in_txlog(block_id):
                    if block_end > self._farthest_end_utc_ms:
                        self._farthest_end_utc_ms = block_end
                    continue

                # Deserialize and fill ads
                try:
                    from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block
                    scheduled_block = _deserialize_scheduled_block(sb_dict)

                    # Fill ad breaks via traffic manager
                    filled_block = self._fill_ads(scheduled_block)

                    # Write to TransmissionLog
                    self._write_to_txlog(filled_block, scan_date)

                    self._last_fill_block_id = block_id
                    if block_end > self._farthest_end_utc_ms:
                        self._farthest_end_utc_ms = block_end
                    blocks_filled += 1

                    logger.debug(
                        "PlaylogHorizon[%s]: filled block=%s (%d segs)",
                        self._channel_id, block_id,
                        len(filled_block.segments),
                    )

                except Exception as e:
                    self._fill_errors += 1
                    logger.error(
                        "PlaylogHorizon[%s]: failed to fill block=%s: %s",
                        self._channel_id, block_id, e,
                    )

            scan_date += timedelta(days=1)

        return blocks_filled

    def _ensure_tier2_covers_now(self, now_ms: int) -> int:
        """Backfill the Tier-1 block containing now_ms if Tier-2 has no row covering it.

        INV-PLAYLOG-COVERAGE-HOLE-001: Ensures Tier 2 always covers the block that
        contains now_ms (e.g. daemon started late or Tier-2 was empty). Backfill
        allowed only if now_ms < block_end (do not backfill wholly-past blocks).

        Returns 1 if a block was filled, 0 otherwise.
        """
        if self._tier2_row_covers_now(now_ms):
            return 0

        block = self._get_tier1_block_containing(now_ms)
        if block is None:
            return 0

        block_end = block["end_utc_ms"]
        if now_ms >= block_end:
            return 0

        block_id = block["block_id"]
        logger.warning(
            "INV-PLAYLOG-COVERAGE-HOLE-001: missing Tier2 coverage for now_ms=%d "
            "backfilling block_id=%s",
            now_ms, block_id,
        )

        try:
            from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

            scheduled_block = _deserialize_scheduled_block(block)
            filled_block = self._fill_ads(scheduled_block)
            block_start_dt = datetime.fromtimestamp(
                block["start_utc_ms"] / 1000.0, tz=timezone.utc
            )
            broadcast_day = self._broadcast_date_for(block_start_dt)
            self._write_to_txlog(filled_block, broadcast_day)

            self._last_fill_block_id = block_id
            if block_end > self._farthest_end_utc_ms:
                self._farthest_end_utc_ms = block_end
            return 1
        except Exception as e:
            self._fill_errors += 1
            logger.error(
                "PlaylogHorizon[%s]: backfill failed for block=%s: %s",
                self._channel_id, block_id, e,
            )
            return 0

    def _tier2_row_covers_now(self, now_ms: int) -> bool:
        """True if TransmissionLog has a row covering now_ms (by time window)."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import TransmissionLog

        try:
            with db_session_factory() as db:
                return (
                    db.query(TransmissionLog)
                    .filter(
                        TransmissionLog.channel_slug == self._channel_id,
                        TransmissionLog.start_utc_ms <= now_ms,
                        TransmissionLog.end_utc_ms > now_ms,
                    )
                    .first()
                    is not None
                )
        except Exception:
            return False

    def _get_tier1_block_containing(self, now_ms: int) -> dict | None:
        """Return the Tier-1 segmented block dict that contains now_ms, or None.

        Checks broadcast_date(now) and broadcast_date(now)-1 for day-boundary blocks.
        """
        now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
        bd = self._broadcast_date_for(now_dt)
        for scan_date in (bd - timedelta(days=1), bd):
            blocks = self._load_tier1_blocks(scan_date)
            if blocks is None:
                continue
            for sb_dict in blocks:
                if sb_dict["start_utc_ms"] <= now_ms < sb_dict["end_utc_ms"]:
                    return sb_dict
        return None

    def _load_tier1_blocks(self, broadcast_day: date) -> list[dict] | None:
        """Load segmented_blocks from CompiledProgramLog (Tier 1)."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import CompiledProgramLog

        try:
            with db_session_factory() as db:
                row = db.query(CompiledProgramLog).filter(
                    CompiledProgramLog.channel_id == self._channel_id,
                    CompiledProgramLog.broadcast_day == broadcast_day,
                    CompiledProgramLog.locked == True,
                ).first()
                if row is None:
                    return None
                cj = row.compiled_json
                if "segmented_blocks" not in cj or not cj["segmented_blocks"]:
                    logger.warning(
                        "PlaylogHorizon[%s]: Tier 1 for %s has no segmented_blocks "
                        "(pre-enhancement cache — needs recompile)",
                        self._channel_id, broadcast_day.isoformat(),
                    )
                    return None
                return cj["segmented_blocks"]
        except Exception as e:
            logger.error(
                "PlaylogHorizon[%s]: DB error loading Tier 1 for %s: %s",
                self._channel_id, broadcast_day.isoformat(), e,
            )
            return None

    def _block_exists_in_txlog(self, block_id: str) -> bool:
        """Check if a block already has a TransmissionLog entry."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import TransmissionLog

        try:
            with db_session_factory() as db:
                return db.query(TransmissionLog).filter(
                    TransmissionLog.block_id == block_id,
                ).first() is not None
        except Exception:
            return False

    def _fill_ads(self, block: "ScheduledBlock") -> "ScheduledBlock":
        """Fill empty filler placeholders with real interstitials.

        INV-PLAYLOG-PREFILL-001: Ad fill happens here at Tier 2 generation.
        """
        from retrovue.runtime.traffic_manager import fill_ad_blocks
        from retrovue.infra.uow import session as db_session_factory

        asset_lib = None
        try:
            from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
            with db_session_factory() as db:
                asset_lib = DatabaseAssetLibrary(db, channel_slug=self._channel_id)
        except Exception as e:
            logger.warning(
                "PlaylogHorizon[%s]: Could not create asset library: %s",
                self._channel_id, e,
            )

        return fill_ad_blocks(
            block,
            filler_uri=self._filler_path,
            filler_duration_ms=self._filler_duration_ms,
            asset_library=asset_lib,
        )

    def _write_to_txlog(self, block: "ScheduledBlock", broadcast_day: date) -> None:
        """Write a filled block to TransmissionLog.

        INV-PLAYLOG-PREFILL-001: Canonical Tier 2 write path.
        """
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import TransmissionLog

        segments_data = []
        for i, seg in enumerate(block.segments):
            d = {
                "segment_index": i,
                "segment_type": seg.segment_type,
                "asset_uri": seg.asset_uri,
                "asset_start_offset_ms": seg.asset_start_offset_ms,
                "segment_duration_ms": seg.segment_duration_ms,
            }
            # Add title for observability (derive from asset_uri)
            if seg.asset_uri:
                name = seg.asset_uri.rsplit("/", 1)[-1] if "/" in seg.asset_uri else seg.asset_uri
                if "." in name:
                    name = name.rsplit(".", 1)[0]
                for prefix in ("Interstitial - Commercial - ", "Interstitial - ", "Commercial - "):
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                        break
                d["title"] = name
            else:
                d["title"] = "BLACK" if seg.segment_type == "pad" else seg.segment_type.upper()

            # Preserve transition fields if present
            if seg.transition_in != "TRANSITION_NONE":
                d["transition_in"] = seg.transition_in
                d["transition_in_duration_ms"] = seg.transition_in_duration_ms
            if seg.transition_out != "TRANSITION_NONE":
                d["transition_out"] = seg.transition_out
                d["transition_out_duration_ms"] = seg.transition_out_duration_ms

            segments_data.append(d)

        try:
            with db_session_factory() as db:
                row = TransmissionLog(
                    block_id=block.block_id,
                    channel_slug=self._channel_id,
                    broadcast_day=broadcast_day,
                    start_utc_ms=block.start_utc_ms,
                    end_utc_ms=block.end_utc_ms,
                    segments=segments_data,
                )
                db.merge(row)
        except Exception as e:
            logger.error(
                "PlaylogHorizon[%s]: Failed to write block=%s to TransmissionLog: %s",
                self._channel_id, block.block_id, e,
            )
            raise

    # ------------------------------------------------------------------
    # Internal: queries
    # ------------------------------------------------------------------

    def _get_frontier_utc_ms(self) -> int:
        """Get the farthest end_utc_ms in TransmissionLog for this channel."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import TransmissionLog
        import sqlalchemy as sa

        try:
            with db_session_factory() as db:
                result = db.query(sa.func.max(TransmissionLog.end_utc_ms)).filter(
                    TransmissionLog.channel_slug == self._channel_id,
                ).scalar()
                return result or 0
        except Exception:
            return 0

    def _count_blocks_in_window(self, now_ms: int) -> int:
        """Count TransmissionLog entries from now forward."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import TransmissionLog

        try:
            with db_session_factory() as db:
                return db.query(TransmissionLog).filter(
                    TransmissionLog.channel_slug == self._channel_id,
                    TransmissionLog.end_utc_ms > now_ms,
                ).count()
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Internal: utilities
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.evaluate_once()
            except Exception:
                logger.exception(
                    "PlaylogHorizon[%s]: evaluation failed", self._channel_id,
                )
            self._stop_event.wait(timeout=self._eval_interval_s)

    def _broadcast_date_for(self, dt: datetime) -> date:
        """Compute broadcast day using the channel's local timezone.

        INV-PLAYLOG-HORIZON-TZ-001: Broadcast day boundary MUST be computed
        in the channel's configured timezone, not UTC. A channel with
        programming_day_start_hour=6 and tz=America/New_York starts its
        broadcast day at 06:00 EST (11:00 UTC), not 06:00 UTC.
        """
        local_dt = dt.astimezone(self._channel_tz)
        if local_dt.hour < self._day_start_hour:
            return (local_dt - timedelta(days=1)).date()
        return local_dt.date()

    def _now_utc_ms(self) -> int:
        if self._clock is not None:
            return int(self._clock.now_utc().timestamp() * 1000)
        return int(datetime.now(timezone.utc).timestamp() * 1000)
