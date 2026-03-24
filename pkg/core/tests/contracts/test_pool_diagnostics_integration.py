"""Contract tests: Pool diagnostics integration at the scheduling boundary.

INV-POOL-RESOLUTION-VISIBILITY-001 integration:
  - Empty pools emit structured diagnostics via logger.warning
  - Non-empty pools do not emit diagnostics warnings
  - Diagnostics are attached to AssemblyResult.pool_diagnostics

These tests validate the scheduling-layer wiring, not the diagnostic
engine itself (that is covered by test_pool_resolution_visibility.py).
"""

from __future__ import annotations

import logging

import pytest

try:
    from retrovue.runtime.asset_resolver import (
        AssetMetadata,
        PoolDiagnostics,
        StubAssetResolver,
    )
    from retrovue.runtime.program_assembly import assemble_schedule_block
    from retrovue.runtime.program_definition import AssemblyFault
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


GRID_MINUTES = 30
SEED = 42


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _resolver_with_empty_presentation_pool() -> StubAssetResolver:
    """Resolver where content pool has assets but a presentation pool is empty."""
    resolver = StubAssetResolver()

    # Content — valid movies
    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="Taken",
        rating="PG-13", file_uri="/mnt/movies/taken.mkv",
    ))

    # Presentation pool that will match nothing
    # (no assets carry "nonexistent_channel" tag)
    resolver.register_pools({
        "movies": {"match": {"type": "movie"}},
        "empty_intros": {
            "match": {"type": "bumper", "tags": ["nonexistent_channel", "intros"]},
        },
    })

    return resolver


def _resolver_with_all_pools_populated() -> StubAssetResolver:
    """Resolver where all pools have matching assets."""
    resolver = StubAssetResolver()

    resolver.add("movie-001", AssetMetadata(
        type="movie", duration_sec=5400, title="Taken",
        rating="PG-13", file_uri="/mnt/movies/taken.mkv",
    ))
    resolver.add("intro-001", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO Intro",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/bumpers/intro.mp4",
    ))
    resolver.add("station-id-001", AssetMetadata(
        type="bumper", duration_sec=10, title="Station ID",
        tags=("hbo", "station_ids"),
        file_uri="/mnt/bumpers/station_id.mp4",
    ))

    resolver.register_pools({
        "movies": {"match": {"type": "movie"}},
        "intros": {
            "match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]},
        },
        "station_ids": {
            "match": {"type": "bumper", "tags": ["hbo", "station_ids"]},
        },
    })

    return resolver


def _resolver_with_empty_content_pool() -> StubAssetResolver:
    """Resolver where the content pool matches zero assets."""
    resolver = StubAssetResolver()

    # Only bumpers — no movies
    resolver.add("intro-001", AssetMetadata(
        type="bumper", duration_sec=30, title="HBO Intro",
        tags=("hbo", "presentation", "intros"),
        file_uri="/mnt/bumpers/intro.mp4",
    ))

    resolver.register_pools({
        "movies": {"match": {"type": "movie"}},
        "intros": {
            "match": {"type": "bumper", "tags": ["hbo", "presentation", "intros"]},
        },
    })

    return resolver


# ===========================================================================
# Step 1 — Empty presentation pool emits diagnostics
# ===========================================================================


class TestEmptyPoolEmitsDiagnostics:
    """When a presentation pool resolves to zero assets, structured
    diagnostics must be logged and attached to the result.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_empty_presentation_pool_logs_warning(self, caplog):
        """An empty presentation pool must emit a logger.warning with
        the INV-POOL-RESOLUTION-VISIBILITY-001 event.
        """
        resolver = _resolver_with_empty_presentation_pool()

        with caplog.at_level(logging.WARNING, logger="retrovue.runtime.program_assembly"):
            results = assemble_schedule_block(
                program_ref="hbo_movies",
                program_def={
                    "pool": "movies",
                    "grid_blocks": 4,
                    "fill_mode": "single",
                    "presentation": [{"pool": "empty_intros"}],
                },
                pool_name="movies",
                slots=4,
                progression="random",
                grid_minutes=GRID_MINUTES,
                resolver=resolver,
                bleed=True,
                seed=SEED,
            )

        # Must have logged the visibility warning
        visibility_logs = [
            r for r in caplog.records
            if "INV-POOL-RESOLUTION-VISIBILITY-001" in r.message
        ]
        assert len(visibility_logs) >= 1, (
            f"Expected INV-POOL-RESOLUTION-VISIBILITY-001 log, got: "
            f"{[r.message for r in caplog.records]}"
        )

        # Log must name the pool
        assert "empty_intros" in visibility_logs[0].message

        # Log must include diagnostic counts
        assert "total_considered=" in visibility_logs[0].message
        assert "matched=0" in visibility_logs[0].message

    # Tier: 2 | Scheduling logic invariant
    def test_empty_presentation_pool_diagnostics_on_result(self):
        """Diagnostics for the empty pool must be attached to
        AssemblyResult.pool_diagnostics.
        """
        resolver = _resolver_with_empty_presentation_pool()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "empty_intros"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        assert len(results) >= 1
        result = results[0]
        assert "empty_intros" in result.pool_diagnostics, (
            f"Expected 'empty_intros' in pool_diagnostics, "
            f"got keys: {list(result.pool_diagnostics.keys())}"
        )

        diag = result.pool_diagnostics["empty_intros"]
        assert isinstance(diag, PoolDiagnostics)
        assert diag.matched == 0
        assert diag.total_considered > 0

    # Tier: 2 | Scheduling logic invariant
    def test_empty_postroll_pool_diagnostics_on_result(self):
        """Empty postroll pool diagnostics attached to result."""
        resolver = _resolver_with_empty_presentation_pool()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation_postroll": [{"pool": "empty_intros"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        result = results[0]
        assert "empty_intros" in result.pool_diagnostics
        assert result.pool_diagnostics["empty_intros"].matched == 0

    # Tier: 2 | Scheduling logic invariant
    def test_empty_content_pool_diagnostics_before_fault(self):
        """When the content pool is empty, diagnostics are emitted before
        AssemblyFault is raised.
        """
        resolver = _resolver_with_empty_content_pool()

        with pytest.raises(AssemblyFault, match="INV-PROGRAM-POOL-002"):
            assemble_schedule_block(
                program_ref="hbo_movies",
                program_def={
                    "pool": "movies",
                    "grid_blocks": 4,
                    "fill_mode": "single",
                },
                pool_name="movies",
                slots=4,
                progression="random",
                grid_minutes=GRID_MINUTES,
                resolver=resolver,
                bleed=True,
                seed=SEED,
            )

    # Tier: 2 | Scheduling logic invariant
    def test_empty_content_pool_logs_diagnostics(self, caplog):
        """Content pool empty → diagnostics logged before exception."""
        resolver = _resolver_with_empty_content_pool()

        with caplog.at_level(logging.WARNING, logger="retrovue.runtime.program_assembly"):
            with pytest.raises(AssemblyFault):
                assemble_schedule_block(
                    program_ref="hbo_movies",
                    program_def={
                        "pool": "movies",
                        "grid_blocks": 4,
                        "fill_mode": "single",
                    },
                    pool_name="movies",
                    slots=4,
                    progression="random",
                    grid_minutes=GRID_MINUTES,
                    resolver=resolver,
                    bleed=True,
                    seed=SEED,
                )

        visibility_logs = [
            r for r in caplog.records
            if "INV-POOL-RESOLUTION-VISIBILITY-001" in r.message
        ]
        assert len(visibility_logs) >= 1, (
            "Empty content pool must emit diagnostics before raising"
        )
        assert "movies" in visibility_logs[0].message


# ===========================================================================
# Step 2 — Non-empty pool does not emit warning
# ===========================================================================


class TestNonEmptyPoolNoWarning:
    """When all pools resolve successfully, no diagnostics warnings are emitted."""

    # Tier: 2 | Scheduling logic invariant
    def test_populated_pools_no_visibility_warning(self, caplog):
        """All pools populated → no INV-POOL-RESOLUTION-VISIBILITY-001 log."""
        resolver = _resolver_with_all_pools_populated()

        with caplog.at_level(logging.WARNING, logger="retrovue.runtime.program_assembly"):
            results = assemble_schedule_block(
                program_ref="hbo_movies",
                program_def={
                    "pool": "movies",
                    "grid_blocks": 4,
                    "fill_mode": "single",
                    "presentation": [{"pool": "intros"}],
                    "presentation_postroll": [{"pool": "station_ids"}],
                },
                pool_name="movies",
                slots=4,
                progression="random",
                grid_minutes=GRID_MINUTES,
                resolver=resolver,
                bleed=True,
                seed=SEED,
            )

        visibility_logs = [
            r for r in caplog.records
            if "INV-POOL-RESOLUTION-VISIBILITY-001" in r.message
        ]
        assert len(visibility_logs) == 0, (
            f"No diagnostics warning expected for populated pools, "
            f"got: {[r.message for r in visibility_logs]}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_populated_pools_empty_diagnostics_dict(self):
        """All pools populated → pool_diagnostics dict is empty."""
        resolver = _resolver_with_all_pools_populated()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "intros"}],
                "presentation_postroll": [{"pool": "station_ids"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        result = results[0]
        assert result.pool_diagnostics == {}, (
            f"Expected empty pool_diagnostics for populated pools, "
            f"got: {result.pool_diagnostics}"
        )


# ===========================================================================
# Step 3 — Diagnostics attached to block
# ===========================================================================


class TestDiagnosticsAttachedToBlock:
    """Pool diagnostics must be accessible on the AssemblyResult."""

    # Tier: 1 | Structural invariant
    def test_pool_diagnostics_field_exists(self):
        """AssemblyResult must have a pool_diagnostics field."""
        resolver = _resolver_with_all_pools_populated()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        assert hasattr(results[0], "pool_diagnostics"), (
            "AssemblyResult must have pool_diagnostics field"
        )
        assert isinstance(results[0].pool_diagnostics, dict)

    # Tier: 2 | Scheduling logic invariant
    def test_diagnostics_contains_pool_diagnostics_type(self):
        """Attached diagnostics must be PoolDiagnostics instances."""
        resolver = _resolver_with_empty_presentation_pool()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "empty_intros"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        for pool_name, diag in results[0].pool_diagnostics.items():
            assert isinstance(diag, PoolDiagnostics), (
                f"pool_diagnostics['{pool_name}'] must be PoolDiagnostics, "
                f"got {type(diag)}"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_diagnostics_exclusion_reasons_populated(self):
        """Attached diagnostics for empty pool must have exclusion reasons."""
        resolver = _resolver_with_empty_presentation_pool()

        # Add some bumpers that will fail the tag filter
        resolver.add("wrong-bumper", AssetMetadata(
            type="bumper", duration_sec=15, title="Wrong Tags",
            tags=("other_channel",),
            file_uri="/mnt/bumpers/wrong.mp4",
        ))

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "empty_intros"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        diag = results[0].pool_diagnostics["empty_intros"]
        assert diag.total_considered > 0
        assert len(diag.exclusion_reasons) > 0, (
            "Diagnostics must explain why assets were excluded"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_assembly_still_succeeds_with_empty_presentation_pool(self):
        """Empty presentation pool degrades gracefully — assembly still
        produces a valid result with content.
        """
        resolver = _resolver_with_empty_presentation_pool()

        results = assemble_schedule_block(
            program_ref="hbo_movies",
            program_def={
                "pool": "movies",
                "grid_blocks": 4,
                "fill_mode": "single",
                "presentation": [{"pool": "empty_intros"}],
            },
            pool_name="movies",
            slots=4,
            progression="random",
            grid_minutes=GRID_MINUTES,
            resolver=resolver,
            bleed=True,
            seed=SEED,
        )

        assert len(results) >= 1
        content_segs = [
            s for s in results[0].segments if s.segment_type == "content"
        ]
        assert len(content_segs) >= 1, (
            "Assembly must still produce content even with empty presentation pool"
        )
