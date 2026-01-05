"""
AsRun Logger

Pattern: Observer + Data Recorder

The AsRunLogger is responsible for recording what actually aired on each channel,
providing accurate playout logs for reporting, compliance, and analytics.

Key Responsibilities:
- Record actual playout events as they happen
- Tag events with correct broadcast day labels
- Handle broadcast day rollover scenarios
- Provide accurate as-run data for reporting

Broadcast Day Behavior:
- AsRunLogger MUST call ScheduleService.broadcast_day_for(channel_id, when_utc)
  for each playout event or subsegment.
- AsRunLogger is allowed to split a single continuous asset into multiple as-run
  rows across a broadcast day boundary.
- Example: Movie 05:00–07:00 turns into:
  - Row A: 05:00–06:00 tagged broadcast_day=2025-10-24
  - Row B: 06:00–07:00 tagged broadcast_day=2025-10-25
- This is not an error. This is expected and correct.
- Document that in the AsRunLogger code comments so reporting later can pull
  "everything that aired on 2025-10-24 broadcast day" and get the correct partial segment.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AsRunEvent:
    """Record of what actually aired"""

    event_id: str
    channel_id: str
    program_id: str
    asset_id: str
    start_time_utc: datetime
    end_time_utc: datetime
    broadcast_day: str  # Date label for the broadcast day
    segment_type: str  # "content", "commercial", "bumper", etc.
    duration_seconds: float
    metadata: dict[str, Any]


class AsRunLogger:
    """
    Records what actually aired on each channel.

    Pattern: Observer + Data Recorder

    This component observes playout events and records them with accurate
    broadcast day labels for reporting and compliance.

    BROADCAST DAY BEHAVIOR (06:00 → 06:00):
    - AsRunLogger MUST call ScheduleService.broadcast_day_for(channel_id, when_utc)
      for each playout event or subsegment.
    - AsRunLogger is allowed to split a single continuous asset into multiple as-run
      rows across a broadcast day boundary.
    - Example: Movie 05:00–07:00 turns into:
      - Row A: 05:00–06:00 tagged broadcast_day=2025-10-24
      - Row B: 06:00–07:00 tagged broadcast_day=2025-10-25
    - This is not an error. This is expected and correct.
    - Document that in the AsRunLogger code comments so reporting later can pull
      "everything that aired on 2025-10-24 broadcast day" and get the correct partial segment.
    """

    def __init__(self, schedule_service=None):
        """
        Initialize the AsRun Logger.

        Args:
            schedule_service: ScheduleService instance for broadcast day lookups
        """
        self.schedule_service = schedule_service
        self.events: list[AsRunEvent] = []

    def log_playout_start(
        self,
        channel_id: str,
        program_id: str,
        asset_id: str,
        start_time_utc: datetime,
        segment_type: str = "content",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Log the start of a playout event.

        Args:
            channel_id: Channel that's airing
            program_id: Program identifier
            asset_id: Asset being played
            start_time_utc: When playback started (UTC, timezone-aware)
            segment_type: Type of segment (content, commercial, bumper, etc.)
            metadata: Additional metadata

        Returns:
            Event ID for tracking

        Raises:
            ValueError if start_time_utc is naive
        """
        if start_time_utc.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        # Get broadcast day label from ScheduleService
        if self.schedule_service:
            broadcast_day = self.schedule_service.broadcast_day_for(channel_id, start_time_utc)
            broadcast_day_str = broadcast_day.isoformat()
        else:
            # Fallback if no ScheduleService available
            broadcast_day_str = start_time_utc.date().isoformat()

        event_id = f"{channel_id}_{program_id}_{start_time_utc.timestamp()}"

        event = AsRunEvent(
            event_id=event_id,
            channel_id=channel_id,
            program_id=program_id,
            asset_id=asset_id,
            start_time_utc=start_time_utc,
            end_time_utc=start_time_utc,  # Will be updated when playout ends
            broadcast_day=broadcast_day_str,
            segment_type=segment_type,
            duration_seconds=0.0,
            metadata=metadata or {},
        )

        self.events.append(event)
        return event_id

    def log_playout_end(self, event_id: str, end_time_utc: datetime) -> None:
        """
        Log the end of a playout event.

        Args:
            event_id: Event ID from log_playout_start
            end_time_utc: When playback ended (UTC, timezone-aware)

        Raises:
            ValueError if end_time_utc is naive
        """
        if end_time_utc.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        # Find the event and update it
        for event in self.events:
            if event.event_id == event_id:
                event.end_time_utc = end_time_utc
                event.duration_seconds = (end_time_utc - event.start_time_utc).total_seconds()
                break

    def log_broadcast_day_rollover(self, channel_id: str, rollover_time_utc: datetime) -> None:
        """
        Log a broadcast day rollover event.

        This is called when a program spans the 06:00 rollover boundary.
        The AsRunLogger may need to split the continuous playout into
        multiple as-run records for proper broadcast day reporting.

        Args:
            channel_id: Channel experiencing rollover
            rollover_time_utc: UTC time of the 06:00 rollover
        """
        if rollover_time_utc.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        # TODO: Implement rollover handling
        # This would involve:
        # 1. Finding active playout that spans the rollover
        # 2. Creating a new as-run record for the post-rollover portion
        # 3. Ensuring both records have correct broadcast day labels
        pass

    def get_events_for_broadcast_day(self, channel_id: str, broadcast_day: str) -> list[AsRunEvent]:
        """
        Get all as-run events for a specific broadcast day.

        Args:
            channel_id: Channel to query
            broadcast_day: Broadcast day label (YYYY-MM-DD format)

        Returns:
            List of AsRunEvent records for that broadcast day
        """
        return [
            event
            for event in self.events
            if event.channel_id == channel_id and event.broadcast_day == broadcast_day
        ]

    def get_events_for_time_range(
        self, channel_id: str, start_time_utc: datetime, end_time_utc: datetime
    ) -> list[AsRunEvent]:
        """
        Get all as-run events in a time range.

        Args:
            channel_id: Channel to query
            start_time_utc: Start of time range (UTC, timezone-aware)
            end_time_utc: End of time range (UTC, timezone-aware)

        Returns:
            List of AsRunEvent records in the time range
        """
        if start_time_utc.tzinfo is None or end_time_utc.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        return [
            event
            for event in self.events
            if (
                event.channel_id == channel_id
                and event.start_time_utc >= start_time_utc
                and event.end_time_utc <= end_time_utc
            )
        ]

    def get_continuous_playout_spanning_rollover(
        self, channel_id: str, rollover_time_utc: datetime
    ) -> AsRunEvent | None:
        """
        Get any continuous playout that spans the broadcast day rollover.

        This is used to identify programs that started before 06:00 and continue after.

        Args:
            channel_id: Channel to check
            rollover_time_utc: UTC time of the 06:00 rollover

        Returns:
            AsRunEvent if there's a continuous playout spanning rollover, None otherwise
        """
        if rollover_time_utc.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        # Find events that started before rollover and end after rollover
        for event in self.events:
            if (
                event.channel_id == channel_id
                and event.start_time_utc < rollover_time_utc
                and event.end_time_utc > rollover_time_utc
            ):
                return event

        return None
