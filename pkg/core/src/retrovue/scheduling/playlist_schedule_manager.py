"""Hard-coded PlaylistScheduleManager (Phase 4 burn-in).

Sole producer of Playlists consumed by ChannelManager.
Satisfies PlaylistScheduleManagerContract.md (Accepted, frozen 2026-02-07).

Produces a deterministic repeating schedule of three Cheers episodes with
filler padding to half-hour blocks, at 30fps playout.  No system clock
access, no runtime probing, no randomness, no mutable global state.

Media constants derived from ffprobe (measured offline, inlined here):
    S01E01  24000/1001fps  nb_frames=36003  -> 45049 playout frames at 30fps
    S01E02  24000/1001fps  nb_frames=31971  -> 40004 playout frames at 30fps
    S01E03  24000/1001fps  nb_frames=35961  -> 44996 playout frames at 30fps
    filler  30000/1001fps  nb_frames=109404 -> 109513 playout frames at 30fps

Playout frame counts computed as:
    source_duration = nb_frames * 1001 / source_fps_num   (exact via Fraction)
    playout_frames  = round_half_up(source_duration * 30)

Each episode + filler pair sums to 54000 frames (exactly 1800.0s at 30fps).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

from retrovue.runtime.channel_manager import Playlist, PlaylistSegment

# ---------------------------------------------------------------------------
# Constants (internal — not exposed across the Playlist boundary)
# ---------------------------------------------------------------------------

_FPS: int = 30
_BLOCK_FRAMES: int = _FPS * 1800  # 54000 frames = 30 minutes exactly

_CHANNEL_TIMEZONE: str = "America/New_York"

# ---------------------------------------------------------------------------
# Media constants (measured via ffprobe, converted to 30fps playout)
#
# Derivation for episodes (source 24000/1001 fps):
#   source_dur = nb_frames * 1001 / 24000
#   playout_fc = round_half_up(source_dur * 30)
#
# Derivation for filler (source 30000/1001 fps):
#   source_dur = nb_frames * 1001 / 30000
#   playout_fc = round_half_up(source_dur * 30)
# ---------------------------------------------------------------------------

# S01E01: nb_frames=36003, dur=1501.625125s, playout_fc=45049
_EP1_ASSET_ID: str = "asset-cheers-s01e01"
_EP1_ASSET_PATH: str = (
    "/opt/retrovue/assets/"
    "Cheers (1982) - S01E01 - Give Me a Ring Sometime "
    "[Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
)
_EP1_FRAME_COUNT: int = 45049

# S01E02: nb_frames=31971, dur=1333.457125s, playout_fc=40004
_EP2_ASSET_ID: str = "asset-cheers-s01e02"
_EP2_ASSET_PATH: str = (
    "/opt/retrovue/assets/"
    "Cheers (1982) - S01E02 - Sams Women "
    "[AMZN WEBDL-720p][AAC 2.0][x264]-Trollhd.mp4"
)
_EP2_FRAME_COUNT: int = 40004

# S01E03: nb_frames=35961, dur=1499.873375s, playout_fc=44996
_EP3_ASSET_ID: str = "asset-cheers-s01e03"
_EP3_ASSET_PATH: str = (
    "/opt/retrovue/assets/"
    "Cheers (1982) - S01E03 - The Tortelli Tort "
    "[Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
)
_EP3_FRAME_COUNT: int = 44996

# Filler: nb_frames=109404, dur=3650.4468s, playout_fc=109513
_FILLER_ASSET_ID: str = "asset-filler"
_FILLER_ASSET_PATH: str = "/opt/retrovue/assets/filler.mp4"
_FILLER_FULL_FRAME_COUNT: int = 109513

# ---------------------------------------------------------------------------
# Repeating pattern: [EP, FILLER] x 3 episodes.
# Each (PROGRAM + INTERSTITIAL) pair sums to _BLOCK_FRAMES (54000).
# Filler frame counts: _BLOCK_FRAMES - episode frame count.
# ---------------------------------------------------------------------------

_PATTERN: Sequence[tuple[str, int, str, str]] = (
    # Block 1: S01E01 (45049) + filler (8951) = 54000
    ("PROGRAM",      _EP1_FRAME_COUNT,                    _EP1_ASSET_ID,    _EP1_ASSET_PATH),
    ("INTERSTITIAL", _BLOCK_FRAMES - _EP1_FRAME_COUNT,    _FILLER_ASSET_ID, _FILLER_ASSET_PATH),
    # Block 2: S01E02 (40004) + filler (13996) = 54000
    ("PROGRAM",      _EP2_FRAME_COUNT,                    _EP2_ASSET_ID,    _EP2_ASSET_PATH),
    ("INTERSTITIAL", _BLOCK_FRAMES - _EP2_FRAME_COUNT,    _FILLER_ASSET_ID, _FILLER_ASSET_PATH),
    # Block 3: S01E03 (44996) + filler (9004) = 54000
    ("PROGRAM",      _EP3_FRAME_COUNT,                    _EP3_ASSET_ID,    _EP3_ASSET_PATH),
    ("INTERSTITIAL", _BLOCK_FRAMES - _EP3_FRAME_COUNT,    _FILLER_ASSET_ID, _FILLER_ASSET_PATH),
)


def _round_half_up(x: float) -> int:
    """ROUND_HALF_UP: floor(x + 0.5) for non-negative x."""
    return int(math.floor(x + 0.5))


class PlaylistScheduleManager:
    """Hard-coded, deterministic PlaylistScheduleManager for Phase 4 burn-in.

    Produces Playlists from a repeating 3-episode rotation with filler padding
    to half-hour blocks, at 30fps.  Returns a single Playlist covering the
    entire requested window.
    """

    def get_playlists(
        self,
        channel_id: str,
        window_start_at: datetime,
        window_end_at: datetime,
    ) -> list[Playlist]:
        """Return Playlists that tile [window_start_at, window_end_at).

        Raises:
            ValueError: If window_start_at >= window_end_at.
            ValueError: If either datetime is naive (no tzinfo).
        """
        if window_start_at.tzinfo is None or window_end_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if window_start_at >= window_end_at:
            raise ValueError("window_start_at must be before window_end_at")

        pattern_len = len(_PATTERN)
        segments: list[PlaylistSegment] = []
        cursor = window_start_at
        idx = 0

        while cursor < window_end_at:
            seg_type, full_frames, asset_id, asset_path = _PATTERN[idx % pattern_len]

            # Clamp the last segment so it does not overshoot the window.
            remaining_seconds = (window_end_at - cursor).total_seconds()
            remaining_frames = _round_half_up(remaining_seconds * _FPS)
            if remaining_frames <= 0:
                break
            frame_count = min(full_frames, remaining_frames)

            duration_seconds = frame_count / _FPS

            seg_id = "seg-{}-{:04d}".format(
                cursor.strftime("%Y%m%d-%H%M"),
                idx,
            )

            segments.append(
                PlaylistSegment(
                    segment_id=seg_id,
                    start_at=cursor,
                    duration_seconds=duration_seconds,
                    type=seg_type,
                    asset_id=asset_id,
                    asset_path=asset_path,
                    frame_count=frame_count,
                )
            )

            cursor = cursor + timedelta(seconds=duration_seconds)
            idx += 1

        return [
            Playlist(
                channel_id=channel_id,
                channel_timezone=_CHANNEL_TIMEZONE,
                window_start_at=window_start_at,
                window_end_at=window_end_at,
                generated_at=window_start_at,
                source="HARD_CODED",
                segments=tuple(segments),
            )
        ]
