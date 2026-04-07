"""Playlist Builder Daemon — maintains the Playlog Plan horizon.

Maintains a rolling window of fully-filled PlaylistEvent rows (the playlog plan) 2–3+ hours
ahead of the current wall-clock time. Consumes pre-segmented blocks from
program schedule (active ScheduleRevision/ScheduleItems), fills ad break placeholders
via the traffic manager, and writes the result to PlaylistEvent (Postgres).

ChannelManager reads PlaylistEvent directly — no ad fill or schedule
compilation at feed time.

See: docs/architecture/program-schedule-playlog-plan-horizon.md
     INV-PLAYLOG-HORIZON-001: playlog plan maintains ≥2 hours coverage
     INV-PLAYLOG-PREFILL-001: Ad fill at playlog plan generation, never at feed time
     INV-CHANNEL-NO-COMPILE-001: ChannelManager never compiles or fills ads

Lifecycle: start()/stop() run a background daemon thread.
           evaluate_once() can be called manually for testing.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retrovue.runtime.schedule_items_reader import expand_editorial_block

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INV-BLOCKFILL-SUBPROCESS-ISOLATION-001: Module-level worker for subprocess
# ---------------------------------------------------------------------------

def _subprocess_expand_blocks(payload: dict) -> list[dict]:
    """Expand editorial blocks in a subprocess for memory isolation.

    INV-BLOCKFILL-SUBPROCESS-ISOLATION-001: This function runs in a child
    process. When it returns, the child exits and all memory allocated during
    expansion (deserialization, traffic fill, candidate caches) is returned
    to the OS — eliminating allocator fragmentation in the daemon process.

    The child creates its own short-lived DB session for the asset library.
    The session and connection die with the process.

    Args:
        payload: dict with keys: channel_id, blocks (list of sb_dict),
                 filler_uri, filler_duration_ms, policy, break_config.

    Returns:
        List of result dicts, one per input block:
        {"block_id": str, "ok": True, "serialized": dict} on success,
        {"block_id": str, "ok": False, "error": str} on failure.
    """
    # Late imports: subprocess has its own module state.
    from retrovue.runtime.schedule_items_reader import expand_editorial_block
    from retrovue.runtime.dsl_schedule_service import _serialize_scheduled_block

    channel_id = payload["channel_id"]
    filler_uri = payload["filler_uri"]
    filler_duration_ms = payload["filler_duration_ms"]
    policy = payload.get("policy")
    break_config = payload.get("break_config")

    # Create a short-lived DB session for asset library queries.
    asset_library = None
    db_session = None
    try:
        from retrovue.infra.uow import session as db_session_factory
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
        db_session = db_session_factory()
        asset_library = DatabaseAssetLibrary(db_session, channel_slug=channel_id)
    except Exception:
        pass  # Fall back to filler-only mode if DB unavailable.

    results = []
    try:
        for sb_dict in payload["blocks"]:
            block_id = sb_dict.get("block_id", "unknown")
            try:
                filled = expand_editorial_block(
                    sb_dict,
                    filler_uri=filler_uri,
                    filler_duration_ms=filler_duration_ms,
                    asset_library=asset_library,
                    policy=policy,
                    break_config=break_config,
                )
                results.append({
                    "block_id": block_id,
                    "ok": True,
                    "serialized": _serialize_scheduled_block(filled),
                })
            except Exception as e:
                results.append({
                    "block_id": block_id,
                    "ok": False,
                    "error": str(e),
                })
    finally:
        if db_session is not None:
            try:
                db_session.close()
            except Exception:
                pass

    return results


# Log INV-PLAYLOG-HORIZON-002 at WARNING only on first consecutive zero; later repeats at DEBUG.
# When the program schedule has no next-day blocks (e.g. compile not run yet), 0 blocks filled every tick.
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
    """Rolling playlog plan horizon: pre-filled playlist events in Postgres.

    Write path:
        evaluate_once() → reads program schedule blocks, fills ads, writes PlaylistEvent

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
        program_schedule_extend_callback: Any = None,
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
        # INV-EPG-VIEWER-INDEPENDENT-001: Callback to extend program schedule horizon
        # when the daemon discovers missing days. Signature: (channel_id, now_utc_ms) -> None
        self._program_schedule_extend = program_schedule_extend_callback

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
        self._last_playlog_plan_purge_utc_ms: int = 0

        # Lifecycle
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_once(self) -> int:
        """Evaluate playlog plan depth and extend if below threshold.

        INV-PLAYLOG-COVERAGE-HOLE-001: Ensures playlog plan always covers the block
        containing now_ms (backfill current block if missing) before forward fill.

        INV-DAEMON-SESSION-SCOPE-001: Opens at most one database session per
        cycle and passes it to all sub-methods.

        Returns the number of blocks filled in this evaluation.
        """
        from retrovue.infra.uow import session as db_session_factory

        now_ms = self._now_utc_ms()
        self._last_evaluation_utc_ms = now_ms

        # INV-EPG-VIEWER-INDEPENDENT-001: Proactively extend program schedule horizon
        # so EPG data stays fresh even when no viewers are connected.
        if self._program_schedule_extend is not None:
            try:
                self._program_schedule_extend(self._channel_id, now_ms)
            except Exception as e:
                logger.debug(
                    "PlaylistBuilder[%s]: program schedule extend callback failed: %s",
                    self._channel_id, e,
                )

        with db_session_factory() as db:
            # Pre-step: ensure playlog plan covers the block containing now (backfill if hole)
            backfill_count = self._ensure_playlog_plan_covers_now(now_ms, db=db)

            # Discover current playlog plan frontier
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

            # Need to extend: find program schedule blocks that don't yet have playlog plan entries
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

            # INV-SCHEDULE-RETENTION-001: purge expired playlog plan DB rows
            self._purge_expired_playlog_plan(now_ms, db=db)

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

    def _purge_expired_playlog_plan(self, now_utc_ms: int = 0, *, db=None) -> int:
        """Delete PlaylistEvent rows with end_utc_ms <= now - 4 hours.

        INV-SCHEDULE-RETENTION-001: playlog plan retains only rows where
        end_utc_ms > now - 4h. Throttled to at most once per hour.

        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session to avoid
        opening a new connection when called from evaluate_once().

        Returns the number of rows deleted (0 if throttled or no-op).
        """
        if now_utc_ms == 0:
            now_utc_ms = self._now_utc_ms()

        # Hourly throttle
        if (now_utc_ms - self._last_playlog_plan_purge_utc_ms) < 3_600_000:
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
            self._last_playlog_plan_purge_utc_ms = now_utc_ms
            if count > 0:
                logger.info(
                    "INV-SCHEDULE-RETENTION-001: Purged %d expired playlog plan rows "
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
                "INV-SCHEDULE-RETENTION-001: playlog plan purge failed for channel=%s: %s",
                self._channel_id, e,
            )
            return 0

    # ------------------------------------------------------------------
    # Internal: extension logic
    # ------------------------------------------------------------------

    def _extend_to_target(self, now_ms: int, target_ms: int, *, db=None) -> int:
        """Fill from program schedule until playlog plan depth reaches target.

        INV-BLOCKFILL-SUBPROCESS-ISOLATION-001: Block expansion runs in a
        subprocess. When the child exits, all memory from deserialization
        and traffic fill is returned to the OS.

        INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001:
        - Rule 1: Batch PlaylistEvent existence checks per scan-day.
        - Rule 2: Yield GIL (time.sleep) after each block write.

        INV-DAEMON-SESSION-SCOPE-001: Receives db from evaluate_once();
        does not open any sessions itself. DB writes remain in parent.
        """
        target_end_ms = now_ms + target_ms

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

        # Phase 1: Collect all candidate blocks needing fill (parent process).
        # Each entry: (sb_dict, scan_date) — scan_date needed for DB write.
        blocks_to_fill: list[tuple[dict, date]] = []

        while scan_date <= end_date and cursor_ms < target_end_ms:
            segmented_blocks = self._load_program_schedule_blocks(scan_date, db=db)
            if segmented_blocks is None:
                logger.debug(
                    "PlaylistBuilder[%s]: No program schedule data for %s — cannot extend",
                    self._channel_id, scan_date.isoformat(),
                )
                scan_date += timedelta(days=1)
                continue

            # Rule 1: Collect candidate block IDs for this scan-day
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
                block_id = sb_dict["block_id"]
                block_end = sb_dict["end_utc_ms"]

                if block_id in existing_ids:
                    if block_end > self._farthest_end_utc_ms:
                        self._farthest_end_utc_ms = block_end
                    continue

                blocks_to_fill.append((sb_dict, scan_date))

            scan_date += timedelta(days=1)

        if not blocks_to_fill:
            return 0

        # Phase 2: Expand blocks in subprocess (memory isolation).
        # INV-BLOCKFILL-SUBPROCESS-ISOLATION-001: max_tasks_per_child=1
        # guarantees the child process exits after each batch, releasing
        # all memory back to the OS.
        payload = {
            "channel_id": self._channel_id,
            "blocks": [entry[0] for entry in blocks_to_fill],
            "filler_uri": self._filler_path,
            "filler_duration_ms": self._filler_duration_ms,
            "policy": self._traffic_policy,
            "break_config": self._break_config,
        }

        try:
            with ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as executor:
                future = executor.submit(_subprocess_expand_blocks, payload)
                results = future.result(timeout=120)
        except Exception as e:
            logger.error(
                "PlaylistBuilder[%s]: subprocess block expansion failed: %s",
                self._channel_id, e,
            )
            self._fill_errors += len(blocks_to_fill)
            return 0

        # Phase 3: Write results to DB (parent process).
        # INV-DAEMON-SESSION-SCOPE-001: uses the session from evaluate_once().
        from retrovue.runtime.dsl_schedule_service import _deserialize_scheduled_block

        blocks_filled = 0
        for result, (sb_dict, scan_date) in zip(results, blocks_to_fill):
            block_id = result["block_id"]
            block_end = sb_dict["end_utc_ms"]

            if not result["ok"]:
                self._fill_errors += 1
                if db is not None:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                logger.error(
                    "PlaylistBuilder[%s]: failed to fill block=%s: %s",
                    self._channel_id, block_id, result.get("error", "unknown"),
                )
                # Rule 2: yield GIL even on error
                time.sleep(0.010)
                continue

            try:
                filled_block = _deserialize_scheduled_block(result["serialized"])

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
                if db is not None:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                logger.error(
                    "PlaylistBuilder[%s]: failed to write block=%s: %s",
                    self._channel_id, block_id, e,
                )

            # Rule 2: yield GIL after each block write so upstream
            # reader thread can cycle select→recv→put.
            # 10ms minimum — 1ms was insufficient (UPSTREAM_LOOP
            # spikes of 260ms+ observed with 0.001).
            time.sleep(0.010)

        return blocks_filled

    def _ensure_playlog_plan_covers_now(self, now_ms: int, *, db=None) -> int:
        """Backfill the program schedule block containing now_ms if playlog plan has no row covering it.

        INV-PLAYLOG-COVERAGE-HOLE-001: Ensures playlog plan always covers the block that
        contains now_ms (e.g. daemon started late or playlog plan was empty). Backfill
        allowed only if now_ms < block_end (do not backfill wholly-past blocks).

        Returns 1 if a block was filled, 0 otherwise.
        """
        if self._playlog_plan_row_covers_now(now_ms, db=db):
            return 0

        block = self._get_program_schedule_block_containing(now_ms, db=db)
        if block is None:
            return 0

        block_end = block["end_utc_ms"]
        if now_ms >= block_end:
            return 0

        block_id = block["block_id"]
        logger.warning(
            "INV-PLAYLOG-COVERAGE-HOLE-001: missing playlog plan coverage for now_ms=%d "
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

    def _playlog_plan_row_covers_now(self, now_ms: int, *, db=None) -> bool:
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

    def _get_program_schedule_block_containing(self, now_ms: int, *, db=None) -> dict | None:
        """Return the program schedule segmented block dict that contains now_ms, or None.

        Checks broadcast_date(now) and broadcast_date(now)-1 for day-boundary blocks.
        """
        now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
        bd = self._broadcast_date_for(now_dt)
        for scan_date in (bd - timedelta(days=1), bd):
            blocks = self._load_program_schedule_blocks(scan_date, db=db)
            if blocks is None:
                continue
            for sb_dict in blocks:
                if sb_dict["start_utc_ms"] <= now_ms < sb_dict["end_utc_ms"]:
                    return sb_dict
        return None

    def _load_program_schedule_blocks(self, broadcast_day: date, *, db=None) -> list[dict] | None:
        """Load program schedule segmented blocks from active ScheduleRevision only.

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
                "PlaylistBuilder[%s]: DB error loading program schedule for %s: %s",
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
        Returns set[str] of block_ids that already have playlog plan entries.
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

        INV-PLAYLOG-PREFILL-001: Ad fill happens at playlog plan generation.
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

        INV-PLAYLOG-PREFILL-001: Canonical playlog plan write path.
        INV-DAEMON-SESSION-SCOPE-001: Accepts optional db session.
        INV-TIER2-WINDOW-UUID-PROPAGATION-001: Sets PlaylistEvent.window_uuid
        column from program schedule block dict when present.
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

            # INV-LOUDNESS-NORMALIZED-001: persist gain_db when non-zero
            if seg.gain_db != 0.0:
                d["gain_db"] = seg.gain_db

            # Preserve transition fields if present
            if seg.transition_in != "TRANSITION_NONE":
                d["transition_in"] = seg.transition_in
                d["transition_in_duration_ms"] = seg.transition_in_duration_ms
            if seg.transition_out != "TRANSITION_NONE":
                d["transition_out"] = seg.transition_out
                d["transition_out_duration_ms"] = seg.transition_out_duration_ms

            segments_data.append(d)

        # INV-PLAYOUT-WRITE-ONCE-001: Use INSERT ... ON CONFLICT DO NOTHING
        # so an existing PlaylistEvent row is never overwritten.  The daemon
        # already checks _batch_block_exists_in_txlog before calling this,
        # but a race with ensure_block_compiled is possible.  The DO NOTHING
        # clause makes the write idempotent and preserves the first writer.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        values = dict(
            block_id=block.block_id,
            channel_slug=self._channel_id,
            broadcast_day=broadcast_day,
            start_utc_ms=block.start_utc_ms,
            end_utc_ms=block.end_utc_ms,
            segments=segments_data,
            window_uuid=window_uuid,
        )

        try:
            if db is not None:
                stmt = pg_insert(PlaylistEvent.__table__).values(
                    **values,
                ).on_conflict_do_nothing(index_elements=["block_id"])
                result = db.execute(stmt)
                db.commit()
                if result.rowcount == 0:
                    logger.debug(
                        "INV-PLAYOUT-WRITE-ONCE-001: PlaylistBuilder[%s] "
                        "block=%s already persisted — skipping",
                        self._channel_id, block.block_id,
                    )
            else:
                from retrovue.infra.uow import session as db_session_factory
                with db_session_factory() as s:
                    stmt = pg_insert(PlaylistEvent.__table__).values(
                        **values,
                    ).on_conflict_do_nothing(index_elements=["block_id"])
                    result = s.execute(stmt)
                    if result.rowcount == 0:
                        logger.debug(
                            "INV-PLAYOUT-WRITE-ONCE-001: PlaylistBuilder[%s] "
                            "block=%s already persisted — skipping",
                            self._channel_id, block.block_id,
                        )
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
        # ContainerDiscoveryContract / CatalogReconciliationContract: container refresh
        # (discovery + reconciliation for configured containers) MUST run before
        # horizon expansion. Wire container_refresh here when invoked by scheduler.
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
