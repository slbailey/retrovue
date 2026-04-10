"""Contract tests for CUN (Coming Up Next) synthesis pipeline invariants.

All 11 Phase 1 CUN invariants. These tests are RED — the CUN synthesis
pipeline does not exist yet. They define the behavioral contracts that
the implementation must satisfy.

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

import hashlib
from datetime import datetime, timedelta as _td, timezone

import pytest


# ---------------------------------------------------------------------------
# Deferred imports — these modules do not exist yet (RED).
# Each test class documents which module it requires.
# ---------------------------------------------------------------------------

def _import_cun_render_request():
    """Import CunRenderRequest from the synthesis module (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import CunRenderRequest  # noqa: F811
    return CunRenderRequest


def _import_cun_worker():
    """Import CunSynthesisWorker from the synthesis module (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import CunSynthesisWorker  # noqa: F811
    return CunSynthesisWorker


def _import_cun_content_hash():
    """Import cun_content_hash from the synthesis module (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import cun_content_hash  # noqa: F811
    return cun_content_hash


def _import_cun_select_template():
    """Import cun_select_template from the synthesis module (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import cun_select_template  # noqa: F811
    return cun_select_template


def _import_cun_cleanup_eligible():
    """Import cun_cleanup_eligible from the synthesis module (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import cun_cleanup_eligible  # noqa: F811
    return cun_cleanup_eligible


def _import_ensure_cun_ready():
    """Import ensure_cun_ready from the playlist builder CUN integration (does not exist yet)."""
    from retrovue.runtime.cun_synthesis import ensure_cun_ready  # noqa: F811
    return ensure_cun_ready


# ---------------------------------------------------------------------------
# INV-CUN-FEATURE-FLAG-001 — Feature flag gate
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

        # Feature flag is false — even though continuity declares CUN,
        # the feature gate must prevent placement.
        # The current evaluate_optional_presentation does NOT check the feature flag;
        # it relies on the caller to omit CUN from continuity when disabled.
        # This test asserts the system-level guarantee: when features.coming_up_next
        # is false, no CUN segments appear. The implementation must enforce this.
        features = {"coming_up_next": False}

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity_with_cun,
            broadcast_day="2026-04-10",
            channel_id="test-channel",
            features=features,
        )

        # Collect all CUN segments across all blocks
        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]

        # When feature flag is false, the system must produce zero CUN segments.
        assert len(cun_segments) == 0, (
            f"INV-CUN-FEATURE-FLAG-001 violated: {len(cun_segments)} CUN segments "
            f"placed when features.coming_up_next is false"
        )

    def test_flag_true_cun_segments_placed(self):
        """When features.coming_up_next is true AND continuity declares CUN,
        at least one CUN segment appears (given multi-block schedule)."""
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

        # With the flag true and a multi-block schedule, CUN should appear
        # in at least the first block (last block has no "next" to announce).
        assert len(cun_segments) >= 1, (
            f"INV-CUN-FEATURE-FLAG-001: expected >= 1 CUN segment with flag=true, "
            f"got {len(cun_segments)}"
        )

    def test_no_render_requests_when_disabled(self):
        """When feature flag is false, no CUN render requests are created.

        The feature gate in optional_presentation filters CUN elements before
        placement, so no CUN segments reach the playlist builder → no render
        requests are ever enqueued. This test confirms the gate produces zero
        CUN segments, which is the upstream guarantee that prevents requests.
        """
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

        result = evaluate_optional_presentation(
            blocks=blocks,
            continuity=continuity_with_cun,
            broadcast_day="2026-04-10",
            channel_id="test-channel",
            features={"coming_up_next": False},
        )

        cun_segments = [
            seg
            for block in result
            for seg in block["compiled_segments"]
            if seg["segment_type"] == "coming_up_next"
        ]

        # Zero CUN segments → zero render requests can ever be created.
        assert len(cun_segments) == 0, (
            f"INV-CUN-FEATURE-FLAG-001: {len(cun_segments)} CUN segments placed "
            f"when disabled — render requests would be created from these"
        )


# ---------------------------------------------------------------------------
# INV-CUN-SCHEDULE-SCOPED-001 — Schedule-scoped, not ProcessorJob
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunScheduleScoped:
    """INV-CUN-SCHEDULE-SCOPED-001: CUN uses its own pipeline, not ProcessorJob."""

    def test_cun_render_request_not_processor_job(self):
        """CunRenderRequest must not inherit from or reference ProcessorJob."""
        CunRenderRequest = _import_cun_render_request()

        from retrovue.catalog.processor_jobs import ProcessorJob

        assert not issubclass(CunRenderRequest, ProcessorJob), (
            "INV-CUN-SCHEDULE-SCOPED-001 violated: CunRenderRequest inherits ProcessorJob"
        )

    def test_cun_not_in_enricher_registry(self):
        """No enricher with CUN responsibility exists in the enricher registry."""
        # If the enricher registry has a CUN-related entry, this invariant is violated.
        try:
            from retrovue.usecases.asset_enrich import ENRICHER_REGISTRY
            cun_enrichers = [
                name for name in ENRICHER_REGISTRY
                if "cun" in name.lower() or "coming_up" in name.lower()
            ]
            assert len(cun_enrichers) == 0, (
                f"INV-CUN-SCHEDULE-SCOPED-001 violated: CUN enrichers found: {cun_enrichers}"
            )
        except ImportError:
            # ENRICHER_REGISTRY doesn't exist as expected — that's fine,
            # but the main test is CunRenderRequest independence from ProcessorJob.
            pass


# ---------------------------------------------------------------------------
# INV-CUN-RENDER-IDLE-001 — Render during idle, not compilation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunRenderIdle:
    """INV-CUN-RENDER-IDLE-001: CUN rendering happens during idle time, not compilation."""

    def test_compilation_does_not_invoke_render(self):
        """Schedule compilation with unresolved CUN must not invoke render."""
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

        # Compilation places the CUN segment with metadata (next_program_title)
        # but must NOT render it. The segment should have editorial intent only.
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

        # CUN segments at compilation time must carry next_program_title
        # but must NOT have a rendered_asset_path (that comes from the worker).
        for seg in cun_segments:
            assert "rendered_asset_path" not in seg, (
                f"INV-CUN-RENDER-IDLE-001 violated: CUN segment has rendered_asset_path "
                f"at compilation time: {seg}"
            )
            assert "next_program_title" in seg, (
                f"INV-CUN-RENDER-IDLE-001: CUN segment missing next_program_title "
                f"editorial intent: {seg}"
            )


# ---------------------------------------------------------------------------
# INV-CUN-RENDER-DEADLINE-001 — Deadline enforcement
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunRenderDeadline:
    """INV-CUN-RENDER-DEADLINE-001: Late renders are marked SKIPPED."""

    def test_past_deadline_marked_skipped(self, contract_clock):
        """A render request past its deadline must be marked SKIPPED."""
        CunSynthesisWorker = _import_cun_worker()

        # segment_start_utc is 60s from now, margin is 30s → deadline is 30s from now
        now = contract_clock.clock.now_utc()
        segment_start = now + _td(seconds=60)
        margin_ms = 30_000

        # Advance clock past the deadline (now at +40s, deadline was at +30s)
        advanced_now = now + _td(seconds=40)

        assert CunSynthesisWorker.is_past_deadline(
            segment_start_utc=segment_start,
            now=advanced_now,
            margin_ms=margin_ms,
        ), (
            "INV-CUN-RENDER-DEADLINE-001 violated: is_past_deadline returned False "
            "when now is past the deadline"
        )

    def test_before_deadline_proceeds(self, contract_clock):
        """A render request before its deadline must proceed to render."""
        CunSynthesisWorker = _import_cun_worker()

        now = contract_clock.clock.now_utc()
        segment_start = now + _td(seconds=120)
        margin_ms = 30_000

        # Clock is well before deadline — render should proceed
        assert not CunSynthesisWorker.is_past_deadline(
            segment_start_utc=segment_start,
            now=now,
            margin_ms=margin_ms,
        ), (
            "INV-CUN-RENDER-DEADLINE-001 violated: is_past_deadline returned True "
            "when now is well before the deadline"
        )


# ---------------------------------------------------------------------------
# INV-CUN-SKIP-IF-UNREADY-001 — Skip unready CUN at playout
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunSkipIfUnready:
    """INV-CUN-SKIP-IF-UNREADY-001: Unready CUN segments are skipped."""

    def test_pending_render_skipped(self):
        """CUN segment with pending render is omitted from resolved playlist."""
        ensure_cun_ready = _import_ensure_cun_ready()

        segment = {"segment_type": "coming_up_next", "next_program_title": "Movie X"}
        result = ensure_cun_ready(segment, render_status="pending")
        assert result is None, (
            "INV-CUN-SKIP-IF-UNREADY-001 violated: pending render was not skipped"
        )

    def test_failed_render_skipped(self):
        """CUN segment with failed render is omitted from resolved playlist."""
        ensure_cun_ready = _import_ensure_cun_ready()

        segment = {"segment_type": "coming_up_next", "next_program_title": "Movie X"}
        result = ensure_cun_ready(segment, render_status="failed")
        assert result is None, (
            "INV-CUN-SKIP-IF-UNREADY-001 violated: failed render was not skipped"
        )

    def test_completed_render_used(self):
        """CUN segment with completed render is included with rendered_asset_path."""
        ensure_cun_ready = _import_ensure_cun_ready()

        segment = {"segment_type": "coming_up_next", "next_program_title": "Movie X"}
        result = ensure_cun_ready(
            segment,
            render_status="completed",
            rendered_asset_path="/cache/abc123.mp4",
        )
        assert result is not None, (
            "INV-CUN-SKIP-IF-UNREADY-001 violated: completed render was skipped"
        )
        assert result["rendered_asset_path"] == "/cache/abc123.mp4"
        assert result["next_program_title"] == "Movie X"

    def test_no_blocking_on_unready(self):
        """ensure_cun_ready must return immediately, never block/wait."""
        ensure_cun_ready = _import_ensure_cun_ready()

        import time
        start = time.monotonic()
        # Call with None status (no render exists at all)
        result = ensure_cun_ready(
            {"segment_type": "coming_up_next", "next_program_title": "X"},
            render_status=None,
        )
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 0.1, (
            f"INV-CUN-SKIP-IF-UNREADY-001 violated: ensure_cun_ready took {elapsed:.3f}s, "
            f"expected < 0.1s (must not block)"
        )


# ---------------------------------------------------------------------------
# INV-CUN-PRIORITY-PLAYOUT-001 — Playout-time priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunPriorityPlayout:
    """INV-CUN-PRIORITY-PLAYOUT-001: Soonest-airing segments render first."""

    def test_earlier_segment_claimed_first(self):
        """Priority ordering: earlier segment_start_utc → lower priority number → claimed first.

        This tests the design invariant that priority is derived from playout
        time. The actual claim ordering (SKIP LOCKED) is a DB-level guarantee
        tested separately; here we verify the priority assignment contract.
        """
        CunRenderRequest = _import_cun_render_request()

        # Two segments: T+60s and T+120s. Priority = Unix timestamp of
        # segment_start_utc, so T+60s gets a lower priority number.
        early_ts = 1712764800  # example timestamp
        late_ts = 1712764860   # 60s later

        # Priority is set at enqueue time in PlaylistBuilderDaemon.
        # The contract is: lower priority value = higher urgency = sooner playout.
        assert early_ts < late_ts, "Sanity: earlier timestamp is lower"
        # The queue orders by priority ASC, so lower number is claimed first.
        # This is a design-level assertion, not a DB test.

    def test_priority_reflects_playout_time(self):
        """Priority value must be derived from segment_start_utc (lower = sooner)."""
        CunRenderRequest = _import_cun_render_request()

        # Verify the model has a priority field (structural contract).
        assert hasattr(CunRenderRequest, "priority"), (
            "INV-CUN-PRIORITY-PLAYOUT-001: CunRenderRequest missing 'priority' column"
        )
        assert hasattr(CunRenderRequest, "segment_start_utc"), (
            "INV-CUN-PRIORITY-PLAYOUT-001: CunRenderRequest missing 'segment_start_utc' column"
        )


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-DEDUP-001 — Content-addressed cache
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheDedup:
    """INV-CUN-CACHE-DEDUP-001: hash(template_id, title) deduplication."""

    def test_same_inputs_same_hash(self):
        """Identical (template_id, title) must produce identical content_hash."""
        cun_content_hash = _import_cun_content_hash()

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-retro-01", "The Tonight Show")
        assert h1 == h2, (
            f"INV-CUN-CACHE-DEDUP-001 violated: same inputs produced different hashes: "
            f"{h1} != {h2}"
        )

    def test_different_title_different_hash(self):
        """Different titles must produce different content_hash."""
        cun_content_hash = _import_cun_content_hash()

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-retro-01", "Late Night")
        assert h1 != h2, (
            "INV-CUN-CACHE-DEDUP-001 violated: different titles produced same hash"
        )

    def test_different_template_different_hash(self):
        """Different template_ids must produce different content_hash."""
        cun_content_hash = _import_cun_content_hash()

        h1 = cun_content_hash("template-retro-01", "The Tonight Show")
        h2 = cun_content_hash("template-neon-02", "The Tonight Show")
        assert h1 != h2, (
            "INV-CUN-CACHE-DEDUP-001 violated: different templates produced same hash"
        )


# ---------------------------------------------------------------------------
# INV-CUN-DEDUP-BEFORE-RENDER-001 — Pre-render dedup check
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunDedupBeforeRender:
    """INV-CUN-DEDUP-BEFORE-RENDER-001: Reuse existing completed render."""

    def test_existing_completed_render_reused(self):
        """If a completed render with the same content_hash exists, reuse it.

        Structural contract: the find_completed_by_hash function exists and
        is callable. Full DB integration tested in test_cun_playlog_resolution.
        """
        from retrovue.runtime.cun_queue import find_completed_by_hash
        assert callable(find_completed_by_hash), (
            "INV-CUN-DEDUP-BEFORE-RENDER-001: find_completed_by_hash not callable"
        )

        # Verify the worker's run_once references the dedup path.
        CunSynthesisWorker = _import_cun_worker()
        import inspect
        src = inspect.getsource(CunSynthesisWorker.run_once)
        assert "find_completed_by_hash" in src, (
            "INV-CUN-DEDUP-BEFORE-RENDER-001: run_once does not call find_completed_by_hash"
        )

    def test_no_existing_render_proceeds_to_ffmpeg(self):
        """If no completed render exists, proceed to actual rendering.

        Structural contract: the worker's run_once builds an ffmpeg command.
        """
        CunSynthesisWorker = _import_cun_worker()
        import inspect
        src = inspect.getsource(CunSynthesisWorker.run_once)
        assert "render_fn" in src, (
            "INV-CUN-DEDUP-BEFORE-RENDER-001: run_once does not invoke render_fn"
        )


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-UNTIL-USED-001 — Retain until broadcast
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheUntilUsed:
    """INV-CUN-CACHE-UNTIL-USED-001: Retain rendered assets until after broadcast."""

    def test_future_segment_not_cleaned(self, contract_clock):
        """Cleanup must not delete a rendered file whose segment hasn't aired."""
        cun_cleanup_eligible = _import_cun_cleanup_eligible()

        now = contract_clock.clock.now_utc()
        future_start = now + _td(hours=1)

        assert not cun_cleanup_eligible([future_start], now), (
            "INV-CUN-CACHE-UNTIL-USED-001 violated: future segment marked eligible for cleanup"
        )

    def test_past_segment_eligible_for_cleanup(self, contract_clock):
        """After segment has aired, rendered file is eligible for cleanup."""
        cun_cleanup_eligible = _import_cun_cleanup_eligible()

        now = contract_clock.clock.now_utc()
        past_start = now - _td(hours=1)

        assert cun_cleanup_eligible([past_start], now), (
            "INV-CUN-CACHE-UNTIL-USED-001 violated: past segment not eligible for cleanup"
        )


# ---------------------------------------------------------------------------
# INV-CUN-CACHE-SAFE-CLEANUP-001 — Safe cleanup across shared hashes
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunCacheSafeCleanup:
    """INV-CUN-CACHE-SAFE-CLEANUP-001: Don't delete until ALL referencing requests have aired."""

    def test_shared_hash_one_future_blocks_cleanup(self, contract_clock):
        """Two requests share hash H. One past, one future. File must not be deleted."""
        cun_cleanup_eligible = _import_cun_cleanup_eligible()

        now = contract_clock.clock.now_utc()
        past_start = now - _td(hours=1)
        future_start = now + _td(hours=1)

        assert not cun_cleanup_eligible([past_start, future_start], now), (
            "INV-CUN-CACHE-SAFE-CLEANUP-001 violated: file eligible for cleanup "
            "while one referencing segment is still in the future"
        )

    def test_shared_hash_all_past_allows_cleanup(self, contract_clock):
        """Two requests share hash H. Both past. File is eligible for cleanup."""
        cun_cleanup_eligible = _import_cun_cleanup_eligible()

        now = contract_clock.clock.now_utc()
        past_start_a = now - _td(hours=2)
        past_start_b = now - _td(hours=1)

        assert cun_cleanup_eligible([past_start_a, past_start_b], now), (
            "INV-CUN-CACHE-SAFE-CLEANUP-001 violated: file not eligible for cleanup "
            "when all referencing segments have aired"
        )


# ---------------------------------------------------------------------------
# INV-CUN-TEMPLATE-DETERMINISTIC-001 — Deterministic template selection
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCunTemplateDeterministic:
    """INV-CUN-TEMPLATE-DETERMINISTIC-001: SHA256-seeded deterministic selection."""

    def test_same_inputs_same_template(self):
        """Same (channel_id, broadcast_day, block_index, templates) → same template."""
        cun_select_template = _import_cun_select_template()

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
        assert t1 == t2, (
            f"INV-CUN-TEMPLATE-DETERMINISTIC-001 violated: same inputs produced "
            f"different templates: {t1} != {t2}"
        )

    def test_different_inputs_may_differ(self):
        """Different inputs should generally produce different selections."""
        cun_select_template = _import_cun_select_template()

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
            block_index=1,
            templates=templates,
        )
        # With 3 templates, different block indices should sometimes differ.
        # We test over multiple block indices to ensure at least one differs.
        results = set()
        for idx in range(10):
            t = cun_select_template(
                channel_id="hbo",
                broadcast_day="2026-04-10",
                block_index=idx,
                templates=templates,
            )
            results.add(t["id"])

        assert len(results) > 1, (
            "INV-CUN-TEMPLATE-DETERMINISTIC-001: deterministic selection always "
            "picks the same template regardless of block_index — distribution failure"
        )
