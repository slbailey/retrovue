"""HLS delivery subsystem for RetroVue Core.

Components:
    LiveSegment       — immutable completed segment
    SegmentRing       — bounded in-memory segment window
    ManifestGenerator — pure HLS playlist generation
    HlsSegmenter     — TS→segment producer
    HlsSessionManager — HLS viewer presence tracking
"""

from .segment_ring import LiveSegment, SegmentRing
from .manifest_generator import ManifestGenerator
from .segmenter import HlsSegmenter
from .session_manager import HlsSessionManager

__all__ = [
    "LiveSegment",
    "SegmentRing",
    "ManifestGenerator",
    "HlsSegmenter",
    "HlsSessionManager",
]
