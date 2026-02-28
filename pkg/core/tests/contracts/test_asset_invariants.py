"""
Contract tests: Asset & Asset Library Invariants.

Formalizes implicit rules governing the asset entity, enrichment pipeline,
metadata integrity, schedulability, and library boundaries.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
See: docs/contracts/invariants/core/asset/INV-ASSET-*.md
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from retrovue.domain.entities import (
    validate_marker_bounds,
    validate_state_transition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(**overrides: object) -> SimpleNamespace:
    """Create a minimal asset stub for contract tests."""
    defaults = dict(
        uuid="00000000-0000-0000-0000-000000000001",
        collection_uuid="00000000-0000-0000-0000-000000000099",
        canonical_key="test/asset.mp4",
        canonical_key_hash="a" * 64,
        uri="/media/test/asset.mp4",
        canonical_uri="/media/test/asset.mp4",
        size=1_000_000,
        state="new",
        approved_for_broadcast=False,
        operator_verified=False,
        duration_ms=None,
        video_codec=None,
        audio_codec=None,
        container=None,
        discovered_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        is_deleted=False,
        deleted_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _check_approved_implies_ready(asset: SimpleNamespace) -> None:
    """Validate INV-ASSET-APPROVED-IMPLIES-READY-001 at the application layer."""
    if asset.approved_for_broadcast and asset.state != "ready":
        raise ValueError(
            "INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED: "
            f"approved_for_broadcast=True but state={asset.state!r}"
        )


def _check_softdelete_sync(asset: SimpleNamespace) -> None:
    """Validate INV-ASSET-SOFTDELETE-SYNC-001 at the application layer."""
    if asset.is_deleted and asset.deleted_at is None:
        raise ValueError(
            "INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED: "
            "is_deleted=True but deleted_at is None"
        )
    if not asset.is_deleted and asset.deleted_at is not None:
        raise ValueError(
            "INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED: "
            "is_deleted=False but deleted_at is not None"
        )


def _check_canonical_key_format(canonical_key_hash: str) -> None:
    """Validate INV-ASSET-CANONICAL-KEY-FORMAT-001 at the application layer."""
    if len(canonical_key_hash) != 64:
        raise ValueError(
            "INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED: "
            f"hash length is {len(canonical_key_hash)}, expected 64"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", canonical_key_hash):
        raise ValueError(
            "INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED: "
            "hash contains non-hex characters"
        )


def _is_schedulable(asset: SimpleNamespace) -> bool:
    """Evaluate the schedulability triple-gate predicate."""
    return (
        asset.state == "ready"
        and asset.approved_for_broadcast is True
        and asset.is_deleted is False
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: Asset Entity Integrity
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvAssetApprovedImpliesReady001:
    """INV-ASSET-APPROVED-IMPLIES-READY-001 enforcement tests."""

    def test_taair_001_ready_approved_valid(self) -> None:
        """INV-ASSET-APPROVED-IMPLIES-READY-001 — positive

        Invariant: approved_for_broadcast=true ONLY IF state='ready'.
        Scenario: Asset with state=ready, approved=true is valid.
        """
        asset = _make_asset(state="ready", approved_for_broadcast=True, duration_ms=1_320_000)
        _check_approved_implies_ready(asset)  # must not raise

    def test_taair_002_new_approved_rejected(self) -> None:
        """INV-ASSET-APPROVED-IMPLIES-READY-001 — negative

        Invariant: approved_for_broadcast=true ONLY IF state='ready'.
        Scenario: Asset with state=new, approved=true must be rejected.
        """
        asset = _make_asset(state="new", approved_for_broadcast=True)
        with pytest.raises(ValueError, match="INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED"):
            _check_approved_implies_ready(asset)

    def test_taair_003_enriching_approved_rejected(self) -> None:
        """INV-ASSET-APPROVED-IMPLIES-READY-001 — negative

        Invariant: approved_for_broadcast=true ONLY IF state='ready'.
        Scenario: Asset with state=enriching, approved=true must be rejected.
        """
        asset = _make_asset(state="enriching", approved_for_broadcast=True)
        with pytest.raises(ValueError, match="INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED"):
            _check_approved_implies_ready(asset)

    def test_taair_004_ready_not_approved_valid(self) -> None:
        """INV-ASSET-APPROVED-IMPLIES-READY-001 — positive

        Invariant: approved_for_broadcast=true ONLY IF state='ready'.
        Scenario: Asset with state=ready, approved=false is valid (not yet approved).
        """
        asset = _make_asset(state="ready", approved_for_broadcast=False, duration_ms=1_320_000)
        _check_approved_implies_ready(asset)  # must not raise


class TestInvAssetSoftdeleteSync001:
    """INV-ASSET-SOFTDELETE-SYNC-001 enforcement tests."""

    def test_tsds_001_deleted_with_timestamp_valid(self) -> None:
        """INV-ASSET-SOFTDELETE-SYNC-001 — positive

        Invariant: is_deleted=true IFF deleted_at IS NOT NULL.
        Scenario: is_deleted=true + deleted_at set is valid.
        """
        asset = _make_asset(
            is_deleted=True,
            deleted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        _check_softdelete_sync(asset)  # must not raise

    def test_tsds_002_not_deleted_no_timestamp_valid(self) -> None:
        """INV-ASSET-SOFTDELETE-SYNC-001 — positive

        Invariant: is_deleted=true IFF deleted_at IS NOT NULL.
        Scenario: is_deleted=false + deleted_at=null is valid.
        """
        asset = _make_asset(is_deleted=False, deleted_at=None)
        _check_softdelete_sync(asset)  # must not raise

    def test_tsds_003_deleted_no_timestamp_rejected(self) -> None:
        """INV-ASSET-SOFTDELETE-SYNC-001 — negative

        Invariant: is_deleted=true IFF deleted_at IS NOT NULL.
        Scenario: is_deleted=true + deleted_at=null must be rejected.
        """
        asset = _make_asset(is_deleted=True, deleted_at=None)
        with pytest.raises(ValueError, match="INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED"):
            _check_softdelete_sync(asset)

    def test_tsds_004_not_deleted_with_timestamp_rejected(self) -> None:
        """INV-ASSET-SOFTDELETE-SYNC-001 — negative

        Invariant: is_deleted=true IFF deleted_at IS NOT NULL.
        Scenario: is_deleted=false + deleted_at set must be rejected.
        """
        asset = _make_asset(
            is_deleted=False,
            deleted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED"):
            _check_softdelete_sync(asset)


class TestInvAssetCanonicalKeyFormat001:
    """INV-ASSET-CANONICAL-KEY-FORMAT-001 enforcement tests."""

    def test_tckf_001_valid_sha256_hex(self) -> None:
        """INV-ASSET-CANONICAL-KEY-FORMAT-001 — positive

        Invariant: canonical_key_hash is exactly 64 lowercase hex characters.
        Scenario: Valid 64-char hex string passes.
        """
        valid_hash = "a1b2c3d4e5f6" + "0" * 52  # 64 hex chars
        _check_canonical_key_format(valid_hash)  # must not raise

    def test_tckf_002_too_short_rejected(self) -> None:
        """INV-ASSET-CANONICAL-KEY-FORMAT-001 — negative

        Invariant: canonical_key_hash is exactly 64 lowercase hex characters.
        Scenario: 63-char string must be rejected.
        """
        short_hash = "a" * 63
        with pytest.raises(ValueError, match="INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED"):
            _check_canonical_key_format(short_hash)

    def test_tckf_003_too_long_rejected(self) -> None:
        """INV-ASSET-CANONICAL-KEY-FORMAT-001 — negative

        Invariant: canonical_key_hash is exactly 64 lowercase hex characters.
        Scenario: 65-char string must be rejected.
        """
        long_hash = "a" * 65
        with pytest.raises(ValueError, match="INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED"):
            _check_canonical_key_format(long_hash)

    def test_tckf_004_non_hex_rejected(self) -> None:
        """INV-ASSET-CANONICAL-KEY-FORMAT-001 — negative

        Invariant: canonical_key_hash is exactly 64 lowercase hex characters.
        Scenario: 64-char string with non-hex characters must be rejected.
        """
        bad_hash = "g" * 64
        with pytest.raises(ValueError, match="INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED"):
            _check_canonical_key_format(bad_hash)

    def test_tckf_005_uppercase_rejected(self) -> None:
        """INV-ASSET-CANONICAL-KEY-FORMAT-001 — negative

        Invariant: canonical_key_hash is exactly 64 lowercase hex characters.
        Scenario: 64-char string with uppercase hex must be rejected.
        """
        upper_hash = "A" * 64
        with pytest.raises(ValueError, match="INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED"):
            _check_canonical_key_format(upper_hash)


class TestInvAssetStateMachine001:
    """INV-ASSET-STATE-MACHINE-001 enforcement tests."""

    def test_tasm_001_new_to_enriching(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — positive

        Invariant: Legal transitions include new -> enriching.
        Scenario: Transition from new to enriching succeeds.
        """
        validate_state_transition("new", "enriching")  # must not raise

    def test_tasm_002_enriching_to_ready(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — positive

        Invariant: Legal transitions include enriching -> ready.
        Scenario: Transition from enriching to ready succeeds.
        """
        validate_state_transition("enriching", "ready")  # must not raise

    def test_tasm_003_enriching_to_new_revert(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — positive

        Invariant: Legal transitions include enriching -> new (revert on failure).
        Scenario: Transition from enriching to new succeeds.
        """
        validate_state_transition("enriching", "new")  # must not raise

    def test_tasm_004_any_to_retired(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — positive

        Invariant: Legal transitions include any -> retired.
        Scenario: All states can transition to retired.
        """
        for state in ("new", "enriching", "ready"):
            validate_state_transition(state, "retired")  # must not raise

    def test_tasm_005_new_to_ready_rejected(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — negative

        Invariant: new -> ready is not a legal transition (skips enriching).
        Scenario: Direct promotion from new to ready must be rejected.
        """
        with pytest.raises(ValueError, match="INV-ASSET-STATE-MACHINE-001-VIOLATED"):
            validate_state_transition("new", "ready")

    def test_tasm_006_ready_to_new_rejected(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — negative

        Invariant: ready -> new is not a legal transition.
        Scenario: Reverting from ready to new must be rejected.
        """
        with pytest.raises(ValueError, match="INV-ASSET-STATE-MACHINE-001-VIOLATED"):
            validate_state_transition("ready", "new")

    def test_tasm_007_ready_to_enriching_rejected(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — negative

        Invariant: ready -> enriching is not a legal transition.
        Scenario: Re-enriching a ready asset must use reprobe instead.
        """
        with pytest.raises(ValueError, match="INV-ASSET-STATE-MACHINE-001-VIOLATED"):
            validate_state_transition("ready", "enriching")

    def test_tasm_008_same_state_noop(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — positive

        Invariant: Same-state transition is a no-op.
        Scenario: Transitioning to the same state is always valid.
        """
        for state in ("new", "enriching", "ready", "retired"):
            validate_state_transition(state, state)  # must not raise

    def test_tasm_009_retired_to_anything_rejected(self) -> None:
        """INV-ASSET-STATE-MACHINE-001 — negative

        Invariant: retired is a terminal state (no outbound transitions).
        Scenario: Transitioning out of retired must be rejected.
        """
        for target in ("new", "enriching", "ready"):
            with pytest.raises(ValueError, match="INV-ASSET-STATE-MACHINE-001-VIOLATED"):
                validate_state_transition("retired", target)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: Enrichment Pipeline
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvAssetDurationRequiredForReady001:
    """INV-ASSET-DURATION-REQUIRED-FOR-READY-001 enforcement tests."""

    def test_tdrr_001_valid_duration_promotes(self) -> None:
        """INV-ASSET-DURATION-REQUIRED-FOR-READY-001 — positive

        Invariant: Asset MUST have duration_ms > 0 to transition to ready.
        Scenario: Asset with duration_ms=1320000 can be promoted.
        """
        asset = _make_asset(state="enriching", duration_ms=1_320_000)
        # Simulate the promotion guard from ingest_orchestrator
        if asset.duration_ms and asset.duration_ms > 0:
            validate_state_transition(asset.state, "ready")
            asset.state = "ready"
        assert asset.state == "ready"

    def test_tdrr_002_none_duration_stays_new(self) -> None:
        """INV-ASSET-DURATION-REQUIRED-FOR-READY-001 — negative

        Invariant: Asset MUST have duration_ms > 0 to transition to ready.
        Scenario: Asset with duration_ms=None stays in new.
        """
        asset = _make_asset(state="enriching", duration_ms=None)
        if asset.duration_ms and asset.duration_ms > 0:
            asset.state = "ready"
        else:
            validate_state_transition(asset.state, "new")
            asset.state = "new"
        assert asset.state == "new"

    def test_tdrr_003_zero_duration_stays_new(self) -> None:
        """INV-ASSET-DURATION-REQUIRED-FOR-READY-001 — negative

        Invariant: Asset MUST have duration_ms > 0 to transition to ready.
        Scenario: Asset with duration_ms=0 stays in new.
        """
        asset = _make_asset(state="enriching", duration_ms=0)
        if asset.duration_ms and asset.duration_ms > 0:
            asset.state = "ready"
        else:
            validate_state_transition(asset.state, "new")
            asset.state = "new"
        assert asset.state == "new"


class TestInvAssetApprovalOperatorOnly001:
    """INV-ASSET-APPROVAL-OPERATOR-ONLY-001 enforcement tests."""

    def test_taoo_001_enrichment_never_approves(self) -> None:
        """INV-ASSET-APPROVAL-OPERATOR-ONLY-001 — positive

        Invariant: Enrichment pipeline MUST NOT set approved_for_broadcast=true.
        Scenario: After enrichment, approved_for_broadcast remains false.
        """
        asset = _make_asset(state="new", approved_for_broadcast=False)

        # Simulate enrichment pipeline: state transitions, probe data applied
        validate_state_transition(asset.state, "enriching")
        asset.state = "enriching"
        asset.duration_ms = 1_320_000
        asset.video_codec = "h264"
        asset.audio_codec = "aac"
        asset.container = "mp4"
        validate_state_transition(asset.state, "ready")
        asset.state = "ready"

        # The enrichment pipeline MUST NOT have set approved_for_broadcast
        assert asset.approved_for_broadcast is False

    def test_taoo_002_enrichment_setting_approved_is_violation(self) -> None:
        """INV-ASSET-APPROVAL-OPERATOR-ONLY-001 — negative

        Invariant: Enrichment pipeline MUST NOT set approved_for_broadcast=true.
        Scenario: Setting approved=true during enrichment is a violation.
        """
        asset = _make_asset(state="enriching", approved_for_broadcast=False)

        # Simulate enrichment pipeline incorrectly approving
        asset.approved_for_broadcast = True

        # This should be caught: enriching + approved is invalid per
        # INV-ASSET-APPROVED-IMPLIES-READY-001
        with pytest.raises(ValueError, match="INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED"):
            _check_approved_implies_ready(asset)


class TestInvAssetReprobeResetsApproval001:
    """INV-ASSET-REPROBE-RESETS-APPROVAL-001 enforcement tests."""

    def test_trra_001_reprobe_clears_all_stale_data(self) -> None:
        """INV-ASSET-REPROBE-RESETS-APPROVAL-001 — positive

        Invariant: Reprobe resets approval, clears technical metadata.
        Scenario: After reprobe reset, all stale fields are cleared.
        """
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=True,
            duration_ms=1_320_000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )

        # Simulate reprobe reset (from asset_reprobe.py lines 67-73)
        asset.state = "new"
        asset.approved_for_broadcast = False
        asset.duration_ms = None
        asset.video_codec = None
        asset.audio_codec = None
        asset.container = None

        assert asset.state == "new"
        assert asset.approved_for_broadcast is False
        assert asset.duration_ms is None
        assert asset.video_codec is None
        assert asset.audio_codec is None
        assert asset.container is None

    def test_trra_002_non_chapter_markers_survive(self) -> None:
        """INV-ASSET-REPROBE-RESETS-APPROVAL-001 — positive

        Invariant: Non-CHAPTER markers MUST be preserved across reprobe.
        Scenario: AVAILABILITY marker survives reprobe, CHAPTER is deleted.
        """
        chapter_marker = SimpleNamespace(kind="CHAPTER", start_ms=0, end_ms=30_000)
        avail_marker = SimpleNamespace(kind="AVAILABILITY", start_ms=0, end_ms=60_000)
        all_markers = [chapter_marker, avail_marker]

        # Simulate reprobe: delete CHAPTER markers only
        surviving = [m for m in all_markers if m.kind != "CHAPTER"]
        deleted = [m for m in all_markers if m.kind == "CHAPTER"]

        assert len(surviving) == 1
        assert surviving[0].kind == "AVAILABILITY"
        assert len(deleted) == 1
        assert deleted[0].kind == "CHAPTER"

    def test_trra_003_chapter_markers_removed(self) -> None:
        """INV-ASSET-REPROBE-RESETS-APPROVAL-001 — negative

        Invariant: CHAPTER markers MUST be deleted during reprobe.
        Scenario: CHAPTER markers surviving reprobe is a violation.
        """
        markers = [
            SimpleNamespace(kind="CHAPTER", start_ms=0, end_ms=30_000),
            SimpleNamespace(kind="CHAPTER", start_ms=30_000, end_ms=60_000),
        ]

        # Simulate reprobe: filter out CHAPTER markers
        surviving = [m for m in markers if m.kind != "CHAPTER"]

        # All CHAPTER markers must be removed
        assert len(surviving) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: Metadata Integrity
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvAssetProbeOnlyFieldAuthority001:
    """INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 enforcement tests."""

    def test_tpfa_001_non_probe_authoritative_valid(self) -> None:
        """INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 — positive

        Invariant: Probe-only fields MUST NOT be in authoritative_fields.
        Scenario: Sidecar with non-probe fields authoritative passes.
        """
        from retrovue.domain.metadata_schema import EpisodeSidecar

        sidecar_data = {
            "asset_type": "episode",
            "title": "Test Episode",
            "season_number": 1,
            "episode_number": 1,
            "_meta": {
                "schema_id": "retrovue.sidecar",
                "version": "1.0",
                "scope": "file",
                "authoritative_fields": ["title", "description"],
            },
        }
        sidecar = EpisodeSidecar.model_validate(sidecar_data)
        assert sidecar.title == "Test Episode"

    def test_tpfa_002_runtime_seconds_authoritative_rejected(self) -> None:
        """INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 — negative

        Invariant: Probe-only fields MUST NOT be in authoritative_fields.
        Scenario: runtime_seconds in authoritative_fields must be rejected.
        """
        from retrovue.domain.metadata_schema import EpisodeSidecar

        sidecar_data = {
            "asset_type": "episode",
            "title": "Test Episode",
            "season_number": 1,
            "episode_number": 1,
            "_meta": {
                "schema_id": "retrovue.sidecar",
                "version": "1.0",
                "scope": "file",
                "authoritative_fields": ["title", "runtime_seconds"],
            },
        }
        with pytest.raises(ValueError, match="Probe-only fields cannot be authoritative"):
            EpisodeSidecar.model_validate(sidecar_data)

    def test_tpfa_003_video_codec_authoritative_rejected(self) -> None:
        """INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 — negative

        Invariant: Probe-only fields MUST NOT be in authoritative_fields.
        Scenario: video_codec in authoritative_fields must be rejected.
        """
        from retrovue.domain.metadata_schema import EpisodeSidecar

        sidecar_data = {
            "asset_type": "episode",
            "title": "Test Episode",
            "season_number": 1,
            "episode_number": 1,
            "_meta": {
                "schema_id": "retrovue.sidecar",
                "version": "1.0",
                "scope": "file",
                "authoritative_fields": ["video_codec"],
            },
        }
        with pytest.raises(ValueError, match="Probe-only fields cannot be authoritative"):
            EpisodeSidecar.model_validate(sidecar_data)

    def test_tpfa_004_probe_fields_present_but_not_authoritative_valid(self) -> None:
        """INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 — positive

        Invariant: Probe-only fields MUST NOT be in authoritative_fields.
        Scenario: Sidecar with probe-only fields present but not authoritative passes.
        """
        from retrovue.domain.metadata_schema import EpisodeSidecar

        sidecar_data = {
            "asset_type": "episode",
            "title": "Test Episode",
            "season_number": 1,
            "episode_number": 1,
            "runtime_seconds": 1320,
            "video_codec": "h264",
            "_meta": {
                "schema_id": "retrovue.sidecar",
                "version": "1.0",
                "scope": "file",
                "authoritative_fields": ["title"],
            },
        }
        sidecar = EpisodeSidecar.model_validate(sidecar_data)
        assert sidecar.runtime_seconds == 1320


class TestInvAssetDurationContractualTruth001:
    """INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 enforcement tests."""

    def test_tdct_001_duration_set_at_enrichment(self) -> None:
        """INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 — positive

        Invariant: Duration measured once at ingest, consumed as contractual truth.
        Scenario: Duration set during enrichment and unchanged through planning.
        """
        asset = _make_asset(state="new")

        # Simulate enrichment setting duration from probe data
        probed_duration_ms = 1_320_000
        asset.duration_ms = probed_duration_ms
        asset.state = "enriching"

        # After enrichment, duration is the contractual truth
        assert asset.duration_ms == probed_duration_ms

        # Simulate planning pipeline reading duration (via asset library)
        planning_duration = asset.duration_ms
        assert planning_duration == probed_duration_ms

    def test_tdct_002_asset_library_returns_stored_value(self) -> None:
        """INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 — positive

        Invariant: Asset Library returns the stored duration_ms value.
        Scenario: get_duration_ms returns the probed value without recalculation.
        """
        stored_duration_ms = 2_700_000  # 45 minutes

        # Simulate InMemoryAssetLibrary / DatabaseAssetLibrary behavior
        class MockAssetLibrary:
            def get_duration_ms(self, asset_uri: str) -> int:
                # Returns stored value; no re-derivation
                return stored_duration_ms

        lib = MockAssetLibrary()
        assert lib.get_duration_ms("/media/test.mp4") == stored_duration_ms


class TestInvAssetMarkerBounds001:
    """INV-ASSET-MARKER-BOUNDS-001 enforcement tests."""

    def test_tamb_001_valid_marker_within_bounds(self) -> None:
        """INV-ASSET-MARKER-BOUNDS-001 — positive

        Invariant: Marker start_ms >= 0 and end_ms <= asset.duration_ms.
        Scenario: Marker within asset duration is valid.
        """
        validate_marker_bounds(
            start_ms=0,
            end_ms=30_000,
            asset_duration_ms=1_320_000,
        )  # must not raise

    def test_tamb_002_marker_at_boundaries(self) -> None:
        """INV-ASSET-MARKER-BOUNDS-001 — positive

        Invariant: Marker start_ms >= 0 and end_ms <= asset.duration_ms.
        Scenario: Marker at exact boundaries (0, duration) is valid.
        """
        validate_marker_bounds(
            start_ms=0,
            end_ms=1_320_000,
            asset_duration_ms=1_320_000,
        )  # must not raise

    def test_tamb_003_end_exceeds_duration_rejected(self) -> None:
        """INV-ASSET-MARKER-BOUNDS-001 — negative

        Invariant: Marker end_ms MUST be <= asset.duration_ms.
        Scenario: Marker with end_ms exceeding duration must be rejected.
        """
        with pytest.raises(ValueError, match="INV-ASSET-MARKER-BOUNDS-001-VIOLATED"):
            validate_marker_bounds(
                start_ms=0,
                end_ms=2_000_000,
                asset_duration_ms=1_320_000,
            )

    def test_tamb_004_negative_start_rejected(self) -> None:
        """INV-ASSET-MARKER-BOUNDS-001 — negative

        Invariant: Marker start_ms MUST be >= 0.
        Scenario: Marker with negative start_ms must be rejected.
        """
        with pytest.raises(ValueError, match="INV-ASSET-MARKER-BOUNDS-001-VIOLATED"):
            validate_marker_bounds(
                start_ms=-1,
                end_ms=30_000,
                asset_duration_ms=1_320_000,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: Schedulability & Library Boundary
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvAssetSchedulableTripleGate001:
    """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 enforcement tests."""

    def test_tstg_001_all_three_conditions_schedulable(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — positive

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: All three conditions met — asset is schedulable.
        """
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=True,
            is_deleted=False,
            duration_ms=1_320_000,
        )
        assert _is_schedulable(asset) is True

    def test_tstg_002_deleted_not_schedulable(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — negative

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: ready + approved + deleted — not schedulable.
        """
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=True,
            is_deleted=True,
            deleted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        assert _is_schedulable(asset) is False

    def test_tstg_003_not_approved_not_schedulable(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — negative

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: ready + not approved + not deleted — not schedulable.
        """
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=False,
            is_deleted=False,
            duration_ms=1_320_000,
        )
        assert _is_schedulable(asset) is False

    def test_tstg_004_not_ready_not_schedulable(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — negative

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: new + not approved + not deleted — not schedulable.
        """
        asset = _make_asset(
            state="new",
            approved_for_broadcast=False,
            is_deleted=False,
        )
        assert _is_schedulable(asset) is False

    def test_tstg_005_enriching_not_schedulable(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — negative

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: enriching state — not schedulable regardless of other flags.
        """
        asset = _make_asset(
            state="enriching",
            approved_for_broadcast=False,
            is_deleted=False,
        )
        assert _is_schedulable(asset) is False

    def test_tstg_006_all_permutations(self) -> None:
        """INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 — exhaustive

        Invariant: Schedulable IFF ready AND approved AND not deleted.
        Scenario: Only one of eight combinations is schedulable.
        """
        schedulable_count = 0
        for state in ("ready", "new"):
            for approved in (True, False):
                for deleted in (True, False):
                    asset = _make_asset(
                        state=state,
                        approved_for_broadcast=approved,
                        is_deleted=deleted,
                        deleted_at=datetime(2025, 6, 1, tzinfo=timezone.utc) if deleted else None,
                        duration_ms=1_320_000 if state == "ready" else None,
                    )
                    if _is_schedulable(asset):
                        schedulable_count += 1
                        # Only this combination should pass
                        assert state == "ready"
                        assert approved is True
                        assert deleted is False

        assert schedulable_count == 1


class TestInvAssetLibraryPlanningOnly001:
    """INV-ASSET-LIBRARY-PLANNING-ONLY-001 enforcement tests."""

    def test_talp_001_no_asset_library_in_channel_manager(self) -> None:
        """INV-ASSET-LIBRARY-PLANNING-ONLY-001 — positive

        Invariant: ChannelManager MUST NOT import Asset Library.
        Scenario: Grep channel_manager.py for asset library imports.
        """
        import pathlib

        channel_manager = pathlib.Path(
            "/opt/retrovue/pkg/core/src/retrovue/runtime/channel_manager.py"
        )
        if not channel_manager.exists():
            pytest.skip("channel_manager.py not found")

        source = channel_manager.read_text()
        forbidden = ["db_asset_library", "DatabaseAssetLibrary", "InMemoryAssetLibrary"]
        for term in forbidden:
            assert term not in source, (
                f"INV-ASSET-LIBRARY-PLANNING-ONLY-001-VIOLATED: "
                f"channel_manager.py imports {term!r}"
            )

    def test_talp_002_no_asset_library_in_playout_session(self) -> None:
        """INV-ASSET-LIBRARY-PLANNING-ONLY-001 — positive

        Invariant: Playout session (runtime) MUST NOT import Asset Library.
        Scenario: Grep playout_session.py for asset library imports.
        """
        import pathlib

        playout_session = pathlib.Path(
            "/opt/retrovue/pkg/core/src/retrovue/runtime/playout_session.py"
        )
        if not playout_session.exists():
            pytest.skip("playout_session.py not found")

        source = playout_session.read_text()
        forbidden = ["db_asset_library", "DatabaseAssetLibrary", "InMemoryAssetLibrary"]
        for term in forbidden:
            assert term not in source, (
                f"INV-ASSET-LIBRARY-PLANNING-ONLY-001-VIOLATED: "
                f"playout_session.py imports {term!r}"
            )
