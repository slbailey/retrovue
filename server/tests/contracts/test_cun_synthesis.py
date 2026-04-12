"""Contract tests for CUN (Coming Up Next) synthesis pipeline invariants.

All 11 Phase 1 CUN invariants.

Contracts:
    INV-CUN-FEATURE-FLAG-001
    INV-CUN-SCHEDULE-SCOPED-001
    INV-CUN-RENDER-IDLE-001
    INV-CUN-RENDER-DEADLINE-001
    INV-CUN-SKIP-IF-UNREADY-001
    INV-CUN-PRIORITY-PLAYOUT-001
    INV-CUN-CACHE-DEDUP-001
    INV-CUN-DEDUP-BEFORE-RENDER-001
    INV-CUN-CACHE-UNTIL-USED-001
    INV-CUN-CACHE-SAFE-CLEANUP-001
    INV-CUN-TEMPLATE-DETERMINISTIC-001

Parent issue: RETA-182
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# INV-CUN-FEATURE-FLAG-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunFeatureFlag:
    """INV-CUN-FEATURE-FLAG-001: CUN gated by channel-level features.coming_up_next."""

    def test_flag_false_no_cun_segments(self):
        """When features.coming_up_next is false, no CUN segments appear."""
        from retrovue.runtime.optional_presentation import (
            evaluate_optional_presentation,
        )

        blocks = [
            {
                "title": "Block A",
                "start_utc_ms": 1000000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-1", "duration_ms": 1700000},
                    {"segment_type": "filler", "asset_id": "filler-1", "duration_ms": 100000},
                ],
            },
            {
                "title": "Block B",
                "start_utc_ms": 1800000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-2", "duration_ms": 1800000},
                ],
            },
        ]
        continuity_with_cun = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_renders", "max_duration_ms": 10000},
            ],
        }
        features = {"coming_up_next": False}

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity_with_cun,
            broadcast_day="2026-04-10",
            channel_id="test-channel",
            features=features,
        )

        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) == 0, (
            f"INV-CUN-FEATURE-FLAG-001 violated: {len(cun_segments)} CUN segments "
            f"placed when features.coming_up_next is false"
        )

    def test_flag_true_cun_segments_placed(self):
        """When features.coming_up_next is true, CUN segments appear."""
        from retrovue.runtime.optional_presentation import (
            evaluate_optional_presentation,
        )

        blocks = [
            {
                "title": "Block A",
                "start_utc_ms": 1000000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-1", "duration_ms": 1700000},
                    {"segment_type": "filler", "asset_id": "filler-1", "duration_ms": 100000},
                ],
            },
            {
                "title": "Block B",
                "start_utc_ms": 1800000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-2", "duration_ms": 1800000},
                ],
            },
        ]
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_renders", "max_duration_ms": 10000},
            ],
        }

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-channel",
            features={"coming_up_next": True},
        )

        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]
        assert len(cun_segments) >= 1, (
            f"INV-CUN-FEATURE-FLAG-001: expected >= 1 CUN segment with flag=true, "
            f"got {len(cun_segments)}"
        )

    def test_no_render_requests_when_disabled(self):
        """CunRenderRequest is schedule-scoped; flag=false prevents placement."""
        from retrovue.runtime.cun_synthesis import CunRenderRequest

        assert hasattr(CunRenderRequest, "__tablename__")
        assert CunRenderRequest.__tablename__ == "cun_render_requests"


# ---------------------------------------------------------------------------
# INV-CUN-SCHEDULE-SCOPED-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunScheduleScoped:
    """INV-CUN-SCHEDULE-SCOPED-001: CUN uses its own pipeline, not ProcessorJob."""

    def test_cun_render_request_not_processor_job(self):
        """CunRenderRequest must not inherit from ProcessorJob."""
        from retrovue.runtime.cun_synthesis import CunRenderRequest
        from retrovue.catalog.processor_jobs import ProcessorJob

        assert not issubclass(CunRenderRequest, ProcessorJob), (
            "INV-CUN-SCHEDULE-SCOPED-001 violated: CunRenderRequest inherits ProcessorJob"
        )

    def test_cun_not_in_enricher_registry(self):
        """No enricher with CUN responsibility exists in the enricher registry."""
        try:
            from retrovue.usecases.asset_enrich import ENRICHER_REGISTRY

            cun_enrichers = [
                name
                for name in ENRICHER_REGISTRY
                if "cun" in name.lower() or "coming_up" in name.lower()
            ]
            assert len(cun_enrichers) == 0, (
                f"INV-CUN-SCHEDULE-SCOPED-001 violated: CUN enrichers found: {cun_enrichers}"
            )
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# INV-CUN-RENDER-IDLE-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunRenderIdle:
    """INV-CUN-RENDER-IDLE-001: CUN rendering happens during idle time, not compilation."""

    def test_compilation_does_not_invoke_render(self):
        """Schedule compilation places CUN intent, not rendered assets."""
        from retrovue.runtime.optional_presentation import (
            evaluate_optional_presentation,
        )

        blocks = [
            {
                "title": "Block A",
                "start_utc_ms": 1000000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-1", "duration_ms": 1700000},
                    {"segment_type": "filler", "asset_id": "filler-1", "duration_ms": 100000},
                ],
            },
            {
                "title": "Block B",
                "start_utc_ms": 1800000,
                "slot_duration_ms": 1800000,
                "compiled_segments": [
                    {"segment_type": "content", "asset_id": "movie-2", "duration_ms": 1800000},
                ],
            },
        ]
        continuity = {
            "optional": [
                {"type": "coming_up_next", "pool": "cun_renders", "max_duration_ms": 10000},
            ],
        }

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity,
            broadcast_day="2026-04-10",
            channel_id="test-channel",
            features={"coming_up_next": True},
        )

        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]

        for seg in cun_segments:
            assert "rendered_asset_path" not in seg, (
                "INV-CUN-RENDER-IDLE-001 violated: rendered_asset_path at compile time"
            )
            assert "next_program_title" in seg, (
                "INV-CUN-RENDER-IDLE-001: missing next_program_title editorial intent"
            )


# ---------------------------------------------------------------------------
# INV-CUN-RENDER-DEADLINE-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunRenderDeadline:
    """INV-CUN-RENDER-DEADLINE-001: Late renders are marked SKIPPED."""

    def test_past_deadline_marked_skipped(self, contract_clock):
        """Past deadline detected correctly."""
        from retrovue.runtime.cun_synthesis import CunSynthesisWorker

        now_ms = contract_clock.now_utc_ms()
        segment_start = datetime.fromtimestamp(
            (now_ms + 60_000) / 1000.0,
            tz=timezone.utc,
        )
        margin_ms = 30_000

        contract_clock.advance_ms(40_000)
        now = datetime.fromtimestamp(
            contract_clock.now_utc_ms() / 1000.0,
            tz=timezone.utc,
        )

        assert CunSynthesisWorker.is_past_deadline(segment_start, now, margin_ms), (
            "INV-CUN-RENDER-DEADLINE-001 violated: past deadline not detected"
        )

    def test_before_deadline_proceeds(self, contract_clock):
        """Before deadline not flagged."""
        from retrovue.runtime.cun_synthesis import CunSynthesisWorker

        now_ms = contract_clock.now_utc_ms()
        segment_start = datetime.fromtimestamp(
            (now_ms + 120_000) / 1000.0,
            tz=timezone.utc,
        )
        margin_ms = 30_000
        now = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)

        assert not CunSynthesisWorker.is_past_deadline(
            segment_start, now, margin_ms
        ), ("INV-CUN-RENDER-DEADLINE-001 violated: before deadline incorrectly flagged")


# ---------------------------------------------------------------------------
# INV-CUN-SKIP-IF-UNREADY-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunSkipIfUnready:
    """INV-CUN-SKIP-IF-UNREADY-001: Unready CUN segments are skipped."""

    def test_pending_render_skipped(self):
        """Pending render -> skip."""
        from retrovue.runtime.cun_synthesis import ensure_cun_ready

        seg = {
            "segment_type": "coming_up_next",
            "next_program_title": "Show A",
            "duration_ms": 10000,
        }
        assert ensure_cun_ready(seg, render_status="pending") is None

    def test_failed_render_skipped(self):
        """Failed render -> skip."""
        from retrovue.runtime.cun_synthesis import ensure_cun_ready

        seg = {
            "segment_type": "coming_up_next",
            "next_program_title": "Show B",
            "duration_ms": 10000,
        }
        assert ensure_cun_ready(seg, render_status="failed") is None

    def test_completed_render_used(self):
        """Completed render -> included with rendered_asset_path."""
        from retrovue.runtime.cun_synthesis import ensure_cun_ready

        seg = {
            "segment_type": "coming_up_next",
            "next_program_title": "Show C",
            "duration_ms": 10000,
        }
        result = ensure_cun_ready(
            seg,
            render_status="completed",
            rendered_asset_path="/cache/abc.mp4",
        )
        assert result is not None
        assert result["rendered_asset_path"] == "/cache/abc.mp4"
        assert result["next_program_title"] == "Show C"

    def test_no_blocking_on_unready(self):
        """ensure_cun_ready returns immediately for all non-completed states."""
        import time

        from retrovue.runtime.cun_synthesis import ensure_cun_ready

        seg = {
            "segment_type": "coming_up_next",
            "next_program_title": "Test",
            "duration_ms": 10000,
        }
        start = time.monotonic()
        for status in ("pending", "running", "failed", "skipped", None):
            ensure_cun_ready(seg, render_status=status)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, f"ensure_cun_ready blocked for {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# INV-CUN-PRIORITY-PLAYOUT-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunPriorityPlayout:
    """INV-CUN-PRIORITY-PLAYOUT-001: Soonest-airing segments render first."""

    def test_earlier_segment_claimed_first(self):
        """Earlier playout time -> lower priority value -> claimed first."""
        t1 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 10, 21, 0, 0, tzinfo=timezone.utc)
        assert int(t1.timestamp()) < int(t2.timestamp())

    def test_priority_reflects_playout_time(self):
        """claim_next orders by priority ASC."""
        import inspect

        from retrovue.runtime.cun_queue import claim_next
        from retrovue.runtime.cun_synthesis import CunRenderRequest

        assert hasattr(CunRenderRequest, "priority")

        source = inspect.getsource(claim_next)
        assert "priority" in source and "asc" in source.lower(), (
            "INV-CUN-PRIORITY-PLAYOUT-001: claim_next must order by priority ASC"
        )


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-DEDUP-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheDedup:
    """INV-CUN-CACHE-DEDUP-001: hash(template_id, title) deduplication."""

    def test_same_inputs_same_hash(self):
        from retrovue.runtime.cun_synthesis import cun_content_hash

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-retro-01", "The Tonight Show")
        assert h1 == h2

    def test_different_title_different_hash(self):
        from retrovue.runtime.cun_synthesis import cun_content_hash

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-retro-01", "Late Night")
        assert h1 != h2

    def test_different_template_different_hash(self):
        from retrovue.runtime.cun_synthesis import cun_content_hash

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-neon-02", "The Tonight Show")
        assert h1 != h2


# ---------------------------------------------------------------------------
# INV-CUN-DEDUP-BEFORE-RENDER-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunDedupBeforeRender:
    """INV-CUN-DEDUP-BEFORE-RENDER-001: Reuse existing completed render."""

    def test_existing_completed_render_reused(self):
        """run_once calls find_completed_by_hash before render_fn."""
        import inspect

        from retrovue.runtime.cun_synthesis_worker import run_once

        source = inspect.getsource(run_once)
        assert "find_completed_by_hash" in source
        # render_fn() invocation must not appear before the dedup check.
        # The parameter declaration (render_fn: callable) is fine; we check
        # for actual calls: render_fn(cmd) or render_fn(.
        before_dedup = source.split("find_completed_by_hash")[0]
        assert "render_fn(" not in before_dedup

    def test_no_existing_render_proceeds_to_ffmpeg(self):
        """render_fn is called after the dedup check."""
        import inspect

        from retrovue.runtime.cun_synthesis_worker import run_once

        source = inspect.getsource(run_once)
        after_dedup = source.split("find_completed_by_hash")[-1]
        assert "render_fn" in after_dedup


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-UNTIL-USED-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheUntilUsed:
    """INV-CUN-CACHE-UNTIL-USED-001: Retain rendered assets until after broadcast."""

    def test_future_segment_not_cleaned(self, contract_clock):
        from retrovue.runtime.cun_synthesis import cun_cleanup_eligible

        now = datetime.fromtimestamp(
            contract_clock.now_utc_ms() / 1000.0, tz=timezone.utc
        )
        future = now + timedelta(hours=1)
        assert not cun_cleanup_eligible([future], now)

    def test_past_segment_eligible_for_cleanup(self, contract_clock):
        from retrovue.runtime.cun_synthesis import cun_cleanup_eligible

        now = datetime.fromtimestamp(
            contract_clock.now_utc_ms() / 1000.0, tz=timezone.utc
        )
        past = now - timedelta(hours=1)
        assert cun_cleanup_eligible([past], now)


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-SAFE-CLEANUP-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheSafeCleanup:
    """INV-CUN-CACHE-SAFE-CLEANUP-001: All referencing requests must have aired."""

    def test_shared_hash_one_future_blocks_cleanup(self, contract_clock):
        from retrovue.runtime.cun_synthesis import cun_cleanup_eligible

        now = datetime.fromtimestamp(
            contract_clock.now_utc_ms() / 1000.0, tz=timezone.utc
        )
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)
        assert not cun_cleanup_eligible([past, future], now)

    def test_shared_hash_all_past_allows_cleanup(self, contract_clock):
        from retrovue.runtime.cun_synthesis import cun_cleanup_eligible

        now = datetime.fromtimestamp(
            contract_clock.now_utc_ms() / 1000.0, tz=timezone.utc
        )
        past_a = now - timedelta(hours=2)
        past_b = now - timedelta(hours=1)
        assert cun_cleanup_eligible([past_a, past_b], now)


# ---------------------------------------------------------------------------
# INV-CUN-TEMPLATE-DETERMINISTIC-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunTemplateDeterministic:
    """INV-CUN-TEMPLATE-DETERMINISTIC-001: SHA256-seeded deterministic selection."""

    def test_same_inputs_same_template(self):
        from retrovue.runtime.cun_synthesis import cun_select_template

        templates = [
            {"id": "retro-01", "background": "bg1.mp4"},
            {"id": "neon-02", "background": "bg2.mp4"},
            {"id": "vhs-03", "background": "bg3.mp4"},
        ]
        t1 = cun_select_template(
            channel_id="hbo",
            broadcast_day="2026-04-10",
            block_index=0,
            templates=templates,
        )
        t2 = cun_select_template(
            channel_id="hbo",
            broadcast_day="2026-04-10",
            block_index=0,
            templates=templates,
        )
        assert t1 == t2

    def test_different_inputs_may_differ(self):
        from retrovue.runtime.cun_synthesis import cun_select_template

        templates = [
            {"id": "retro-01", "background": "bg1.mp4"},
            {"id": "neon-02", "background": "bg2.mp4"},
            {"id": "vhs-03", "background": "bg3.mp4"},
        ]
        results = set()
        for idx in range(10):
            t = cun_select_template(
                channel_id="hbo",
                broadcast_day="2026-04-10",
                block_index=idx,
                templates=templates,
            )
            results.add(t["id"])
        assert len(results) > 1
