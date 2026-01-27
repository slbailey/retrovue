"""
Phase 5 — Segment orchestrator: CM timing and prefeed contract.

Orchestrator watches time, issues LoadPreview by prefeed deadline, SwitchToLive at boundary.
Does not mutate segments; does not issue duplicate LoadPreview for the same next segment.
Designed for testing with stepped clock and gRPC mock. No real media or ffmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from retrovue.runtime.playout_pipeline import PlayoutSegment


class PlayoutSink(Protocol):
    """Sink for LoadPreview and SwitchToLive (gRPC mock or real client)."""

    def load_preview(self, segment: PlayoutSegment, channel_id: str) -> None:
        """Issue LoadPreview for the given segment."""
        ...

    def switch_to_live(self, channel_id: str) -> None:
        """Issue SwitchToLive at the boundary."""
        ...


@dataclass
class RecordingSink:
    """Records LoadPreview and SwitchToLive calls for Phase 5 tests."""

    load_preview_calls: list[tuple[PlayoutSegment, str]] = field(default_factory=list)
    switch_to_live_calls: list[str] = field(default_factory=list)

    def load_preview(self, segment: PlayoutSegment, channel_id: str) -> None:
        self.load_preview_calls.append((segment, channel_id))

    def switch_to_live(self, channel_id: str) -> None:
        self.switch_to_live_calls.append(channel_id)


@dataclass
class SegmentOrchestrator:
    """
    Phase 5: Issues LoadPreview by hard_stop_time_ms - prefeed_window_ms,
    SwitchToLive at boundary. Idempotent prefeed per segment; segments immutable.
    """

    get_now_epoch_ms: Callable[[], int]
    prefeed_window_ms: int
    sink: PlayoutSink
    channel_id: str
    get_next_segment: Callable[[int | None], PlayoutSegment | None]
    """Given previous boundary epoch ms (or None for first segment), returns segment to prefeed."""

    _current: PlayoutSegment | None = field(default=None)
    _next: PlayoutSegment | None = field(default=None)
    _prefed_hard_stop_ms: int | None = field(default=None)  # avoid duplicate LoadPreview

    def tick(self) -> None:
        """
        One evaluation step. Call repeatedly (periodic tick, event loop, or test).
        CM may re-evaluate multiple times; we only send LoadPreview once per next segment.
        """
        now_ms = self.get_now_epoch_ms()

        # At boundary: switch to next (which must have been prefed)
        if self._current is not None and now_ms >= self._current.hard_stop_time_ms:
            self.sink.switch_to_live(self.channel_id)
            self._current = self._next
            self._next = None
            self._prefed_hard_stop_ms = None
            return

        # Bootstrap: no current segment yet — prefeed and switch to first
        if self._current is None:
            seg = self.get_next_segment(None)
            if seg is None:
                return
            self.sink.load_preview(seg, self.channel_id)
            self.sink.switch_to_live(self.channel_id)
            self._current = seg
            self._prefed_hard_stop_ms = seg.hard_stop_time_ms
            return

        # Prefeed next segment by deadline (no later than hard_stop - prefeed_window)
        deadline_ms = self._current.hard_stop_time_ms - self.prefeed_window_ms
        if now_ms >= deadline_ms and self._next is None:
            next_seg = self.get_next_segment(self._current.hard_stop_time_ms)
            if next_seg is not None:
                self._next = next_seg
                self.sink.load_preview(next_seg, self.channel_id)
                self._prefed_hard_stop_ms = next_seg.hard_stop_time_ms
            return

        # Idempotent: already have next prefed; do not send duplicate LoadPreview for same segment
        if self._next is not None and now_ms >= deadline_ms:
            # Re-evaluation before boundary: we already prefed _next; do nothing
            return
