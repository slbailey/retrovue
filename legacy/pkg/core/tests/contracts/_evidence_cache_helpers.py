"""
Test-only helpers: deprecated evidence-server segment cache.

Relocated from ``retrovue.runtime.evidence_server`` in
PASS-OPT-02-PHASE-C3-C4-C5.  These functions are used exclusively by
``test_asrun_jip_segment_attribution.py`` to verify that the deprecated
DB segment cache contract still holds for historical attribution tests.

NO PRODUCTION CODE PATH CALLS THESE FUNCTIONS.
INV-AIR-SEGMENT-ID-001/003 superseded the runtime DB-lookup path.
"""
from __future__ import annotations

import threading
import types as _types

_block_segment_cache: dict = {}
_block_segment_cache_lock = threading.Lock()
_BLOCK_SEGMENT_CACHE_MAX = 10


def _lookup_segment_from_db(block_id: str, segment_index: int) -> object | None:
    """Look up segment metadata from the in-memory test cache.

    In the test context this only reads from the prepopulated cache
    (set via prepopulate_block_segment_cache).  No real DB access.
    """
    with _block_segment_cache_lock:
        segments = _block_segment_cache.get(block_id)

    if segments is None:
        return None

    seg_data = None
    for s in segments:
        if isinstance(s, dict) and s.get("segment_index") == segment_index:
            seg_data = s
            break

    if seg_data is None:
        return None

    return _types.SimpleNamespace(
        segment_index=seg_data.get("segment_index", segment_index),
        segment_type=seg_data.get("segment_type", "content"),
        asset_uri=seg_data.get("asset_uri", ""),
        asset_start_offset_ms=seg_data.get("asset_start_offset_ms", 0),
        segment_duration_ms=seg_data.get("segment_duration_ms", 0),
        title=seg_data.get("title", ""),
    )


def prepopulate_block_segment_cache(block_id: str, segments: list) -> None:
    """Pre-populate the test segment cache."""
    with _block_segment_cache_lock:
        if len(_block_segment_cache) >= _BLOCK_SEGMENT_CACHE_MAX:
            oldest = next(iter(_block_segment_cache))
            del _block_segment_cache[oldest]
        _block_segment_cache[block_id] = segments


def _clear_block_segment_cache(block_id: str) -> None:
    """Clear cached segments for a block (test cleanup)."""
    with _block_segment_cache_lock:
        _block_segment_cache.pop(block_id, None)
