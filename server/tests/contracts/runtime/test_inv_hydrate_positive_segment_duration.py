"""
Compiled segment hydration must never emit segment_duration_ms <= 0 to playout.

AIR BlockPlanValidator fails with "segment N has non-positive duration: 0", which
prevents decoder startup and can wedge the preview→live fence (INV-PREROLL-READY-001).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrovue.runtime.schedule_items_reader import _hydrate_compiled_segments


class _StubResolver:
    def lookup(self, asset_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            file_uri=f"file:///media/{asset_id}.mp4",
            loudness_gain_db=0.0,
        )


@pytest.mark.contract
def test_hydrate_skips_zero_duration_segments_keeps_slot_sum():
    """Intro (or any act) with duration_ms=0 is omitted; slot still fills from rest."""
    slot_ms = 1_800_000
    block = _hydrate_compiled_segments(
        compiled_segments=[
            {"segment_type": "intro", "asset_id": "intro-a", "duration_ms": 0},
            {
                "segment_type": "content",
                "asset_id": "main-a",
                "duration_ms": slot_ms,
            },
        ],
        asset_id="raw-slot",
        start_utc_ms=1_700_000_000_000,
        slot_duration_ms=slot_ms,
        resolver=_StubResolver(),
    )
    assert len(block.segments) == 1
    assert block.segments[0].segment_type == "content"
    assert block.segments[0].segment_duration_ms == slot_ms


@pytest.mark.contract
def test_hydrate_all_nonpositive_yields_filler_only():
    """If every compiled act is <=0, one filler segment covers the full slot."""
    slot_ms = 60_000
    block = _hydrate_compiled_segments(
        compiled_segments=[
            {"segment_type": "intro", "asset_id": "x", "duration_ms": 0},
            {"segment_type": "outro", "asset_id": "y", "duration_ms": -1},
        ],
        asset_id="raw-slot",
        start_utc_ms=1_700_000_000_000,
        slot_duration_ms=slot_ms,
        resolver=_StubResolver(),
    )
    assert len(block.segments) == 1
    assert block.segments[0].segment_type == "filler"
    assert block.segments[0].segment_duration_ms == slot_ms
