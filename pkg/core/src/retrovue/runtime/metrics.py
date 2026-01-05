from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from retrovue.runtime.clock import MasterClock
from retrovue.runtime.pace import PaceController, PaceParticipant


@dataclass
class ChannelMetricsSample:
    """Latest emitted metrics snapshot for a channel."""

    station_time: float = 0.0
    channel_state: str = "idle"
    viewer_count: int = 0
    producer_state: str = "stopped"
    segment_id: str | None = None
    segment_position: float = 0.0
    dropped_frames: int | None = None
    queued_frames: int | None = None


class MetricsSource(Protocol):
    """Protocol implemented by channel managers for metrics publishing."""

    def populate_metrics_sample(self, sample: ChannelMetricsSample) -> None:
        """Populate the provided sample with channel state."""


class MetricsPublisher(PaceParticipant):
    """Publishes channel metrics at a fixed cadence using station time."""

    def __init__(
        self,
        clock: MasterClock,
        pace: PaceController,
        source: MetricsSource,
        *,
        sample_hz: float = 2.0,
        aggregation_window: float = 1.0,
    ) -> None:
        if sample_hz <= 0:
            raise ValueError("sample_hz must be greater than zero")
        if aggregation_window <= 0:
            raise ValueError("aggregation_window must be greater than zero")

        self._clock = clock
        self._pace = pace
        self._source = source
        self._interval = 1.0 / sample_hz
        self._aggregation_window = aggregation_window
        self._elapsed = 0.0
        self._sample = ChannelMetricsSample()
        self._last_publish_station = 0.0
        self._lock = Lock()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._pace.add_participant(self)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._pace.remove_participant(self)
        self._started = False

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._elapsed += dt
        if self._elapsed + 1e-6 < self._interval:
            return
        self._elapsed = 0.0
        station_time = self._clock.now()
        with self._lock:
            sample = self._sample
            sample.station_time = station_time
            self._source.populate_metrics_sample(sample)
            self._last_publish_station = station_time

    def get_latest_sample(self) -> ChannelMetricsSample:
        with self._lock:
            return self._sample

    def is_sample_fresh(self) -> bool:
        with self._lock:
            station_now = self._clock.now()
            return (station_now - self._last_publish_station) <= self._aggregation_window



