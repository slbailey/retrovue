"""Contract tests for schedule explain and schedule preview commands.

Coverage:
  explain:
    1. Finds correct ScheduleItem for a given time
    2. Prints compiled segments for template blocks
    3. Handles legacy blocks (no compiled_segments)

  preview:
    4. Returns correct segment list
    5. Respects compiled_segments path
    6. Respects legacy expansion path
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from retrovue.usecases.schedule_explain import explain_at, _find_item_at
from retrovue.usecases.schedule_preview import preview_at, _format_duration


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

BASE_DT = datetime(2026, 3, 6, 14, 30, tzinfo=timezone.utc)
BASE_MS = int(BASE_DT.timestamp() * 1000)


def _mock_channel(slug="hbo-classics"):
    ch = MagicMock()
    ch.id = uuid.uuid4()
    ch.slug = slug
    return ch


def _mock_revision(channel_id, broadcast_day):
    rev = MagicMock()
    rev.id = uuid.uuid4()
    rev.channel_id = channel_id
    rev.broadcast_day = broadcast_day
    rev.status = "active"
    rev.created_by = "dsl_schedule_service"
    return rev


def _mock_pointer(channel_id, broadcast_day, revision_id):
    ptr = MagicMock()
    ptr.channel_id = channel_id
    ptr.broadcast_day = broadcast_day
    ptr.schedule_revision_id = revision_id
    return ptr


def _mock_item_template(revision_id, slot_index=0):
    """ScheduleItem with compiled_segments (template block)."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.schedule_revision_id = revision_id
    item.slot_index = slot_index
    item.start_time = datetime(2026, 3, 6, 14, 0, tzinfo=timezone.utc)
    item.duration_sec = 7200
    item.content_type = "movie"
    item.asset_id = uuid.uuid4()
    item.window_uuid = None
    item.metadata_ = {
        "title": "Weekend at Bernie's",
        "template_id": "hbo_feature_with_intro",
        "epg_title": "HBO Feature Presentation",
        "asset_id_raw": "movie-001",
        "compiled_segments": [
            {
                "segment_type": "intro",
                "asset_id": "intro-hbo-001",
                "asset_uri": "/assets/intro-hbo-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 30000,
                "source_type": "collection",
                "source_name": "Intros",
                "is_primary": False,
                "gain_db": 0.0,
            },
            {
                "segment_type": "content",
                "asset_id": "movie-001",
                "asset_uri": "/assets/movie-001.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 5400000,
                "source_type": "pool",
                "source_name": "hbo_movies",
                "is_primary": True,
                "gain_db": 0.0,
            },
        ],
    }
    return item


def _mock_item_legacy(revision_id, slot_index=0):
    """ScheduleItem without compiled_segments (legacy block)."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.schedule_revision_id = revision_id
    item.slot_index = slot_index
    item.start_time = datetime(2026, 3, 6, 14, 0, tzinfo=timezone.utc)
    item.duration_sec = 3600  # 1 hour, covering 14:00-15:00
    item.content_type = "episode"
    item.asset_id = uuid.uuid4()
    item.window_uuid = None
    item.metadata_ = {
        "title": "Cheers S03E12",
        "asset_id_raw": "cheers-s03e12",
        "episode_duration_sec": 1320,
        "selector": {"collections": ["cheers"]},
    }
    return item


def _setup_db_for_explain(item):
    """Build a MagicMock db that returns the right channel/revision/item."""
    db = MagicMock()
    channel = _mock_channel()
    revision = _mock_revision(channel.id, item.start_time.date())
    pointer = _mock_pointer(channel.id, revision.broadcast_day, revision.id)
    item.schedule_revision_id = revision.id

    # Chain query mocks to return correct objects based on filter calls
    def query_side_effect(model):
        mock_q = MagicMock()
        model_name = getattr(model, '__name__', '') or str(model)
        if 'Channel' in str(model_name) and 'Active' not in str(model_name):
            mock_q.filter.return_value.first.return_value = channel
        elif 'ChannelActiveRevision' in str(model_name):
            mock_q.filter.return_value.first.return_value = pointer
        elif 'ScheduleRevision' in str(model_name):
            mock_q.filter.return_value.first.return_value = revision
        elif 'ScheduleItem' in str(model_name):
            mock_q.filter.return_value.order_by.return_value.all.return_value = [item]
        return mock_q

    db.query.side_effect = query_side_effect
    return db, channel, revision


# ─────────────────────────────────────────────────────────────────────────────
# explain: 1. Finds correct ScheduleItem
# ─────────────────────────────────────────────────────────────────────────────

class TestExplainFindsItem:

    def test_finds_item_covering_time(self):
        """explain_at returns the ScheduleItem whose time range covers the target."""
        item = _mock_item_template(uuid.uuid4())
        db, channel, revision = _setup_db_for_explain(item)

        result = explain_at(db, channel_slug="hbo-classics", at=BASE_DT)

        assert "error" not in result
        assert result["schedule_item"]["slot_index"] == 0
        assert result["schedule_item"]["title"] == "Weekend at Bernie's"

    def test_returns_error_for_unknown_channel(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = explain_at(db, channel_slug="nonexistent", at=BASE_DT)

        assert "error" in result
        assert "not found" in result["error"]


# ─────────────────────────────────────────────────────────────────────────────
# explain: 2. Prints compiled segments for template blocks
# ─────────────────────────────────────────────────────────────────────────────

class TestExplainCompiledSegments:

    def test_compiled_segments_in_result(self):
        """Template blocks include compiled_segments in explain output."""
        item = _mock_item_template(uuid.uuid4())
        db, _, _ = _setup_db_for_explain(item)

        result = explain_at(db, channel_slug="hbo-classics", at=BASE_DT)

        assert result["expansion_path"] == "compiled_segments (template)"
        assert "compiled_segments" in result
        segs = result["compiled_segments"]
        assert len(segs) == 2
        assert segs[0]["segment_type"] == "intro"
        assert segs[1]["segment_type"] == "content"
        assert segs[1]["is_primary"] is True

    def test_template_id_shown(self):
        item = _mock_item_template(uuid.uuid4())
        db, _, _ = _setup_db_for_explain(item)

        result = explain_at(db, channel_slug="hbo-classics", at=BASE_DT)

        assert result["schedule_item"]["template_id"] == "hbo_feature_with_intro"


# ─────────────────────────────────────────────────────────────────────────────
# explain: 3. Handles legacy blocks
# ─────────────────────────────────────────────────────────────────────────────

class TestExplainLegacy:

    def test_legacy_block_expansion_path(self):
        """Legacy blocks show expand_program_block path."""
        item = _mock_item_legacy(uuid.uuid4())
        db, _, _ = _setup_db_for_explain(item)

        result = explain_at(db, channel_slug="hbo-classics", at=BASE_DT)

        assert result["expansion_path"] == "expand_program_block (legacy)"
        assert "legacy_info" in result
        assert result["legacy_info"]["asset_id_raw"] == "cheers-s03e12"
        assert "compiled_segments" not in result


# ─────────────────────────────────────────────────────────────────────────────
# preview: 4. Returns correct segment list
# ─────────────────────────────────────────────────────────────────────────────

class TestPreviewSegmentList:

    @patch("retrovue.usecases.schedule_preview.fill_ad_blocks")
    @patch("retrovue.usecases.schedule_preview._deserialize_scheduled_block")
    @patch("retrovue.usecases.schedule_preview.load_segmented_blocks_from_active_revision")
    def test_returns_segments(self, mock_load, mock_deser, mock_fill):
        """preview_at returns a list of segments with all required fields."""
        db = MagicMock()
        block_start = BASE_MS - 1800000  # 30 min before
        block_end = BASE_MS + 1800000    # 30 min after

        mock_load.return_value = [{
            "block_id": "blk-test",
            "start_utc_ms": block_start,
            "end_utc_ms": block_end,
            "segments": [{"segment_type": "content", "asset_uri": "/test.mp4",
                         "asset_start_offset_ms": 0, "segment_duration_ms": 3600000}],
        }]

        fake_block = MagicMock()
        fake_block.block_id = "blk-test"
        fake_block.start_utc_ms = block_start
        fake_block.end_utc_ms = block_end
        seg = MagicMock()
        seg.segment_type = "content"
        seg.asset_uri = "/test.mp4"
        seg.asset_start_offset_ms = 0
        seg.segment_duration_ms = 3600000
        fake_block.segments = [seg]
        mock_deser.return_value = fake_block
        mock_fill.return_value = fake_block

        result = preview_at(db, channel_slug="test-ch", at=BASE_DT)

        assert "error" not in result
        assert result["block_id"] == "blk-test"
        assert result["segment_count"] == 1
        assert len(result["segments"]) == 1

        s = result["segments"][0]
        assert s["index"] == 0
        assert s["segment_type"] == "content"
        assert s["asset_uri"] == "/test.mp4"
        assert s["duration_ms"] == 3600000

    def test_returns_error_when_no_block(self):
        db = MagicMock()
        with patch(
            "retrovue.usecases.schedule_preview.load_segmented_blocks_from_active_revision"
        ) as mock_load:
            mock_load.return_value = None
            result = preview_at(db, channel_slug="missing", at=BASE_DT)

        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# preview: 5. Respects compiled_segments path
# ─────────────────────────────────────────────────────────────────────────────

class TestPreviewCompiledSegments:

    @patch("retrovue.usecases.schedule_preview.fill_ad_blocks")
    @patch("retrovue.usecases.schedule_preview._deserialize_scheduled_block")
    @patch("retrovue.usecases.schedule_preview.load_segmented_blocks_from_active_revision")
    def test_compiled_segments_produce_intro_and_content(self, mock_load, mock_deser, mock_fill):
        """Blocks with compiled_segments produce intro + content segments."""
        db = MagicMock()
        block_start = BASE_MS - 1800000
        block_end = BASE_MS + 5400000

        mock_load.return_value = [{
            "block_id": "blk-template",
            "start_utc_ms": block_start,
            "end_utc_ms": block_end,
            "segments": [
                {"segment_type": "intro", "asset_uri": "/intro.mp4",
                 "asset_start_offset_ms": 0, "segment_duration_ms": 30000},
                {"segment_type": "content", "asset_uri": "/movie.mp4",
                 "asset_start_offset_ms": 0, "segment_duration_ms": 5400000},
            ],
        }]

        fake_block = MagicMock()
        fake_block.block_id = "blk-template"
        fake_block.start_utc_ms = block_start
        fake_block.end_utc_ms = block_end
        intro_seg = MagicMock(segment_type="intro", asset_uri="/intro.mp4",
                              asset_start_offset_ms=0, segment_duration_ms=30000)
        content_seg = MagicMock(segment_type="content", asset_uri="/movie.mp4",
                                asset_start_offset_ms=0, segment_duration_ms=5400000)
        fake_block.segments = [intro_seg, content_seg]
        mock_deser.return_value = fake_block
        mock_fill.return_value = fake_block

        result = preview_at(db, channel_slug="hbo-classics", at=BASE_DT)

        assert result["segment_count"] == 2
        types = [s["segment_type"] for s in result["segments"]]
        assert types == ["intro", "content"]


# ─────────────────────────────────────────────────────────────────────────────
# preview: 6. Respects legacy expansion path
# ─────────────────────────────────────────────────────────────────────────────

class TestPreviewLegacy:

    @patch("retrovue.usecases.schedule_preview.fill_ad_blocks")
    @patch("retrovue.usecases.schedule_preview._deserialize_scheduled_block")
    @patch("retrovue.usecases.schedule_preview.load_segmented_blocks_from_active_revision")
    def test_legacy_block_expanded(self, mock_load, mock_deser, mock_fill):
        """Legacy blocks (no compiled_segments) still produce segments via
        the standard expansion path."""
        db = MagicMock()
        block_start = BASE_MS - 900000
        block_end = BASE_MS + 900000

        # A legacy block with content + filler (as expand_program_block would produce)
        mock_load.return_value = [{
            "block_id": "blk-legacy",
            "start_utc_ms": block_start,
            "end_utc_ms": block_end,
            "segments": [
                {"segment_type": "content", "asset_uri": "/cheers.mp4",
                 "asset_start_offset_ms": 0, "segment_duration_ms": 1320000},
                {"segment_type": "filler", "asset_uri": "",
                 "asset_start_offset_ms": 0, "segment_duration_ms": 480000},
            ],
        }]

        fake_block = MagicMock()
        fake_block.block_id = "blk-legacy"
        fake_block.start_utc_ms = block_start
        fake_block.end_utc_ms = block_end
        content_seg = MagicMock(segment_type="content", asset_uri="/cheers.mp4",
                                asset_start_offset_ms=0, segment_duration_ms=1320000)
        filler_seg = MagicMock(segment_type="filler", asset_uri="",
                               asset_start_offset_ms=0, segment_duration_ms=480000)
        fake_block.segments = [content_seg, filler_seg]
        mock_deser.return_value = fake_block
        mock_fill.return_value = fake_block

        result = preview_at(db, channel_slug="cheers-24-7", at=BASE_DT)

        assert result["segment_count"] == 2
        types = [s["segment_type"] for s in result["segments"]]
        assert types == ["content", "filler"]


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _format_duration
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatDuration:
    def test_seconds_only(self):
        assert _format_duration(30000) == "30s"

    def test_minutes_and_seconds(self):
        assert _format_duration(90000) == "1m30s"

    def test_hours(self):
        assert _format_duration(5400000) == "1h30m00s"
