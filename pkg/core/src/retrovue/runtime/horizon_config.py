"""Horizon authority mode configuration.

Controls whether horizon management is legacy (auto-resolve), shadow
(HorizonManager runs alongside legacy reads), or authoritative (consumers
are read-only; any consumer-triggered planning is a policy violation).

Environment variable: RETROVUE_HORIZON_AUTHORITY
Values: legacy | shadow | authoritative
Default: legacy

See: docs/contracts/ScheduleHorizonManagementContract_v0.1.md
     docs/domains/HorizonManager_v0.1.md
"""

from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger(__name__)


class HorizonAuthorityMode(Enum):
    """Horizon authority policy for the Core process.

    LEGACY:
        Current behavior. ScheduleManagerBackedScheduleService auto-resolves schedule
        days on first access (INV-P5-002). No HorizonManager involvement.

    SHADOW:
        HorizonManager runs and populates stores proactively, but
        consumers still use legacy auto-resolve reads. Useful for
        validating that horizon maintenance keeps up before cutting over.

    AUTHORITATIVE:
        HorizonManager is the sole planning trigger. Consumers perform
        reads only. Any consumer-triggered planning is a policy violation.
        If execution data is missing, it is reported as a planning failure.
    """

    LEGACY = "legacy"
    SHADOW = "shadow"
    AUTHORITATIVE = "authoritative"


class HorizonNoScheduleDataError(Exception):
    """Raised in authoritative horizon mode when required schedule or execution
    data is missing because the horizon was not extended far enough.
    This represents a planning failure and must not trigger auto-resolution.
    """


def get_horizon_authority_mode() -> HorizonAuthorityMode:
    """Read RETROVUE_HORIZON_AUTHORITY from environment.

    Returns HorizonAuthorityMode.LEGACY if unset or unrecognized.
    """
    raw = os.environ.get("RETROVUE_HORIZON_AUTHORITY", "legacy").strip().lower()
    try:
        mode = HorizonAuthorityMode(raw)
    except ValueError:
        logger.warning(
            "RETROVUE_HORIZON_AUTHORITY='%s' is not valid; "
            "expected legacy|shadow|authoritative. Falling back to legacy.",
            raw,
        )
        mode = HorizonAuthorityMode.LEGACY

    if mode != HorizonAuthorityMode.LEGACY:
        logger.info("Horizon authority mode: %s", mode.value)
    return mode
