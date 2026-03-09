"""Playlist Builder Daemon — Tier 2 of the Two-Tier Horizon Architecture.

Maintains a rolling window of fully-filled playlist events 2–3+ hours
ahead of the current wall-clock time. Consumes pre-segmented blocks from
Tier 1 (active ScheduleRevision/ScheduleItems), fills ad break placeholders
via the traffic manager, and writes the result to PlaylistEvent (Postgres).

ChannelManager reads PlaylistEvent directly — no ad fill or schedule
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
import random
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retrovue.runtime.schedule_items_reader import expand_editorial_block

logger = logging.getLogger(__name__)

# Log INV-PLAYLOG-HORIZON-002 at WARNING only on first consecutive zero; later repeats at DEBUG.
# When Tier 1 has no next-day blocks (e.g. compile not run yet), 0 blocks filled every tick.
PLAYLOG_HORIZON_002_WARN_ON_FIRST_ONLY = True


@dataclass
class PlaylistBuilderHealthReport:
    """Point-in-time health snapshot of the Playlist Builder."""
    depth_hours: float
    min_hours: int
    farthest_block_end_utc_ms: int
    blocks_in_window: int
    last_evaluation_utc_ms: int
    is_healthy: bool
    last_fill_block_id: str | None
    fill_errors_since_start: int


class PlaylistBuilderDaemon:
    """Rolling Tier 2 horizon: pre-filled playlist events in Postgres.

    Write path:
        evaluate_once() → reads Tier 1, fills ads, writes PlaylistEvent

    Read path (ChannelManager):
        SELECT FROM playlist_event WHERE channel_slug=? AND start_utc_ms <= ? AND end_utc_ms > ?

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
        dsl_path: str | None = None,
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

        # Traffic policy + break config resolved from channel DSL
        self._traffic_policy: Any = None
        self._break_config: Any = None
        if dsl_path:
            try:
                from pathlib import Path
                from retrovue.runtime.dsl_schedule_service import parse_dsl
                from retrovue.runtime.traffic_dsl import (
                    resolve_break_config,
                    resolve_traffic_policy,
                )
                dsl = parse_dsl(Path(dsl_path).read_text())
                if "traffic" in dsl:
                    self._traffic_policy = resolve_traffic_policy(dsl, {})
                    self._break_config = resolve_break_config(dsl)
            except Exception as exc:
                logger.warning(
                    "PlaylistBuilder[%s]: could not resolve traffic config: %s",
                    channel_id, exc,
                )

        # State
        self._consecutive_zero_fills: int = 0
        self._farthest_end_utc_ms: int = 0
        self._last_evaluation_utc_ms: int = 0
        self._last_fill_block_id: str | None = None
        self._fill_errors: int = 0

        # Suppress repeated "needs recompile" noise: log once per (channel, day)
        self._warned_stale_days: set[date] = set()

        # INV-SCHEDULE-RETENTION-001: throttle DB purge to at most once/hour
        self._last_tier2_purge_utc_ms: int = 0

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

        INV-DAEMON-SESSION-SCOPE-001: Opens at most one database session per
        cycle and passes it to all sub-methods.

        Returns the number of blocks filled in this evaluation.
        """
        from retrovue.infra.uow import session as db_session_factory

        now_ms = self._now_utc_ms()
        self._last_evaluation_utc_ms = now_ms

        with db_session_factory() as db:
            # Pre-step: ensure Tier 2 covers the block containing now (backfill if hole)
            backfill_count = self._ensure_tier2_covers_now(now_ms, db=db)

            # Discover current Tier 2 frontier
            frontier_ms = self._get_frontier_utc_ms(db=db)
            if frontier_ms > self._farthest_end_utc_ms:
                self._farthest_end_utc_ms = frontier_ms

            depth_ms = max(0, self._farthest_end_utc_ms - now_ms)
            target_ms = self._min_hours * 3_600_000

            if depth_ms >= target_ms:
                self._consecutive_zero_fills = 0
                logger.debug(
                    "PlaylistBuilder[%s]: depth=%.1fh >= %.1fh — no extension needed",
                    self._channel_id, depth_ms / 3_600_000, target_ms / 3_600_000,
                )
                return backfill_count

            # Need to extend: find blocks from Tier 1 that don't yet have Tier 2 entries
            blocks_filled = backfill_count + self._extend_to_target(now_ms, target_ms, db=db)

            if blocks_filled > 0:
                self._consecutive_zero_fills = 0
                logger.info(
                    "PlaylistBuilder[%s]: filled %d blocks, depth now %.1fh",
                    self._channel_id, blocks_filled,
                    max(0, self._farthest_end_utc_ms - now_ms) / 3_600_000,
                )
            else:
                self._consecutive_zero_fills += 1
                frontier_dt = datetime.fromtimestamp(
                    self._farthest_end_utc_ms / 1000.0, tz=timezone.utc
                ) if self._farthest_end_utc_ms > 0 else None
                now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
                # WARNING only on first occurrence; subsequent repeats at DEBUG to avoid flood.
                log_fn = (
                    logger.warning
                    if (PLAYLOG_HORIZON_002_WARN_ON_FIRST_ONLY and self._consecutive_zero_fills == 1)
                    else logger.debug
                )
                log_fn(
                    "PlaylistBuilder[%s]: INV-PLAYLOG-HORIZON-002 VIOLATION: "
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

            # INV-SCHEDULE-RETENTION-001: purge expired Tier 2 DB rows
            self._purge_expired_tier2(now_ms, db=db)

        return blocks_filled

    def get_health_report(self) -> PlaylistBuilderHealthReport:
        now_ms = self._now_utc_ms()
        depth_ms = max(0, self._farthest_end_utc_ms - now_ms)
        block_count = self._count_blocks_in_window(now_ms)
        return PlaylistBuilderHealthReport(
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
            name=f"PlaylistBuilder-{self._channel_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "PlaylistBuilder[%s]: started (interval=%ds, min_hours=%d)",
            self._channel_id, self._eval_interval_s, self._min_hours,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._eval_interval_s + 5)
            self._thread = None
        logger.info("PlaylistBuilder[%s]: stopped", self._channel_id)

    # ------------------------------------------------------------------
    # Internal: retention
    # ------------------------------------------------------------------

    def _purge_expired_tier2(self, now_utc_ms: int = 0, *, db=None) -> int:
        """Delete PlaylistEvent rows with end_utc_ms <= now - 4 hours.

        INV-SCHEDULE-RETENTION-001: Tier 2 retains only rows where
        end_utc_ms > now - 4h. Throttled to at most once per hour.

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session to avoid
        opening a new connection when called from evaluate_once().

        Returns the number of rows deleted (0 if throttled or no-op).
        """
        if now_utc_ms == 0:
            now_utc_ms = self._now_utc_ms()

        # Hourly throttle
        if (now_utc_ms - self._last_tier2_purge_utc_ms) < 3_600_000:
            return 0

        from retrovue.domain.entities import PlaylistEvent

        cutoff_ms = now_utc_ms - (4 * 3_600_000)
        try:
            if db is not None:
                count = db.query(PlaylistEvent).filter(
                    PlaylistEvent.channel_slug == self._channel_id,
                    PlaylistEvent.end_utc_ms <= cutoff_ms,
                ).delete()
                db.commit()
            else:
                from retrovue.infra.uow import session as db_session_factory
                with db_session_factory() as db:
                    count = db.query(PlaylistEvent).filter(
                        PlaylistEvent.channel_slug == self._channel_id,
                        PlaylistEvent.end_utc_ms <= cutoff_ms,
                    ).delete()
            self._last_tier2_purge_utc_ms = now_utc_ms
            if count > 0:
                logger.info(
                    "INV-SCHEDULE-RETENTION-001: Purged %d expired Tier 2 rows "
                    "for channel=%s (end_utc_ms <= %d)",
                    count, self._channel_id, cutoff_ms,
                )
            return count
        except Exception as e:
            # INV-DAEMON-SESSION-RECOVERY-001: rollback poisoned transaction
            # so subsequent queries on the shared session can proceed.
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.warning(
                "INV-SCHEDULE-RETENTION-001: Tier 2 purge failed for channel=%s: %s",
                self._channel_id, e,
            )
            return 0

    # ------------------------------------------------------------------
    # Internal: extension logic
    # ------------------------------------------------------------------

    def _extend_to_target(self, now_ms: int, target_ms: int, *, db=None) -> int:
        """Fill blocks from Tier 1 until Tier 2 depth reaches target.

        INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001:
        - Rule 1: Batch PlaylistEvent existence checks per scan-day.
        - Rule 2: Yield GIL (time.sleep) after each block fill.

        INV-DAEMON-SESSION-SCOPE-001: Receives db from evaluate_once();
        does not open any sessions itself.
        """
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
            segmented_blocks = self._load_tier1_blocks(scan_date, db=db)
            if segmented_blocks is None:
                logger.debug(
                    "PlaylistBuilder[%s]: No Tier 1 data for %s — cannot extend",
                    self._channel_id, scan_date.isoformat(),
                )
                scan_date += timedelta(days=1)
                continue

            # Collect candidate block IDs for this scan-day (Rule 1)
            candidate_ids = []
            candidate_blocks = []
            for sb_dict in segmented_blocks:
                block_start = sb_dict["start_utc_ms"]
                block_end = sb_dict["end_utc_ms"]
                if block_end <= cursor_ms:
                    continue
                if block_start >= target_end_ms:
                    break
                candidate_ids.append(sb_dict["block_id"])
                candidate_blocks.append(sb_dict)

            # Rule 1: single batched query for all candidates in this day
            existing_ids = self._batch_block_exists_in_txlog(candidate_ids, db=db)

            for sb_dict in candidate_blocks:
                block_end = sb_dict["end_utc_ms"]
                block_id = sb_dict["block_id"]

                # Already in PlaylistEvent (checked via batch)
                if block_id in existing_ids:
                    if block_end > self._farthest_end_utc_ms:
                        self._farthest_end_utc_ms = block_end
                    continue

                # Canonical expansion: deserialize + fill ads
                try:
                    filled_block = expand_editorial_block(
                        sb_dict,
                        filler_uri=self._filler_path,
                        filler_duration_ms=self._filler_duration_ms,
                        asset_library=self._get_asset_library(db=db),
                        policy=self._traffic_policy,
                        break_config=self._break_config,
                    )

                    # Write to PlaylistEvent
                    # INV-TIER2-WINDOW-UUID-PROPAGATION-001: thread provenance
                    self._write_to_txlog(
                        filled_block, scan_date,
                        window_uuid=sb_dict.get("window_uuid"),
                        db=db,
                    )

                    self._last_fill_block_id = block_id
                    if block_end > self._farthest_end_utc_ms:
                        self._farthest_end_utc_ms = block_end
                    blocks_filled += 1

                    logger.debug(
                        "PlaylistBuilder[%s]: filled block=%s (%d segs)",
                        self._channel_id, block_id,
                        len(filled_block.segments),
                    )

                except Exception as e:
                    self._fill_errors += 1
                    # INV-DAEMON-SESSION-RECOVERY-001: rollback so next block can proceed
                    if db is not None:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                    logger.error(
                        "PlaylistBuilder[%s]: failed to fill block=%s: %s",
                        self._channel_id, block_id, e,
                    )

                # Rule 2: yield GIL after each block fill so upstream
                # reader thread can cycle select→recv→put.
                # 10ms minimum — 1ms was insufficient (UPSTREAM_LOOP
                # spikes of 260ms+ observed with 0.001).
                time.sleep(0.010)

            scan_date += timedelta(days=1)

        return blocks_filled

    def _ensure_tier2_covers_now(self, now_ms: int, *, db=None) -> int:
        """Backfill the Tier-1 block containing now_ms if Tier-2 has no row covering it.

        INV-PLAYLOG-COVERAGE-HOLE-001: Ensures Tier 2 always covers the block that
        contains now_ms (e.g. daemon started late or Tier-2 was empty). Backfill
        allowed only if now_ms < block_end (do not backfill wholly-past blocks).

        Returns 1 if a block was filled, 0 otherwise.
        """
        if self._tier2_row_covers_now(now_ms, db=db):
            return 0

        block = self._get_tier1_block_containing(now_ms, db=db)
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
            filled_block = expand_editorial_block(
                block,
                filler_uri=self._filler_path,
                filler_duration_ms=self._filler_duration_ms,
                asset_library=self._get_asset_library(db=db),
                policy=self._traffic_policy,
                break_config=self._break_config,
            )
            block_start_dt = datetime.fromtimestamp(
                block["start_utc_ms"] / 1000.0, tz=timezone.utc
            )
            broadcast_day = self._broadcast_date_for(block_start_dt)
            # INV-TIER2-WINDOW-UUID-PROPAGATION-001: thread provenance
            self._write_to_txlog(
                filled_block, broadcast_day,
                window_uuid=block.get("window_uuid"),
                db=db,
            )

            self._last_fill_block_id = block_id
            if block_end > self._farthest_end_utc_ms:
                self._farthest_end_utc_ms = block_end
            return 1
        except Exception as e:
            self._fill_errors += 1
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error(
                "PlaylistBuilder[%s]: backfill failed for block=%s: %s",
                self._channel_id, block_id, e,
            )
            return 0

    def _tier2_row_covers_now(self, now_ms: int, *, db=None) -> bool:
        """True if PlaylistEvent has a row covering now_ms (by time window).

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        """
        from retrovue.domain.entities import PlaylistEvent

        def _query(s):
            return (
                s.query(PlaylistEvent)
                .filter(
                    PlaylistEvent.channel_slug == self._channel_id,
                    PlaylistEvent.start_utc_ms <= now_ms,
                    PlaylistEvent.end_utc_ms > now_ms,
                )
                .first()
                is not None
            )

        try:
            if db is not None:
                return _query(db)
            from retrovue.infra.uow import session as db_session_factory
            with db_session_factory() as s:
                return _query(s)
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            return False

    def _get_tier1_block_containing(self, now_ms: int, *, db=None) -> dict | None:
        """Return the Tier-1 segmented block dict that contains now_ms, or None.

        Checks broadcast_date(now) and broadcast_date(now)-1 for day-boundary blocks.
        """
        now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
        bd = self._broadcast_date_for(now_dt)
        for scan_date in (bd - timedelta(days=1), bd):
            blocks = self._load_tier1_blocks(scan_date, db=db)
            if blocks is None:
                continue
            for sb_dict in blocks:
                if sb_dict["start_utc_ms"] <= now_ms < sb_dict["end_utc_ms"]:
                    return sb_dict
        return None

    def _load_tier1_blocks(self, broadcast_day: date, *, db=None) -> list[dict] | None:
        """Load Tier-1 segmented blocks from active ScheduleRevision only.

        Stage 4: ProgramLogDay JSON fallback removed.

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        """
        from retrovue.runtime.schedule_items_reader import (
            load_segmented_blocks_from_active_revision,
        )

        def _query(s):
            return load_segmented_blocks_from_active_revision(
                s,
                channel_slug=self._channel_id,
                broadcast_day=broadcast_day,
            )

        try:
            if db is not None:
                return _query(db)
            from retrovue.infra.uow import session as db_session_factory
            with db_session_factory() as s:
                return _query(s)
        except Exception as e:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error(
                "PlaylistBuilder[%s]: DB error loading Tier 1 for %s: %s",
                self._channel_id, broadcast_day.isoformat(), e,
            )
            return None

    def _block_exists_in_txlog(self, block_id: str) -> bool:
        """Check if a block already has a PlaylistEvent entry."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import PlaylistEvent

        try:
            with db_session_factory() as db:
                return db.query(PlaylistEvent).filter(
                    PlaylistEvent.block_id == block_id,
                ).first() is not None
        except Exception:
            return False

    def _batch_block_exists_in_txlog(self, block_ids: list[str], *, db=None) -> set[str]:
        """Batch-check which block_ids already have PlaylistEvent entries.

        INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 Rule 3:
        Returns set[str] of block_ids that already have Tier 2 entries.
        Single query per call: SELECT block_id ... WHERE block_id IN (...).

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        """
        if not block_ids:
            return set()

        from retrovue.domain.entities import PlaylistEvent

        def _query(s):
            rows = (
                s.query(PlaylistEvent.block_id)
                .filter(PlaylistEvent.block_id.in_(block_ids))
                .all()
            )
            return {r[0] for r in rows}

        try:
            if db is not None:
                return _query(db)
            from retrovue.infra.uow import session as db_session_factory
            with db_session_factory() as s:
                return _query(s)
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            return set()

    def _get_asset_library(self, *, db=None):
        """Create a DatabaseAssetLibrary for interstitial selection.

        INV-PLAYLOG-PREFILL-001: Ad fill happens at Tier 2 generation.
        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        """
        try:
            from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
            if db is not None:
                return DatabaseAssetLibrary(db, channel_slug=self._channel_id)
            from retrovue.infra.uow import session as db_session_factory
            with db_session_factory() as s:
                return DatabaseAssetLibrary(s, channel_slug=self._channel_id)
        except Exception as e:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.warning(
                "PlaylistBuilder[%s]: Could not create asset library: %s",
                self._channel_id, e,
            )
            return None

    def _write_to_txlog(
        self,
        block: "ScheduledBlock",
        broadcast_day: date,
        *,
        window_uuid: str | None = None,
        db=None,
    ) -> None:
        """Write a filled block to PlaylistEvent.

        INV-PLAYLOG-PREFILL-001: Canonical Tier 2 write path.
        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        INV-TIER2-WINDOW-UUID-PROPAGATION-001: Sets PlaylistEvent.window_uuid
        column from Tier 1 block dict when present.
        """
        from retrovue.domain.entities import PlaylistEvent

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
            if db is not None:
                # INV-TIER2-WINDOW-UUID-PROPAGATION-001: top-level column
                row = PlaylistEvent(
                    block_id=block.block_id,
                    channel_slug=self._channel_id,
                    broadcast_day=broadcast_day,
                    start_utc_ms=block.start_utc_ms,
                    end_utc_ms=block.end_utc_ms,
                    segments=segments_data,
                    window_uuid=window_uuid,
                )
                db.merge(row)
                db.commit()
            else:
                from retrovue.infra.uow import session as db_session_factory
                with db_session_factory() as db:
                    row = PlaylistEvent(
                        block_id=block.block_id,
                        channel_slug=self._channel_id,
                        broadcast_day=broadcast_day,
                        start_utc_ms=block.start_utc_ms,
                        end_utc_ms=block.end_utc_ms,
                        segments=segments_data,
                        window_uuid=window_uuid,
                    )
                    db.merge(row)
        except Exception as e:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error(
                "PlaylistBuilder[%s]: Failed to write block=%s to PlaylistEvent: %s",
                self._channel_id, block.block_id, e,
            )
            raise

    # ------------------------------------------------------------------
    # Internal: queries
    # ------------------------------------------------------------------

    def _get_frontier_utc_ms(self, *, db=None) -> int:
        """Get the farthest end_utc_ms in PlaylistEvent for this channel.

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        """
        from retrovue.domain.entities import PlaylistEvent
        import sqlalchemy as sa

        def _query(s):
            result = s.query(sa.func.max(PlaylistEvent.end_utc_ms)).filter(
                PlaylistEvent.channel_slug == self._channel_id,
            ).scalar()
            return result or 0

        try:
            if db is not None:
                return _query(db)
            from retrovue.infra.uow import session as db_session_factory
            with db_session_factory() as s:
                return _query(s)
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            return 0

    def _count_blocks_in_window(self, now_ms: int) -> int:
        """Count PlaylistEvent entries from now forward."""
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.domain.entities import PlaylistEvent

        try:
            with db_session_factory() as db:
                return db.query(PlaylistEvent).filter(
                    PlaylistEvent.channel_slug == self._channel_id,
                    PlaylistEvent.end_utc_ms > now_ms,
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
                    "PlaylistBuilder[%s]: evaluation failed", self._channel_id,
                )
            # Rule 4: jitter prevents thundering herd when multiple
            # daemons converge onto the same evaluation cadence.
            jitter = random.uniform(1.0, self._eval_interval_s * 0.25)
            self._stop_event.wait(timeout=self._eval_interval_s + jitter)

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
