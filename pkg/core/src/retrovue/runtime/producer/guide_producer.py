from datetime import datetime
from typing import Any

from .base import ContentSegment, Producer, ProducerMode, ProducerStatus


class GuideProducer(Producer):
    """
    Guide mode producer for programming guide display.

    Stub implementation honouring pacing/teardown contracts.
    """

    def __init__(self, channel_id: str, configuration: dict[str, Any]):
        super().__init__(channel_id, ProducerMode.GUIDE, configuration)
        self._endpoint = configuration.get("output_url", f"guide://{channel_id}")

    def start(self, playout_plan: list[dict[str, Any]], start_at_station_time: datetime) -> bool:
        self.status = ProducerStatus.RUNNING
        self.started_at = start_at_station_time
        self.output_url = self._endpoint
        return True

    def stop(self) -> bool:
        self.status = ProducerStatus.STOPPED
        self.output_url = None
        self._teardown_cleanup()
        return True

    def play_content(self, content: ContentSegment) -> bool:
        return True

    def get_stream_endpoint(self) -> str | None:
        return self.output_url

    def health(self) -> str:
        if self.status == ProducerStatus.RUNNING:
            return "running"
        if self.status == ProducerStatus.ERROR:
            return "degraded"
        return "stopped"

    def get_producer_id(self) -> str:
        return f"guide_{self.channel_id}"

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        self._advance_teardown(dt)

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """Advance guide producer state using pacing ticks."""
        # TODO: Implement tick-driven loop for guide mode
        pass