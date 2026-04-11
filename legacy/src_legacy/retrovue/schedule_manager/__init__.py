"""
Schedule Manager Module

This module provides the scheduling and programming system for RetroVue.
It manages EPG horizons, playlog events, and enforces content rules.

Key Components:
- ScheduleService: Authority for schedule state and horizons
- ScheduleOrchestrator: Orchestrator that rolls horizons forward
- Rules: Content rules and policy definitions
"""

from .rules import BlockPolicy, BlockRule, RotationRule
from .schedule_orchestrator import ScheduleOrchestrator
from .schedule_service import ScheduleService

__all__ = [
    "ScheduleService",
    "ScheduleOrchestrator",
    "BlockRule",
    "BlockPolicy",
    "RotationRule",
]
