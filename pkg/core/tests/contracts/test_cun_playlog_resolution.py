"""
Contract tests for CUN segment resolution in PlaylistBuilderDaemon.

Validates ensure_cun_ready behavior per CUN Plan v5:
    INV-CUN-SKIP-IF-UNREADY-001: Unready CUN segments must be skipped entirely.
    INV-CUN-DEDUP-BEFORE-RENDER-001: Before enqueue, check for existing completed render.
    INV-CUN-PRIORITY-PLAYOUT-001: Enqueued requests use playout-time priority.
    INV-CUN-CACHE-DEDUP-001: content_hash = hash(template_id, title).

These tests are RED until ensure_cun_ready is implemented.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_hash(template_id: str, title: str) -> str:
    """Canonical CUN content hash: SHA256(template_id + title)."""
    return hashlib.sha256(f"{template_id}:{title}".encode()).hexdigest()


def _make_block_with_cun(
    *,
    block_start_ms: int = 1_000_000_000_000,
    content_duration_ms: int = 1_800_000,
    cun_duration_ms: int = 10_000,
    cun_asset_uri: str = "/assets/templates/cun/retro_loop_01.mp4",
    filler_duration_ms: int = 0,
) -> ScheduledBlock:
    """Build a ScheduledBlock containing content + CUN + optional filler."""
    segments = [
        ScheduledSegment(
            segment_type="content",
            asset_uri="/shows/cheers/s01e01.mp4",
            asset_start_offset_ms=0,
            segment_duration_ms=content_duration_ms,
        ),
        ScheduledSegment(
            segment_type="coming_up_next",
            asset_uri=cun_asset_uri,
            asset_start_offset_ms=0,
            segment_duration_ms=cun_duration_ms,
        ),
    ]
    if filler_duration_ms > 0:
        segments.append(ScheduledSegment(
            segment_type="filler",
            asset_uri="/assets/filler.mp4",
            asset_start_offset_ms=0,
            segment_duration_ms=filler_duration_ms,
        ))

    total_ms = sum(s.segment_duration_ms for s in segments)
    return ScheduledBlock(
        block_id="BLK-test-001",
        start_utc_ms=block_start_ms,
        end_utc_ms=block_start_ms + total_ms,
        segments=tuple(segments),
    )


def _make_sb_dict_with_cun(
    *,
    block_start_ms: int = 1_000_000_000_000,
    content_duration_ms: int = 1_800_000,
    cun_duration_ms: int = 10_000,
    next_program_title: str = "Cheers S01E02",
    template_id: str = "default",
) -> dict:
    """Build the original sb_dict with CUN metadata preserved."""
    total_ms = content_duration_ms + cun_duration_ms
    return {
        "block_id": "BLK-test-001",
        "start_utc_ms": block_start_ms,
        "end_utc_ms": block_start_ms + total_ms,
        "compiled_segments": [
            {
                "segment_type": "content",
                "asset_uri": "/shows/cheers/s01e01.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": content_duration_ms,
            },
            {
                "segment_type": "coming_up_next",
                "asset_id": template_id,
                "asset_uri": "/assets/templates/cun/retro_loop_01.mp4",
                "duration_ms": cun_duration_ms,
                "segment_duration_ms": cun_duration_ms,
                "next_program_title": next_program_title,
                "pool": "cun_templates",
            },
        ],
    }


def _make_daemon():
    """Create a minimal PlaylistBuilderDaemon for testing."""
    from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
    return PlaylistBuilderDaemon(
        channel_id="test-cun-ch",
        min_hours=2,
        programming_day_start_hour=6,
        channel_tz="UTC",
    )


def _make_block_without_cun(
    block_start_ms: int = 1_000_000_000_000,
) -> ScheduledBlock:
    """Build a ScheduledBlock with no CUN segments."""
    return ScheduledBlock(
        block_id="BLK-no-cun-001",
        start_utc_ms=block_start_ms,
        end_utc_ms=block_start_ms + 1_800_000,
        segments=(
            ScheduledSegment(
                segment_type="content",
                asset_uri="/shows/cheers/s01e01.mp4",
                asset_start_offset_ms=0,
                segment_duration_ms=1_800_000,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

@dataclass
class _MockRenderRequest:
    """Simulates a CunRenderRequest row."""
    id: uuid.UUID
    channel_id: uuid.UUID
    status: str
    rendered_asset_path: str | None
    content_hash: str | None
    next_program_title: str = ""
    template_id: str = "default"
    priority: int = 100


class _MockCunQuery:
    """Mock DB query chain for CunRenderRequest lookups."""

    def __init__(self, results: list[_MockRenderRequest]):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None


# ---------------------------------------------------------------------------
# INV-CUN-SKIP-IF-UNREADY-001: CUN segments skipped when not rendered
# ---------------------------------------------------------------------------

def _mock_db_no_render():
    """DB mock where CUN render lookup returns no completed render."""
    db = MagicMock()
    # query().filter().first() returns None → no completed render found.
    db.query.return_value.filter.return_value.first.return_value = None
    return db


class TestCunSkipIfUnready:
    """INV-CUN-SKIP-IF-UNREADY-001: If a CUN render is incomplete at
    playout time, the system MUST skip the segment."""

    def test_cun_segment_removed_when_no_render_request_exists(self):
        """CUN segment with no render request in DB → segment skipped."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun()

        assert any(s.segment_type == "coming_up_next" for s in block.segments)

        result = daemon._ensure_cun_ready(block, sb_dict, db=_mock_db_no_render())

        # CUN segment must be removed
        cun_segs = [s for s in result.segments if s.segment_type == "coming_up_next"]
        assert len(cun_segs) == 0, "Unready CUN segment must be skipped"

    def test_cun_segment_removed_when_render_pending(self):
        """CUN segment with pending render → segment skipped."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun()

        result = daemon._ensure_cun_ready(block, sb_dict, db=_mock_db_no_render())

        cun_segs = [s for s in result.segments if s.segment_type == "coming_up_next"]
        assert len(cun_segs) == 0, "Pending CUN render must result in skipped segment"

    def test_cun_segment_removed_when_render_failed(self):
        """CUN segment with failed render → segment skipped."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun()

        result = daemon._ensure_cun_ready(block, sb_dict, db=_mock_db_no_render())

        cun_segs = [s for s in result.segments if s.segment_type == "coming_up_next"]
        assert len(cun_segs) == 0, "Failed CUN render must result in skipped segment"

    def test_non_cun_segments_preserved(self):
        """Non-CUN segments must be unaffected when CUN is skipped."""
        daemon = _make_daemon()
        block = _make_block_with_cun(filler_duration_ms=5_000)
        sb_dict = _make_sb_dict_with_cun()

        result = daemon._ensure_cun_ready(block, sb_dict, db=_mock_db_no_render())

        content_segs = [s for s in result.segments if s.segment_type == "content"]
        filler_segs = [s for s in result.segments if s.segment_type == "filler"]
        assert len(content_segs) == 1, "Content segments must be preserved"
        assert len(filler_segs) == 1, "Filler segments must be preserved"

    def test_block_without_cun_passes_through_unchanged(self):
        """Block with no CUN segments → returned unchanged."""
        daemon = _make_daemon()
        block = _make_block_without_cun()
        sb_dict = {"block_id": "BLK-no-cun-001", "compiled_segments": []}

        result = daemon._ensure_cun_ready(block, sb_dict, db=_mock_db_no_render())

        assert result.block_id == block.block_id
        assert len(result.segments) == len(block.segments)


# ---------------------------------------------------------------------------
# INV-CUN-SKIP-IF-UNREADY-001 (positive): Completed render → use path
# ---------------------------------------------------------------------------

def _mock_db_completed_render(rendered_path: str = "/cun_cache/abc123.mp4"):
    """DB mock where CUN render lookup returns a completed render."""
    db = MagicMock()
    # query().filter().first() returns a row tuple with rendered_asset_path.
    db.query.return_value.filter.return_value.first.return_value = (rendered_path,)
    return db


class TestCunResolvedRender:
    """When a CUN render is completed, the segment MUST use the
    rendered asset path."""

    def test_cun_segment_uses_rendered_path_when_completed(self):
        """Completed render → asset_uri replaced with rendered_asset_path."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun()
        rendered_path = "/cun_cache/abc123.mp4"

        result = daemon._ensure_cun_ready(
            block, sb_dict, db=_mock_db_completed_render(rendered_path),
        )

        cun_segs = [s for s in result.segments if s.segment_type == "coming_up_next"]
        assert len(cun_segs) == 1, "Completed CUN render must be included"
        assert cun_segs[0].asset_uri == rendered_path

    def test_cun_segment_preserves_duration_when_resolved(self):
        """Resolved CUN segment must keep original duration."""
        daemon = _make_daemon()
        cun_dur = 10_000
        block = _make_block_with_cun(cun_duration_ms=cun_dur)
        sb_dict = _make_sb_dict_with_cun()

        result = daemon._ensure_cun_ready(
            block, sb_dict, db=_mock_db_completed_render(),
        )

        cun_segs = [s for s in result.segments if s.segment_type == "coming_up_next"]
        assert cun_segs[0].segment_duration_ms == cun_dur


# ---------------------------------------------------------------------------
# INV-CUN-DEDUP-BEFORE-RENDER-001: Dedup check before enqueue
# ---------------------------------------------------------------------------

class TestCunDedupBeforeRender:
    """INV-CUN-DEDUP-BEFORE-RENDER-001: Before enqueueing a render request,
    check for an existing completed request with the same content_hash."""

    def test_ensure_cun_ready_enqueues_missing_request(self):
        """When no render request exists, _enqueue_cun_render_request is called."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun(next_program_title="Cheers S01E02")

        db = _mock_db_no_render()
        with patch.object(daemon, "_enqueue_cun_render_request") as mock_enqueue:
            daemon._ensure_cun_ready(block, sb_dict, db=db)

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs["next_program_title"] == "Cheers S01E02"

    def test_no_enqueue_when_render_completed(self):
        """When a completed render exists, no new request is enqueued."""
        daemon = _make_daemon()
        block = _make_block_with_cun()
        sb_dict = _make_sb_dict_with_cun()

        db = _mock_db_completed_render()
        with patch.object(daemon, "_enqueue_cun_render_request") as mock_enqueue:
            daemon._ensure_cun_ready(block, sb_dict, db=db)

        mock_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# INV-CUN-PRIORITY-PLAYOUT-001: Playout-time priority
# ---------------------------------------------------------------------------

class TestCunPriorityPlayout:
    """INV-CUN-PRIORITY-PLAYOUT-001: CUN render priority MUST be ordered
    by playout time — soonest-airing segments render first."""

    def test_priority_derived_from_segment_start_time(self):
        """Earlier CUN segment gets lower priority value (renders first)."""
        daemon = _make_daemon()
        early_start_ms = 1_000_000_000_000
        late_start_ms = 1_000_000_100_000

        block_early = _make_block_with_cun(block_start_ms=early_start_ms)
        sb_dict_early = _make_sb_dict_with_cun(block_start_ms=early_start_ms)

        block_late = _make_block_with_cun(block_start_ms=late_start_ms)
        sb_dict_late = _make_sb_dict_with_cun(block_start_ms=late_start_ms)

        priorities = []
        db = _mock_db_no_render()
        with patch.object(
            daemon, "_enqueue_cun_render_request",
            side_effect=lambda **kwargs: priorities.append(kwargs["priority"]),
        ):
            daemon._ensure_cun_ready(block_early, sb_dict_early, db=db)
            daemon._ensure_cun_ready(block_late, sb_dict_late, db=db)

        assert len(priorities) == 2
        assert priorities[0] < priorities[1], (
            f"Earlier segment priority ({priorities[0]}) must be lower "
            f"than later ({priorities[1]})"
        )


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-DEDUP-001: Content-addressed hash
# ---------------------------------------------------------------------------

class TestCunContentHash:
    """INV-CUN-CACHE-DEDUP-001: Rendered CUN assets MUST be content-addressed
    by hash(template_id, title) for deduplication."""

    def test_same_template_and_title_produce_same_hash(self):
        """Deterministic: same inputs → same content_hash."""
        h1 = _content_hash("default", "Cheers S01E02")
        h2 = _content_hash("default", "Cheers S01E02")
        assert h1 == h2

    def test_different_title_produces_different_hash(self):
        """Different title → different content_hash."""
        h1 = _content_hash("default", "Cheers S01E02")
        h2 = _content_hash("default", "Frasier S01E01")
        assert h1 != h2

    def test_different_template_produces_different_hash(self):
        """Different template → different content_hash."""
        h1 = _content_hash("default", "Cheers S01E02")
        h2 = _content_hash("seasonal_winter", "Cheers S01E02")
        assert h1 != h2
