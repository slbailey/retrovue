from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .base import (
    ContentSegment,
    Producer,
    ProducerMode,
    ProducerStatus,
    SegmentEdge,
)


@dataclass
class _SegmentTiming:
    segment: ContentSegment
    start_offset: float
    end_offset: float

    @property
    def duration(self) -> float:
        return self.end_offset - self.start_offset


class FFmpegSegmentProducer(Producer):
    """
    Stubbed FFmpeg-backed producer that supports time-addressable playback.

    The implementation is intentionally minimal: it does not spawn FFmpeg yet,
    but it models the pacing contract required by ChannelManager and the runtime.
    """

    def __init__(self, channel_id: str, configuration: dict[str, Any]) -> None:
        super().__init__(channel_id, ProducerMode.NORMAL, configuration)
        self._timeline: list[_SegmentTiming] = []
        self._plan_start_station_seconds: float = 0.0
        self._position: float = 0.0
        self._current_index: int = 0
        self._output_url = configuration.get("output_url", "pipe:1")
        self._teardown_grace_seconds = float(configuration.get("teardown_grace_seconds", 0.5))
        self._current_segment_id: str | None = None
        self._segment_position: float = 0.0
        self._dropped_frames: int = 0
        self._queued_frames: int = 0

    # Lifecycle -----------------------------------------------------------------
    def start(self, playout_plan: list[dict[str, Any]] | Iterable[ContentSegment], start_at_station_time: datetime) -> bool:
        self._timeline = self._build_timeline(playout_plan)
        if not self._timeline:
            self.status = ProducerStatus.ERROR
            return False

        self.status = ProducerStatus.RUNNING
        self.output_url = self._output_url
        self.started_at = start_at_station_time
        self._plan_start_station_seconds = self._timeline[0].segment.start_time.timestamp()
        requested_seconds = start_at_station_time.timestamp()
        self._position = max(0.0, requested_seconds - self._plan_start_station_seconds)
        self._current_index = self._locate_segment_index(self._position)
        self._trim_completed_segments(self._position)
        self._update_segment_progress()
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self._timeline.clear()
        self._position = 0.0
        self._current_index = 0
        self.output_url = None
        self._current_segment_id = None
        self._segment_position = 0.0
        self._teardown_cleanup()
        return True

    # Playback ------------------------------------------------------------------
    def play_content(self, content: ContentSegment) -> bool:
        # This stub simply appends the segment to the timeline for testing purposes.
        last_end = self._timeline[-1].end_offset if self._timeline else 0.0
        duration = (content.end_time - content.start_time).total_seconds()
        timing = _SegmentTiming(segment=content, start_offset=last_end, end_offset=last_end + max(duration, 0.0))
        self._timeline.append(timing)
        if self.status == ProducerStatus.RUNNING and self._current_segment_id is None:
            self._update_segment_progress()
        return True

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        if self._advance_teardown(dt):
            return
        if self.status != ProducerStatus.RUNNING or not self._timeline:
            return
        if dt <= 0.0:
            return

        previous_position = self._position
        self._position += dt

        while self._current_index < len(self._timeline):
            timing = self._timeline[self._current_index]
            if timing.end_offset <= previous_position:
                self._current_index += 1
                continue
            if timing.end_offset <= self._position + 1e-6:
                edge_time = self._plan_start_station_seconds + timing.end_offset
                self._emit_segment_edge(
                    SegmentEdge(
                        segment=timing.segment,
                        kind="segment-end",
                        station_time=edge_time,
                    )
                )
                self._current_index += 1
                previous_position = timing.end_offset
            else:
                break
        self._update_segment_progress()

    def get_stream_endpoint(self) -> str | None:
        return self.output_url

    def health(self) -> str:
        if self.status == ProducerStatus.RUNNING:
            return "running"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        return f"ffmpeg_{self.channel_id}"

    def get_segment_progress(self) -> tuple[str | None, float]:
        return (self._current_segment_id, self._segment_position)

    def get_frame_counters(self) -> tuple[int | None, int | None]:
        return (self._dropped_frames, self._queued_frames)

    # Helpers -------------------------------------------------------------------
    def _build_timeline(self, playout_plan: Iterable[ContentSegment | dict[str, Any]]) -> list[_SegmentTiming]:
        segments: list[ContentSegment] = []
        for entry in playout_plan:
            if isinstance(entry, ContentSegment):
                segments.append(entry)
            elif isinstance(entry, dict):
                segment = entry.get("segment")
                if isinstance(segment, ContentSegment):
                    segments.append(segment)
        if not segments:
            return []

        timeline: list[_SegmentTiming] = []
        baseline = segments[0].start_time.timestamp()
        for seg in segments:
            start_offset = max(0.0, seg.start_time.timestamp() - baseline)
            end_offset = max(start_offset, seg.end_time.timestamp() - baseline)
            timeline.append(_SegmentTiming(segment=seg, start_offset=start_offset, end_offset=end_offset))
        return timeline

    def _locate_segment_index(self, position: float) -> int:
        for idx, timing in enumerate(self._timeline):
            if timing.end_offset > position:
                return idx
        return len(self._timeline)

    def _trim_completed_segments(self, position: float) -> None:
        idx = self._locate_segment_index(position)
        self._current_index = idx

    def _update_segment_progress(self) -> None:
        if self._current_index < len(self._timeline):
            timing = self._timeline[self._current_index]
            self._current_segment_id = timing.segment.asset_id
            self._segment_position = max(0.0, self._position - timing.start_offset)
        else:
            self._current_segment_id = None
            self._segment_position = 0.0

