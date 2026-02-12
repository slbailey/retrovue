"""Horizon authority configuration.

Horizon is authoritative: HorizonManager is the sole planning trigger.
Consumers perform reads only. Any consumer-triggered planning is a policy
violation. Missing data is reported as a planning failure.

See: docs/contracts/ScheduleHorizonManagementContract_v0.1.md
     docs/domains/HorizonManager_v0.1.md
"""

from __future__ import annotations


class HorizonNoScheduleDataError(Exception):
    """Raised when required schedule or execution data is missing because
    the horizon was not extended far enough.

    This represents a planning failure and must not trigger auto-resolution.
    """
