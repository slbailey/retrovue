"""
Runtime constants for prefeed and startup timing.

P11E-001: MIN_PREFEED_LEAD_TIME is the minimum time between LoadPreview and the
target boundary. AIR needs this time to receive the request, seek, decode initial
frames, and buffer. See INV-CONTROL-NO-POLL-001.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

# Minimum time between LoadPreview and target boundary (ms).
# Must be sufficient for AIR to: receive request, seek, decode, buffer, signal readiness.
# Default: 5000ms. Override via RETROVUE_MIN_PREFEED_LEAD_TIME_MS.
DEFAULT_MIN_PREFEED_LEAD_TIME_MS = 5000

_MIN_MS_RAW = os.environ.get("RETROVUE_MIN_PREFEED_LEAD_TIME_MS", str(DEFAULT_MIN_PREFEED_LEAD_TIME_MS))
try:
    MIN_PREFEED_LEAD_TIME_MS = int(_MIN_MS_RAW)
except ValueError:
    MIN_PREFEED_LEAD_TIME_MS = DEFAULT_MIN_PREFEED_LEAD_TIME_MS

if MIN_PREFEED_LEAD_TIME_MS < 1000:
    raise ValueError(
        f"MIN_PREFEED_LEAD_TIME_MS ({MIN_PREFEED_LEAD_TIME_MS}) is dangerously low. "
        "Minimum recommended value is 1000ms."
    )
if MIN_PREFEED_LEAD_TIME_MS > 30000:
    logging.getLogger(__name__).warning(
        "MIN_PREFEED_LEAD_TIME_MS (%s) is unusually high. This may cause unnecessary schedule lookahead.",
        MIN_PREFEED_LEAD_TIME_MS,
    )

MIN_PREFEED_LEAD_TIME = timedelta(milliseconds=MIN_PREFEED_LEAD_TIME_MS)

# P11D-010: Bounded upper limit on channel launch overhead (AIR spawn, gRPC, handshake).
# First boundary MUST satisfy boundary_time >= station_utc + STARTUP_LATENCY + MIN_PREFEED_LEAD_TIME.
STARTUP_LATENCY = timedelta(seconds=7)

# P11E-002: Buffer for scheduling jitter when triggering LoadPreview (trigger = boundary - MIN - buffer).
SCHEDULING_BUFFER_SECONDS = 2.0


def log_prefeed_constants() -> None:
    """Log configured prefeed constants at startup (P11E-001 done criteria)."""
    log = logging.getLogger(__name__)
    log.info(
        "INV-CONTROL-NO-POLL-001: MIN_PREFEED_LEAD_TIME_MS=%d (%.1fs), STARTUP_LATENCY=%s",
        MIN_PREFEED_LEAD_TIME_MS,
        MIN_PREFEED_LEAD_TIME.total_seconds(),
        STARTUP_LATENCY,
    )


# Log once when module is first loaded (process startup).
log_prefeed_constants()
