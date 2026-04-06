"""HorizonManager — clock-driven ExecutionEntry window management.

Enforces:
    INV-EXECUTIONENTRY-LOOKAHEAD-001: window extends >= min_execution_hours ahead
    INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001: extension triggered by clock, not consumers
    INV-EXECUTIONENTRY-NO-GAPS-001: no temporal gaps in execution window

HorizonManager is the sole authority for extending the execution window.
Extension is triggered exclusively by clock progression (remaining depth
falls below min_execution_hours), never by consumer demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


class Clock(Protocol):
    """Minimal clock protocol for HorizonManager."""

    def now_utc_ms(self) -> int: ...


@dataclass
class LookaheadViolation:
    """Records a lookahead depth shortfall."""

    channel_id: str
    shortfall_ms: int
    min_required_ms: int
    actual_depth_ms: int
    fault_class: str = "runtime"


@dataclass
class ExtensionAttempt:
    """Records one extension attempt."""

    success: bool
    reason_code: str  # "clock_progression" — the only valid trigger
    extended_to_ms: int | None = None
    error_code: str | None = None


@dataclass
class HorizonHealthReport:
    """Snapshot of horizon health for a channel."""

    channel_id: str
    depth_ms: int
    min_required_ms: int
    execution_compliant: bool
    extension_attempt_count: int
    extension_success_count: int


@dataclass
class HorizonManager:
    """Manages the rolling ExecutionEntry window for a single channel.

    Clock-driven: evaluate_once() checks remaining depth against
    min_execution_hours and extends if needed. No consumer request
    triggers extension.
    """

    channel_id: str
    clock: Clock
    min_execution_hours: int
    extend_fn: Callable[[str, int], int]  # (channel_id, extend_from_ms) -> new_end_ms
    execution_window_end_ms: int = 0
    extension_attempt_log: list[ExtensionAttempt] = field(default_factory=list)
    extension_forbidden_trigger_count: int = 0

    @property
    def min_execution_ms(self) -> int:
        return self.min_execution_hours * 3_600_000

    def remaining_depth_ms(self) -> int:
        """Remaining execution depth from current clock time."""
        now = self.clock.now_utc_ms()
        return max(0, self.execution_window_end_ms - now)

    def evaluate_once(self) -> HorizonHealthReport:
        """Evaluate lookahead depth and extend if needed.

        This is the sole extension trigger. Called on clock tick,
        not on consumer demand.

        Returns a health report.
        """
        remaining = self.remaining_depth_ms()

        if remaining < self.min_execution_ms:
            self._extend_execution()

        remaining = self.remaining_depth_ms()
        success_count = sum(1 for a in self.extension_attempt_log if a.success)

        return HorizonHealthReport(
            channel_id=self.channel_id,
            depth_ms=remaining,
            min_required_ms=self.min_execution_ms,
            execution_compliant=remaining >= self.min_execution_ms,
            extension_attempt_count=len(self.extension_attempt_log),
            extension_success_count=success_count,
        )

    def _extend_execution(self) -> None:
        """Extend the execution window until depth >= min_execution_ms.

        Loops calling extend_fn until the window is sufficient.
        Records each attempt.
        """
        now = self.clock.now_utc_ms()
        target_end = now + self.min_execution_ms

        while self.execution_window_end_ms < target_end:
            try:
                new_end = self.extend_fn(
                    self.channel_id, self.execution_window_end_ms
                )
                self.extension_attempt_log.append(
                    ExtensionAttempt(
                        success=True,
                        reason_code="clock_progression",
                        extended_to_ms=new_end,
                    )
                )
                if new_end <= self.execution_window_end_ms:
                    # No progress — avoid infinite loop
                    break
                self.execution_window_end_ms = new_end
            except Exception as exc:
                self.extension_attempt_log.append(
                    ExtensionAttempt(
                        success=False,
                        reason_code="clock_progression",
                        error_code=str(exc),
                    )
                )
                break

    def record_consumer_demand_attempt(self) -> None:
        """Record that a consumer tried to trigger extension (violation).

        This should never be called in correct operation. If it is,
        it increments the forbidden trigger count for observability.
        """
        self.extension_forbidden_trigger_count += 1

    def health_report(self) -> HorizonHealthReport:
        """Return current health without evaluating/extending."""
        remaining = self.remaining_depth_ms()
        success_count = sum(1 for a in self.extension_attempt_log if a.success)
        return HorizonHealthReport(
            channel_id=self.channel_id,
            depth_ms=remaining,
            min_required_ms=self.min_execution_ms,
            execution_compliant=remaining >= self.min_execution_ms,
            extension_attempt_count=len(self.extension_attempt_log),
            extension_success_count=success_count,
        )
