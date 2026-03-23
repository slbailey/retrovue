"""INV-EXPANSION-NON-MUTATION-001: Expansion must not call
expand_program_block() to re-derive structural segments.

The expansion layer (_expand_blocks_inner) must consume compiled_segments
as-is, hydrating asset_id → asset_uri only. It must NOT call
expand_program_block() which would re-run break detection, re-derive
chapter markers from the catalog, and produce new content segments.

This test is expected to FAIL against the current implementation.
_expand_blocks_inner() currently calls expand_program_block() for every
block, re-deriving content structure at expansion time.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Minimal stubs for DslScheduleService
# ---------------------------------------------------------------------------

class _FakeAssetMeta:
    def __init__(self, file_uri: str, duration_sec: int = 1320,
                 chapter_markers_sec=None, loudness_gain_db: float = 0.0):
        self.file_uri = file_uri
        self.duration_sec = duration_sec
        self.chapter_markers_sec = chapter_markers_sec or []
        self.loudness_gain_db = loudness_gain_db


class _FakeResolver:
    def __init__(self):
        self._assets = {
            "ep-001": _FakeAssetMeta(
                file_uri="/mnt/episodes/ep-001.mkv",
                duration_sec=1320,
                chapter_markers_sec=[420.0, 840.0],
                loudness_gain_db=-2.5,
            ),
        }

    def lookup(self, asset_id: str):
        if asset_id in self._assets:
            return self._assets[asset_id]
        raise KeyError(f"Asset not found: {asset_id}")

    def asset_needs_loudness_measurement(self, asset_id: str) -> bool:
        return False


def _make_schedule_with_break_aware_segments():
    """Build a schedule dict as if compile_schedule() produced break-aware
    compiled_segments (the target model)."""
    return {
        "program_blocks": [
            {
                "title": "Cheers ep-001",
                "asset_id": "ep-001",
                "start_at": "2026-04-01T06:00:00+00:00",
                "slot_duration_sec": 1800,
                "episode_duration_sec": 1320,
                "compiled_segments": [
                    # Act 1: 0–420s
                    {
                        "segment_type": "content",
                        "asset_id": "ep-001",
                        "duration_ms": 420000,
                        "asset_start_offset_ms": 0,
                        "gain_db": -2.5,
                    },
                    # Break 1 filler
                    {
                        "segment_type": "filler",
                        "duration_ms": 160000,
                    },
                    # Act 2: 420–840s
                    {
                        "segment_type": "content",
                        "asset_id": "ep-001",
                        "duration_ms": 420000,
                        "asset_start_offset_ms": 420000,
                        "gain_db": -2.5,
                    },
                    # Break 2 filler
                    {
                        "segment_type": "filler",
                        "duration_ms": 160000,
                    },
                    # Act 3: 840–1320s
                    {
                        "segment_type": "content",
                        "asset_id": "ep-001",
                        "duration_ms": 480000,
                        "asset_start_offset_ms": 840000,
                        "gain_db": -2.5,
                    },
                    # Post-content filler
                    {
                        "segment_type": "filler",
                        "duration_ms": 160000,
                    },
                ],
            },
        ],
    }


class TestExpansionDoesNotCallExpandProgramBlock:
    """INV-EXPANSION-NON-MUTATION-001: expand_program_block() must not be
    called during expansion."""

    def test_expand_blocks_inner_does_not_call_expand_program_block(self):
        """Patch expand_program_block and verify it is NOT called when
        _expand_blocks_inner processes blocks with compiled_segments."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_break_aware_segments()
        resolver = _FakeResolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "network"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        with patch(
            "retrovue.runtime.dsl_schedule_service.expand_program_block",
            wraps=None,
        ) as mock_expand:
            mock_expand.side_effect = AssertionError(
                "INV-EXPANSION-NON-MUTATION-001 VIOLATED: "
                "expand_program_block() was called during expansion. "
                "Expansion must consume compiled_segments without "
                "re-deriving content structure."
            )
            try:
                blocks = svc._expand_blocks_inner(schedule, resolver)
            except AssertionError as e:
                if "INV-EXPANSION-NON-MUTATION-001" in str(e):
                    pytest.fail(str(e))
                raise

    def test_expanded_block_preserves_compiled_segment_count(self):
        """The expanded ScheduledBlock must contain the same number of
        structural segments as compiled_segments (content entries match)."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_break_aware_segments()
        resolver = _FakeResolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "network"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)

        # This test may fail differently depending on implementation:
        # - If expand_program_block() is called, the content segment count
        #   will match break detection output (correct count but wrong path)
        # - If hydration is used, content count should match compiled_segments
        block = blocks[0]
        compiled_content = [
            s for s in schedule["program_blocks"][0]["compiled_segments"]
            if s.get("segment_type") == "content"
        ]
        expanded_content = [
            s for s in block.segments
            if s.segment_type == "content"
        ]

        assert len(expanded_content) == len(compiled_content), (
            f"INV-EXPANSION-NON-MUTATION-001: Expanded block has "
            f"{len(expanded_content)} content segments but compiled_segments "
            f"has {len(compiled_content)}. Expansion must preserve structural "
            f"segment count."
        )

    def test_expanded_segments_match_compiled_durations(self):
        """Each structural segment in the expanded block must have the same
        duration_ms as its corresponding compiled_segments entry."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_break_aware_segments()
        resolver = _FakeResolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "network"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        compiled_cs = schedule["program_blocks"][0]["compiled_segments"]
        compiled_content = [s for s in compiled_cs if s.get("segment_type") == "content"]
        expanded_content = [s for s in block.segments if s.segment_type == "content"]

        for i, (comp, exp) in enumerate(zip(compiled_content, expanded_content)):
            assert exp.segment_duration_ms == comp["duration_ms"], (
                f"INV-EXPANSION-NON-MUTATION-001: Content segment {i} — "
                f"compiled duration {comp['duration_ms']}ms != "
                f"expanded duration {exp.segment_duration_ms}ms. "
                f"Expansion must not modify structural segment durations."
            )

    def test_expanded_segments_have_resolved_uris(self):
        """Expansion must hydrate asset_id → asset_uri (path resolution is
        permitted by INV-EXPANSION-NON-MUTATION-001)."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_break_aware_segments()
        resolver = _FakeResolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "network"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        for i, seg in enumerate(content_segs):
            assert seg.asset_uri != "", (
                f"Content segment {i} has empty asset_uri. "
                f"Expansion must hydrate asset_id → asset_uri."
            )
            assert seg.asset_uri == "/mnt/episodes/ep-001.mkv", (
                f"Content segment {i} has wrong URI: {seg.asset_uri}"
            )
