"""
Scheduling domain contracts and validation.

This module provides validation contracts for the scheduling domain:
- SchedulePlanInvariantsContract
- ProgramContract
- ScheduleDayContract
- PlaylogEventContract
"""

from .contracts import (
    validate_block_assignment,
    validate_playlog_event,
    validate_schedule_day,
    validate_schedule_plan,
)
from .exceptions import (
    BlockAssignmentValidationError,
    PlaylogEventValidationError,
    ScheduleDayValidationError,
    SchedulePlanValidationError,
    ScheduleValidationError,
)

__all__ = [
    # Validation functions
    "validate_schedule_plan",
    "validate_block_assignment",
    "validate_schedule_day",
    "validate_playlog_event",
    # Exceptions
    "ScheduleValidationError",
    "SchedulePlanValidationError",
    "BlockAssignmentValidationError",
    "ScheduleDayValidationError",
    "PlaylogEventValidationError",
]

