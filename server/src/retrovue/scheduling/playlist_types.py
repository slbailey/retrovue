"""Playlist contract types (PlaylistArchitecture.md).

These types are the data contract between PlaylistScheduleManager (producer)
and ChannelManager (consumer). They live in retrovue.scheduling because they
are scheduling domain types, not runtime implementation types.

Moved from retrovue.runtime.channel_manager in refactor/simplify-single-authority-l3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class PlaylistSegment:
    """A single executable entry in a Playlist.

    Fields match PlaylistArchitecture.md § Segment Fields.
    All timestamps are timezone-aware datetimes.

    Frame-authoritative execution:
        ``frame_count`` is the total number of frames in this segment when
        played from offset 0.  It is the authoritative execution quantity —
        all CT-domain exhaustion math, preload timing, and switch-before-
        exhaustion decisions derive from it.  ``duration_seconds`` is
        retained for metadata, logging, and positional time-lookup only.
    """

    segment_id: str
    start_at: datetime
    duration_seconds: int
    type: str
    asset_id: str
    asset_path: str
    frame_count: int


@dataclass(frozen=True)
class Playlist:
    """Time-bounded, ordered list of executable segments for a channel.

    Fields match PlaylistArchitecture.md § Playlist Fields.
    All timestamps are timezone-aware datetimes.
    """

    channel_id: str
    channel_timezone: str
    window_start_at: datetime
    window_end_at: datetime
    generated_at: datetime
    source: str
    segments: Sequence[PlaylistSegment] = field(default_factory=tuple)
