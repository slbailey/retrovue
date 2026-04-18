"""
Dev-harness mock ScheduleService implementations.

These are used for --mock-schedule-ab and --mock-schedule-grid CLI modes.
They implement the ScheduleService protocol but do not use real schedule files.

Moved from retrovue.runtime.channel_manager — production modules contain only
production code. Dev-mode harnesses live here.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from retrovue.runtime.clock import AuthoritativeClock
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


class MockGridScheduleService:
    """ScheduleService implementation for mock grid + filler model.

    Implements the ScheduleService protocol using a fixed 30-minute grid
    and program + filler model. Used when running with --mock-schedule-grid.
    """

    def __init__(
        self,
        clock: AuthoritativeClock,
        program_asset_path: str,
        program_duration_seconds: float,
        filler_asset_path: str,
        filler_duration_seconds: float = 3600.0,  # Default 1-hour filler
        grid_block_minutes: int = 30,  # Fixed 30-minute grid
    ):
        self.clock = clock
        self.program_asset_path = program_asset_path
        self.program_duration_seconds = program_duration_seconds
        self.filler_asset_path = filler_asset_path
        self.filler_duration_seconds = filler_duration_seconds
        self.grid_block_minutes = grid_block_minutes
        self.filler_epoch = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        """
        No-op schedule loading (mock grid doesn't use schedule files).

        Returns:
            (success, error_message) tuple - always (True, None)
        """
        return (True, None)

    def _floor_to_grid(self, now: datetime) -> datetime:
        """Calculate grid block start time (floor to nearest grid boundary)."""
        current_minute = now.minute
        block_minute = (current_minute // self.grid_block_minutes) * self.grid_block_minutes
        return now.replace(minute=block_minute, second=0, microsecond=0)

    def _calculate_join_offset(
        self,
        now: datetime,
        block_start: datetime,
        program_duration_seconds: float,
    ) -> tuple[str, float]:
        """Calculate join-in-progress offset."""
        elapsed = (now - block_start).total_seconds()

        if elapsed < program_duration_seconds:
            # In program segment
            start_pts_ms = int(elapsed * 1000)
            return ("program", start_pts_ms)
        else:
            # In filler segment
            filler_offset = elapsed - program_duration_seconds
            start_pts_ms = int(filler_offset * 1000)
            return ("filler", start_pts_ms)

    def _calculate_filler_offset(
        self,
        master_clock: datetime,
        filler_epoch: datetime,
        filler_duration_seconds: float,
    ) -> float:
        """Calculate filler offset for continuous virtual stream."""
        time_diff = (master_clock - filler_epoch).total_seconds()
        return time_diff % filler_duration_seconds

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """
        Return playout plan using grid + filler model.

        Returns the complete block structure (program + filler) with proper metadata
        for clock-driven switching. This enables tick() to preload filler into preview
        BEFORE the program ends.

        INV-PREVIEW-NEVER-EMPTY: CORE must ensure preview has a segment loaded before
        the current live segment exhausts. Returning both segments allows tick() to
        determine the successor and preload it in time.

        Returns:
            List of segments in playback order, starting from the segment containing
            at_station_time. Each segment includes:
            - asset_path: Path to media file
            - start_pts: Join offset in milliseconds (for first segment only)
            - segment_type: "content" or "filler"
            - start_time_utc: When segment starts (ISO format)
            - end_time_utc: When segment ends (ISO format)
            - duration_seconds: Segment duration
            - frame_count: Frame budget (fps * duration)
        """
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Calculate grid block boundaries
        block_start = self._floor_to_grid(now)
        block_end = block_start + timedelta(minutes=self.grid_block_minutes)

        # Segment boundaries within block
        program_end = block_start + timedelta(seconds=self.program_duration_seconds)
        filler_duration = (block_end - program_end).total_seconds()

        # Default fps for frame_count calculation (30fps)
        fps = 30.0

        # Determine which segment we're in and build the segment list
        content_type, start_pts_ms = self._calculate_join_offset(
            now, block_start, self.program_duration_seconds
        )

        segments = []

        if content_type == "program":
            # Currently in program segment - return program + filler
            elapsed = (now - block_start).total_seconds()
            remaining_program = self.program_duration_seconds - elapsed

            program_segment = {
                "asset_path": self.program_asset_path,
                "start_pts": start_pts_ms,
                "segment_type": "content",
                "start_time_utc": block_start.isoformat(),
                "end_time_utc": program_end.isoformat(),
                "duration_seconds": remaining_program,  # Remaining from join point
                "frame_count": int(remaining_program * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                    "full_segment_duration": self.program_duration_seconds,
                },
            }
            segments.append(program_segment)

            # Add filler segment (successor) so tick() can preload it
            if filler_duration > 0:
                # INV-SCHED-GRID-FILLER-PADDING: Filler has explicit frame_count
                filler_frame_count = int(filler_duration * fps)
                filler_segment = {
                    "asset_path": self.filler_asset_path,
                    "start_pts": 0,  # Filler starts at frame 0
                    "segment_type": "filler",
                    "start_time_utc": program_end.isoformat(),
                    "end_time_utc": block_end.isoformat(),
                    "duration_seconds": filler_duration,
                    "frame_count": filler_frame_count,
                    "metadata": {
                        "phase": "mock_grid",
                        "grid_block_minutes": self.grid_block_minutes,
                    },
                }
                segments.append(filler_segment)
        else:
            # Currently in filler segment
            # Calculate filler join offset for continuous virtual stream
            filler_offset_seconds = self._calculate_filler_offset(
                now, self.filler_epoch, self.filler_duration_seconds
            )
            block_filler_offset_seconds = start_pts_ms / 1000.0
            filler_absolute_offset_seconds = (
                filler_offset_seconds + block_filler_offset_seconds
            ) % self.filler_duration_seconds

            elapsed_in_filler = (now - program_end).total_seconds()
            remaining_filler = filler_duration - elapsed_in_filler

            filler_segment = {
                "asset_path": self.filler_asset_path,
                "start_pts": int(filler_absolute_offset_seconds * 1000),
                "segment_type": "filler",
                "start_time_utc": program_end.isoformat(),
                "end_time_utc": block_end.isoformat(),
                "duration_seconds": remaining_filler,  # Remaining from join point
                "frame_count": int(remaining_filler * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                    "full_segment_duration": filler_duration,
                },
            }
            segments.append(filler_segment)

            # Add NEXT block's program as successor so tick() can preload it
            next_block_start = block_end
            next_program_end = next_block_start + timedelta(seconds=self.program_duration_seconds)
            next_program_segment = {
                "asset_path": self.program_asset_path,
                "start_pts": 0,  # Next block starts at frame 0
                "segment_type": "content",
                "start_time_utc": next_block_start.isoformat(),
                "end_time_utc": next_program_end.isoformat(),
                "duration_seconds": self.program_duration_seconds,
                "frame_count": int(self.program_duration_seconds * fps),
                "metadata": {
                    "phase": "mock_grid",
                    "grid_block_minutes": self.grid_block_minutes,
                },
            }
            segments.append(next_program_segment)

        return segments


class MockAlternatingScheduleService:
    """ScheduleService that alternates two assets (e.g. SampleA / SampleB) for Air harness testing.

    Segment boundaries are driven by process exit (natural EOF), not wall-clock. When the
    playout process exits, health-check calls get_playout_plan_now() to get the next asset
    and start_pts; segment_seconds is used only to pick which asset (A/B) and join offset.
    Each process runs until natural EOF; asset duration is never used to forcibly stop.
    """

    MOCK_AB_CHANNEL_ID = "test-1"

    def __init__(
        self,
        clock: AuthoritativeClock,
        asset_a_path: str,
        asset_b_path: str,
        segment_seconds: float = 10.0,
    ):
        self.clock = clock
        self.asset_a_path = asset_a_path
        self.asset_b_path = asset_b_path
        self.segment_seconds = segment_seconds
        self._loaded_channels: set[str] = set()
        self._lock = threading.Lock()
        self._epoch = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def load_schedule(self, channel_id: str) -> tuple[bool, str | None]:
        if channel_id != self.MOCK_AB_CHANNEL_ID:
            return (False, f"Alternating schedule only supports channel '{self.MOCK_AB_CHANNEL_ID}'")
        with self._lock:
            self._loaded_channels.add(channel_id)
        return (True, None)

    def get_playout_plan_now(
        self,
        channel_id: str,
        at_station_time: datetime,
    ) -> list[dict[str, Any]]:
        """Return current segment: A or B depending on (time // segment_seconds) % 2, with join offset."""
        with self._lock:
            if channel_id != self.MOCK_AB_CHANNEL_ID or channel_id not in self._loaded_channels:
                return []
        now = at_station_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        total_seconds = (now - self._epoch).total_seconds()
        segment_index = int(total_seconds // self.segment_seconds)
        use_a = (segment_index % 2) == 0
        offset_in_segment = total_seconds % self.segment_seconds
        start_pts_ms = int(offset_in_segment * 1000)
        asset_path = self.asset_a_path if use_a else self.asset_b_path
        content_type = "a" if use_a else "b"
        segment = {
            "asset_path": asset_path,
            "start_pts": start_pts_ms,
            "content_type": content_type,
            "segment_index": segment_index,
            "metadata": {"phase": "mock_ab", "segment_seconds": self.segment_seconds},
        }
        return [segment]

    def get_block_at(self, channel_id: str, utc_ms: int) -> "ScheduledBlock | None":
        """Return the wall-clock block covering ``utc_ms`` (BlockPlan / ChannelManager).

        Grid aligns to ``self._epoch`` (same basis as ``get_playout_plan_now``) with
        one segment per ``segment_seconds`` window, alternating asset A and B.
        """
        with self._lock:
            if channel_id != self.MOCK_AB_CHANNEL_ID or channel_id not in self._loaded_channels:
                return None
        seg_ms = int(round(self.segment_seconds * 1000.0))
        if seg_ms <= 0:
            return None
        epoch_ms = int(self._epoch.timestamp() * 1000)
        rel = utc_ms - epoch_ms
        if rel < 0:
            # Wall clock before Unix epoch — no block (harness uses real "now").
            return None
        segment_index = rel // seg_ms
        block_start_ms = epoch_ms + segment_index * seg_ms
        block_end_ms = block_start_ms + seg_ms
        use_a = (segment_index % 2) == 0
        asset_uri = self.asset_a_path if use_a else self.asset_b_path
        block_id = f"mock-ab-{segment_index}"
        seg = ScheduledSegment(
            segment_type="content",
            asset_uri=asset_uri,
            asset_start_offset_ms=0,
            segment_duration_ms=seg_ms,
        )
        return ScheduledBlock(
            block_id=block_id,
            start_utc_ms=block_start_ms,
            end_utc_ms=block_end_ms,
            segments=(seg,),
        )
