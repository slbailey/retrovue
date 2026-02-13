"""
As-Run artifact types for reconciliation.

No persistence or DB dependencies. Used by AsRunReconciliationContract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AsRunSegment:
    """One segment in an as-run block."""
    segment_type: str
    asset_uri: str | None
    asset_start_offset_ms: int | None
    segment_duration_ms: int
    runtime_recovery: bool = False
    runway_degradation: bool = False


@dataclass
class AsRunBlock:
    """One block in an as-run log."""
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    segments: list[AsRunSegment]


@dataclass
class AsRunLog:
    """As-run log for a channel and broadcast date."""
    channel_id: str
    broadcast_date: date
    blocks: list[AsRunBlock]
