"""Horizon-Backed Schedule Service — Read-Only Execution Consumer.

Implements the ScheduleService protocol expected by ChannelManager
by reading exclusively from pre-populated stores.  Never triggers
schedule resolution, pipeline execution, or any planning activity.

Used in AUTHORITATIVE horizon mode.  Violations (missing data) are
reported as planning failures per ScheduleExecutionInterface §6.

See: docs/contracts/ScheduleExecutionInterfaceContract_v0.1.md
     docs/contracts/ScheduleHorizonManagementContract_v0.1.md §7
     docs/domains/HorizonManager_v0.1.md §6 (Data Flow)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from retrovue.runtime.execution_window_store import ExecutionWindowStore
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

logger = logging.getLogger(__name__)


class HorizonBackedScheduleService:
    """Schedule service backed by HorizonManager-populated stores.

    Read-only.  All planning artifacts are pre-built by HorizonManager.
    If data is missing at read time, this is a planning failure —
    the service logs a POLICY_VIOLATION and returns an empty result
    or raises, depending on the caller's expectation.

    Implements:
    - get_playout_plan_now(channel_id, at_station_time) -> list[dict]
    - get_epg_events(channel_id, start_time, end_time) -> list[dict]
    - load_schedule(channel_id) -> (bool, str | None)
    """

    def __init__(
        self,
        execution_store: ExecutionWindowStore,
        resolved_store=None,  # Optional ResolvedScheduleStore
        programming_day_start_hour: int = 6,
        grid_block_minutes: int = 30,
        channel_id: str = "",
    ) -> None:
        self._execution_store = execution_store
        self._resolved_store = resolved_store
        self._day_start_hour = programming_day_start_hour
        self._grid_minutes = grid_block_minutes
        self._channel_id = channel_id

    # ------------------------------------------------------------------
    # ScheduleService protocol
    # ------------------------------------------------------------------

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """No-op.  Data comes from stores populated by HorizonManager."""
        return (True, None)

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return the block plan covering *at_station_time*.

        Reads from ExecutionWindowStore.  Never triggers planning.
        If no entry covers the requested time, logs POLICY_VIOLATION
        and returns [].
        """
        if at_station_time.tzinfo is None:
            at_station_time = at_station_time.replace(tzinfo=timezone.utc)

        utc_ms = int(at_station_time.timestamp() * 1000)

        entry = self._execution_store.get_entry_at(utc_ms, locked_only=True)

        if entry is None:
            logger.warning(
                "POLICY_VIOLATION: No locked execution entry for "
                "channel=%s at %s (utc_ms=%d). "
                "This is a horizon maintenance failure. "
                "ChannelManager must not compensate.",
                channel_id,
                at_station_time.isoformat(),
                utc_ms,
            )
            return []

        # Convert TransmissionLog segments to the format expected by
        # ChannelManager / BlockPlanProducer consumers.
        return self._entry_to_playout_plan(entry, at_station_time)

    def get_epg_events(
        self,
        channel_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return EPG events from pre-resolved store.

        Reads from ResolvedStore only.  Never triggers resolution.
        If no data is available, returns [] with a log.
        """
        if self._resolved_store is None:
            logger.info(
                "HorizonBackedScheduleService: No resolved_store; "
                "EPG unavailable for %s",
                channel_id,
            )
            return []

        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        events: list[dict[str, Any]] = []
        grid_seconds = self._grid_minutes * 60

        current = start_time
        while current < end_time:
            bd = self._broadcast_date_for(current)
            resolved = self._resolved_store.get(channel_id, bd)

            if resolved is None:
                logger.info(
                    "HorizonBackedScheduleService: No resolved day "
                    "for channel=%s date=%s (read-only; not resolving)",
                    channel_id,
                    bd.isoformat(),
                )
                current += timedelta(days=1)
                continue

            # Build EPG events from resolved program events
            if hasattr(resolved, "program_events") and resolved.program_events:
                slot_idx = 0
                for pe in resolved.program_events:
                    if slot_idx >= len(resolved.resolved_slots):
                        break
                    first_slot = resolved.resolved_slots[slot_idx]
                    event_start = self._slot_to_datetime(bd, first_slot.slot_time)
                    event_end = event_start + timedelta(
                        seconds=pe.block_span_count * grid_seconds
                    )

                    if event_start.tzinfo is None:
                        event_start = event_start.replace(tzinfo=timezone.utc)
                    if event_end.tzinfo is None:
                        event_end = event_end.replace(tzinfo=timezone.utc)

                    if event_start < end_time and event_end > start_time:
                        resolved_asset = pe.resolved_asset or first_slot.resolved_asset
                        events.append({
                            "channel_id": channel_id,
                            "start_time": event_start.isoformat(),
                            "end_time": event_end.isoformat(),
                            "title": resolved_asset.title,
                            "episode_title": resolved_asset.episode_title,
                            "episode_id": resolved_asset.episode_id,
                            "programming_day_date": bd.isoformat(),
                            "asset": {
                                "file_path": resolved_asset.file_path,
                                "asset_id": resolved_asset.asset_id,
                                "duration_seconds": resolved_asset.content_duration_seconds,
                            },
                        })

                    slot_idx += pe.block_span_count

            current += timedelta(days=1)

        return events

    def get_block_at(self, channel_id: str, utc_ms: int) -> ScheduledBlock | None:
        """Return a ScheduledBlock covering utc_ms from ExecutionWindowStore.

        Pure read — does not trigger schedule generation.
        """
        entry = self._execution_store.get_entry_at(utc_ms, locked_only=True)
        if entry is None:
            logger.warning(
                "POLICY_VIOLATION: No locked execution entry for "
                "channel=%s at utc_ms=%d. "
                "This is a horizon maintenance failure.",
                channel_id, utc_ms,
            )
            return None
        return ScheduledBlock(
            block_id=entry.block_id,
            start_utc_ms=entry.start_utc_ms,
            end_utc_ms=entry.end_utc_ms,
            segments=tuple(
                ScheduledSegment(
                    segment_type=s.get("segment_type", "episode"),
                    asset_uri=s.get("asset_uri", ""),
                    asset_start_offset_ms=s.get("asset_start_offset_ms", 0),
                    segment_duration_ms=s.get("segment_duration_ms", 0),
                )
                for s in entry.segments
            ),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _entry_to_playout_plan(
        self,
        entry,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Convert an ExecutionEntry to the playout plan list format.

        Returns the full list of segments for the block, with wall-clock
        start/end times computed from block start and segment durations.
        The active segment (containing at_station_time) is first.
        """
        block_start_ms = entry.start_utc_ms
        result: list[dict[str, Any]] = []
        cursor_ms = block_start_ms
        now_ms = int(at_station_time.timestamp() * 1000)

        for seg in entry.segments:
            seg_dur_ms = seg.get("segment_duration_ms", 0)
            seg_end_ms = cursor_ms + seg_dur_ms
            seg_type = seg.get("segment_type", "episode")
            asset_uri = seg.get("asset_uri", "")
            asset_offset_ms = seg.get("asset_start_offset_ms", 0)

            # Skip pad segments — ChannelManager doesn't consume them
            # as playout plan entries (AIR handles pad via PadProducer).
            if seg_type == "pad":
                cursor_ms = seg_end_ms
                continue

            # If this is a past segment (already fully elapsed), skip it
            if seg_end_ms <= now_ms:
                cursor_ms = seg_end_ms
                continue

            # Compute effective seek offset for mid-join
            if now_ms > cursor_ms:
                elapsed_ms = now_ms - cursor_ms
                effective_offset_ms = asset_offset_ms + elapsed_ms
            else:
                effective_offset_ms = asset_offset_ms

            seg_start_dt = datetime.fromtimestamp(
                cursor_ms / 1000.0, tz=timezone.utc
            )
            seg_end_dt = datetime.fromtimestamp(
                seg_end_ms / 1000.0, tz=timezone.utc
            )

            result.append({
                "asset_path": asset_uri,
                "start_pts": effective_offset_ms,
                "duration_seconds": seg_dur_ms / 1000.0,
                "start_time_utc": seg_start_dt.isoformat(),
                "end_time_utc": seg_end_dt.isoformat(),
                "segment_type": seg_type,
                "metadata": {
                    "phase": "horizon_backed",
                    "grid_minutes": self._grid_minutes,
                    "block_id": entry.block_id,
                },
            })
            cursor_ms = seg_end_ms

        return result

    def _broadcast_date_for(self, dt: datetime) -> date:
        if dt.hour < self._day_start_hour:
            return (dt - timedelta(days=1)).date()
        return dt.date()

    def _slot_to_datetime(self, programming_day_date: date, slot_time) -> datetime:
        base = datetime.combine(programming_day_date, slot_time)
        if slot_time.hour < self._day_start_hour:
            base += timedelta(days=1)
        return base
