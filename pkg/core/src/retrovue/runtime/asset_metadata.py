"""
Phase 2.5 — Asset metadata: authoritative, measured facts (duration, path).

No runtime file I/O. Duration is probed once (e.g. ffprobe); results are
injected as constants or fixtures. Scheduling and playout consume Asset
metadata; they do not open files or recompute duration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    """
    Authoritative asset facts. Immutable.
    duration_ms is measured once (e.g. ffprobe), rounded down to integer ms.
    """

    asset_id: str
    asset_path: str
    duration_ms: int

    def __post_init__(self) -> None:
        if self.duration_ms <= 0:
            raise ValueError("duration_ms must be positive")


# Mock channel assets (frozen). Durations from contract example; replace with
# ffprobe output when binding to real files.
SAMPLECONTENT = Asset(
    asset_id="samplecontent",
    asset_path="assets/samplecontent.mp4",
    duration_ms=1_499_904,
)
FILLER = Asset(
    asset_id="filler",
    asset_path="assets/filler.mp4",
    duration_ms=3_650_455,
)
