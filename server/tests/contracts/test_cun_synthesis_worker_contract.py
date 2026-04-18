"""
Contract tests for CunSynthesisWorker.

Invariants tested:
- INV-CUN-RENDER-DEADLINE-001: renders past deadline must be SKIPPED
- INV-CUN-DEDUP-BEFORE-RENDER-001: existing completed render reused, no re-render
- INV-CUN-PRIORITY-PLAYOUT-001: soonest playout renders first (priority ASC)
- INV-CUN-CACHE-DEDUP-001: content hash is deterministic hash(template_id, title)

Uses real DB sessions via infra.uow.session(). Requires cun_render_requests table.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time

import pytest

from retrovue.domain.entities import Channel, CunRenderRequest
from retrovue.infra.uow import session
from retrovue.runtime.clock import SystemClock
from retrovue.runtime.cun_queue import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    claim_next,
    complete,
    content_hash_for,
    find_completed_by_hash,
    skip,
)
from retrovue.runtime.cun_synthesis_worker import (
    CunTemplateConfig,
    run_once,
)

_TEST_CLOCK = SystemClock()


_test_channel_id: uuid.UUID | None = None


def _get_or_create_test_channel(db) -> uuid.UUID:
    """Get or create a persistent test channel for CUN tests."""
    global _test_channel_id
    if _test_channel_id is not None:
        existing = db.get(Channel, _test_channel_id)
        if existing is not None:
            return _test_channel_id

    slug = f"cun-test-{uuid.uuid4().hex[:8]}"
    ch = Channel(
        id=uuid.uuid4(),
        slug=slug,
        title="CUN Test Channel",
        grid_block_minutes=30,
        kind="network",
        programming_day_start=dt_time(6, 0),
        block_start_offsets_minutes=[0],
    )
    db.add(ch)
    db.flush()
    _test_channel_id = ch.id
    return ch.id


def _make_request(
    db,
    *,
    segment_start_utc: datetime | None = None,
    title: str = "Next Show",
    template_id: str = "default",
    priority: int = 100,
    status: str = STATUS_PENDING,
    content_hash: str | None = None,
    rendered_asset_path: str | None = None,
) -> CunRenderRequest:
    """Insert a CunRenderRequest row for testing. Uses shared test channel."""
    channel_id = _get_or_create_test_channel(db)
    req = CunRenderRequest(
        id=uuid.uuid4(),
        channel_id=channel_id,
        segment_start_utc=segment_start_utc or (datetime.now(UTC) + timedelta(hours=1)),
        next_program_title=title,
        template_id=template_id,
        status=status,
        priority=priority,
        content_hash=content_hash,
        rendered_asset_path=rendered_asset_path,
    )
    db.add(req)
    db.flush()
    return req


class TestCunQueueContract:
    """Verify CUN render request queue guarantees."""

    def _drain_pending(self, max_jobs: int = 500):
        """Drain all pending CUN requests so tests see a clean queue."""
        for _ in range(max_jobs):
            with session() as db:
                req = claim_next(db, clock=_TEST_CLOCK)
                if req is None:
                    return
                skip(db, req.id, "test drain", clock=_TEST_CLOCK)

    def test_claim_returns_lowest_priority_first(self):
        """INV-CUN-PRIORITY-PLAYOUT-001: soonest playout (lowest priority number) claimed first."""
        self._drain_pending()
        now = datetime.now(UTC)
        with session() as db:
            _make_request(db, priority=50, title="Later",
                         segment_start_utc=now + timedelta(hours=2))
            _make_request(db, priority=10, title="Sooner",
                         segment_start_utc=now + timedelta(hours=1))

        with session() as db:
            first = claim_next(db, clock=_TEST_CLOCK)
            assert first is not None
            assert first.priority == 10
            assert first.next_program_title == "Sooner"

        # cleanup
        with session() as db:
            second = claim_next(db, clock=_TEST_CLOCK)
            if second:
                skip(db, second.id, "cleanup", clock=_TEST_CLOCK)

    def test_claim_transitions_pending_to_running(self):
        """Claim must set status=running and started_at."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db)
            req_id = req.id

        with session() as db:
            claimed = claim_next(db, clock=_TEST_CLOCK)
            assert claimed is not None
            assert claimed.id == req_id
            assert claimed.status == STATUS_RUNNING
            assert claimed.started_at is not None

    def test_complete_sets_path_and_hash(self):
        """Complete must record rendered_asset_path, content_hash, and completed_at."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db)
            req_id = req.id

        with session() as db:
            claimed = claim_next(db, clock=_TEST_CLOCK)
            assert claimed is not None

        h = content_hash_for("default", "Next Show")
        with session() as db:
            complete(db, req_id, "/cache/test.mp4", h, clock=_TEST_CLOCK)

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_COMPLETED
            assert row.rendered_asset_path == "/cache/test.mp4"
            assert row.content_hash == h
            assert row.completed_at is not None

    def test_dedup_finds_completed_by_hash(self):
        """INV-CUN-DEDUP-BEFORE-RENDER-001: find_completed_by_hash returns existing completed render."""
        h = content_hash_for("tmpl_a", "My Show")
        with session() as db:
            _make_request(
                db,
                title="My Show",
                template_id="tmpl_a",
                status=STATUS_COMPLETED,
                content_hash=h,
                rendered_asset_path="/cache/existing.mp4",
            )

        with session() as db:
            found = find_completed_by_hash(db, h)
            assert found is not None
            assert found.rendered_asset_path == "/cache/existing.mp4"

    def test_dedup_returns_none_when_no_completed(self):
        """INV-CUN-DEDUP-BEFORE-RENDER-001: no completed render returns None."""
        with session() as db:
            found = find_completed_by_hash(db, "nonexistent_hash_value")
            assert found is None

    def test_content_hash_deterministic(self):
        """INV-CUN-CACHE-DEDUP-001: same inputs produce same hash."""
        h1 = content_hash_for("default", "Cheers")
        h2 = content_hash_for("default", "Cheers")
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex

    def test_content_hash_varies_with_inputs(self):
        """INV-CUN-CACHE-DEDUP-001: different inputs produce different hashes."""
        h1 = content_hash_for("default", "Cheers")
        h2 = content_hash_for("default", "Seinfeld")
        h3 = content_hash_for("retro_v2", "Cheers")
        assert h1 != h2
        assert h1 != h3

    def test_skip_marks_skipped_with_reason(self):
        """INV-CUN-RENDER-DEADLINE-001: skip records reason and sets completed_at."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db)
            req_id = req.id

        with session() as db:
            claimed = claim_next(db, clock=_TEST_CLOCK)
            assert claimed is not None

        with session() as db:
            skip(db, req_id, "past render deadline", clock=_TEST_CLOCK)

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_SKIPPED
            assert row.error_message == "past render deadline"
            assert row.completed_at is not None

    def test_claim_skip_locked_no_double_claim(self):
        """Only one worker can claim a given request; second claim returns different or None."""
        self._drain_pending()
        now = datetime.now(UTC)
        with session() as db:
            _make_request(db, segment_start_utc=now + timedelta(hours=1))
            _make_request(db, segment_start_utc=now + timedelta(hours=2))

        first_id = None
        with session() as db:
            first = claim_next(db, clock=_TEST_CLOCK)
            assert first is not None
            first_id = first.id

        with session() as db:
            second = claim_next(db, clock=_TEST_CLOCK)
            if second is not None:
                assert second.id != first_id
                skip(db, second.id, "cleanup", clock=_TEST_CLOCK)

        # cleanup first
        with session() as db:
            skip(db, first_id, "cleanup", clock=_TEST_CLOCK)


# ---------------------------------------------------------------------------
# Worker-level tests (run_once with mock render)
# ---------------------------------------------------------------------------

_TEST_TEMPLATE = CunTemplateConfig(
    id="default",
    background="/assets/templates/cun/retro_loop_01.mp4",
    text_area_x=120,
    text_area_y=680,
    text_area_width=1680,
    text_area_height=200,
    font="/assets/fonts/retro_display.ttf",
    font_size=64,
    font_color="white",
    fade_in_ms=500,
    fade_out_ms=500,
)


def _mock_template_resolver(channel_id, template_id):
    """Always returns the test template."""
    return _TEST_TEMPLATE


def _noop_render(cmd):
    """No-op render function that simulates successful ffmpeg execution."""
    pass


class TestCunSynthesisWorkerContract:
    """Verify CunSynthesisWorker run_once behavior against invariants."""

    def _drain_pending(self, max_jobs: int = 500):
        for _ in range(max_jobs):
            with session() as db:
                req = claim_next(db, clock=_TEST_CLOCK)
                if req is None:
                    return
                skip(db, req.id, "test drain", clock=_TEST_CLOCK)

    def test_run_once_renders_and_completes(self, tmp_path):
        """Happy path: run_once claims, renders (mock), and completes."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db, title="Cheers",
                               segment_start_utc=datetime.now(UTC) + timedelta(hours=2))
            req_id = req.id

        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_mock_template_resolver,
            clock=_TEST_CLOCK,
            render_fn=_noop_render,
        )
        assert result is True

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_COMPLETED
            assert row.rendered_asset_path is not None
            assert row.content_hash is not None
            assert row.completed_at is not None

    def test_run_once_skips_past_deadline(self, tmp_path):
        """INV-CUN-RENDER-DEADLINE-001: request past deadline is skipped, not rendered."""
        self._drain_pending()
        req_id = None
        # segment_start_utc is 10 seconds from now; deadline margin is 30 seconds
        # so the deadline has already passed
        with session() as db:
            req = _make_request(
                db,
                title="Late Show",
                segment_start_utc=datetime.now(UTC) + timedelta(seconds=10),
            )
            req_id = req.id

        render_called = []

        def _tracking_render(cmd):
            render_called.append(cmd)

        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_mock_template_resolver,
            clock=_TEST_CLOCK,
            deadline_margin_ms=30_000,
            render_fn=_tracking_render,
        )
        assert result is True
        assert len(render_called) == 0  # ffmpeg must NOT have been called

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_SKIPPED
            assert "deadline" in row.error_message.lower()

    def test_run_once_dedup_reuses_existing(self, tmp_path):
        """INV-CUN-DEDUP-BEFORE-RENDER-001: existing completed render is reused."""
        self._drain_pending()
        title = "Seinfeld Dedup Test"
        tmpl = "default"
        h = content_hash_for(tmpl, title)

        # Create a completed render with the same content hash
        with session() as db:
            _make_request(
                db,
                title=title,
                template_id=tmpl,
                status=STATUS_COMPLETED,
                content_hash=h,
                rendered_asset_path="/cache/seinfeld.mp4",
                segment_start_utc=datetime.now(UTC) - timedelta(hours=1),
            )

        # Create a new pending request with same title+template
        req_id = None
        with session() as db:
            req = _make_request(
                db,
                title=title,
                template_id=tmpl,
                segment_start_utc=datetime.now(UTC) + timedelta(hours=2),
            )
            req_id = req.id

        render_called = []

        def _tracking_render(cmd):
            render_called.append(cmd)

        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_mock_template_resolver,
            clock=_TEST_CLOCK,
            render_fn=_tracking_render,
        )
        assert result is True
        assert len(render_called) == 0  # ffmpeg must NOT have been called

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_COMPLETED
            assert row.rendered_asset_path == "/cache/seinfeld.mp4"
            assert row.content_hash == h

    def test_run_once_returns_false_on_empty_queue(self, tmp_path):
        """Empty queue: run_once returns False without side effects."""
        self._drain_pending()
        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_mock_template_resolver,
            clock=_TEST_CLOCK,
            render_fn=_noop_render,
        )
        assert result is False

    def test_run_once_fails_on_render_error(self, tmp_path):
        """Render failure: request is marked failed with error message."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db, title="Bad Render",
                               segment_start_utc=datetime.now(UTC) + timedelta(hours=2))
            req_id = req.id

        def _failing_render(cmd):
            raise RuntimeError("ffmpeg crashed")

        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_mock_template_resolver,
            clock=_TEST_CLOCK,
            render_fn=_failing_render,
        )
        assert result is True

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_FAILED
            assert "ffmpeg crashed" in row.error_message

    def test_run_once_fails_on_missing_template(self, tmp_path):
        """Missing template: request is marked failed."""
        self._drain_pending()
        req_id = None
        with session() as db:
            req = _make_request(db, title="No Template",
                               template_id="nonexistent",
                               segment_start_utc=datetime.now(UTC) + timedelta(hours=2))
            req_id = req.id

        def _none_resolver(channel_id, template_id):
            return None

        result = run_once(
            cache_dir=str(tmp_path),
            template_resolver=_none_resolver,
            clock=_TEST_CLOCK,
            render_fn=_noop_render,
        )
        assert result is True

        with session() as db:
            row = db.get(CunRenderRequest, req_id)
            assert row.status == STATUS_FAILED
            assert "template not found" in row.error_message.lower()
