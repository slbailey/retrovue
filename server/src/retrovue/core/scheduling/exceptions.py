"""
Scheduling validation exceptions.

This module defines custom exceptions for scheduling validation errors.
These exceptions are raised when validation contracts detect violations.
"""


class ScheduleValidationError(Exception):
    """Base exception for all scheduling validation errors."""

    def __init__(self, message: str, violations: list[str] | None = None):
        """
        Initialize a scheduling validation error.

        Args:
            message: Human-readable error message
            violations: List of specific violation descriptions
        """
        super().__init__(message)
        self.message = message
        self.violations = violations or []

    def __str__(self) -> str:
        """Return formatted error message with violations."""
        if self.violations:
            violations_text = "\n  - ".join(self.violations)
            return f"{self.message}\nViolations:\n  - {violations_text}"
        return self.message


class ScheduleDayValidationError(ScheduleValidationError):
    """Raised when a BroadcastScheduleDay fails validation."""

    def __init__(
        self,
        message: str,
        schedule_day_id: str | None = None,
        channel_id: str | None = None,
        schedule_date: str | None = None,
        violations: list[str] | None = None,
    ):
        """
        Initialize a schedule day validation error.

        Args:
            message: Human-readable error message
            schedule_day_id: UUID of the schedule day that failed validation
            channel_id: UUID of the channel
            schedule_date: Date string (YYYY-MM-DD) of the schedule day
            violations: List of specific violation descriptions
        """
        super().__init__(message, violations)
        self.schedule_day_id = schedule_day_id
        self.channel_id = channel_id
        self.schedule_date = schedule_date


class PlaylogEventValidationError(ScheduleValidationError):
    """Raised when a BroadcastPlaylogEvent fails validation."""

    def __init__(
        self,
        message: str,
        event_id: str | None = None,
        channel_id: str | None = None,
        violations: list[str] | None = None,
    ):
        """
        Initialize a playlog event validation error.

        Args:
            message: Human-readable error message
            event_id: UUID of the playlog event that failed validation
            channel_id: UUID of the channel
            violations: List of specific violation descriptions
        """
        super().__init__(message, violations)
        self.event_id = event_id
        self.channel_id = channel_id

