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


class SchedulePlanValidationError(ScheduleValidationError):
    """Raised when a SchedulePlan fails validation."""

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        plan_name: str | None = None,
        violations: list[str] | None = None,
    ):
        """
        Initialize a SchedulePlan validation error.

        Args:
            message: Human-readable error message
            plan_id: UUID of the plan that failed validation
            plan_name: Name of the plan that failed validation
            violations: List of specific violation descriptions
        """
        super().__init__(message, violations)
        self.plan_id = plan_id
        self.plan_name = plan_name


class BlockAssignmentValidationError(ScheduleValidationError):
    """Raised when a Program fails validation."""

    def __init__(
        self,
        message: str,
        assignment_id: str | None = None,
        plan_id: str | None = None,
        violations: list[str] | None = None,
    ):
        """
        Initialize a block assignment validation error.

        Args:
            message: Human-readable error message
            assignment_id: UUID of the assignment that failed validation
            plan_id: UUID of the plan containing the assignment
            violations: List of specific violation descriptions
        """
        super().__init__(message, violations)
        self.assignment_id = assignment_id
        self.plan_id = plan_id


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

