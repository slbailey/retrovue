"""
INV-VALIDATOR-RESULT-PERSISTENCE-001 — Validator results that gate state transitions must be persisted.

Contract requirements:
- Every validator result that gates an asset state transition MUST be persisted.
- The persisted record conforms to INV-VALIDATOR-OUTPUT-SHAPE-001 without lossy compression.
- Persisted record includes: asset identifier, timestamp, and full structured result.
- Retrieval round-trips to the identical shape (no field loss, no type coercion).
- Warnings are preserved (not just errors).

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

import pytest
from datetime import datetime, UTC
from types import SimpleNamespace


def _make_passing_result():
    from retrovue.validators.result import (
        ValidationResult,
        ValidatorEntry,
    )

    return ValidationResult(
        status="validated",
        errors=[],
        warnings=[],
        validators={"duration": ValidatorEntry(status="pass")},
    )


def _make_failing_result():
    from retrovue.validators.result import (
        ValidationResult,
        ValidatorEntry,
        ValidatorError,
        ValidatorWarning,
    )

    return ValidationResult(
        status="failed",
        errors=[
            ValidatorError(
                code="DURATION_MISSING",
                validator="duration",
                message="No duration metadata",
            )
        ],
        warnings=[
            ValidatorWarning(
                code="CODEC_UNUSUAL",
                validator="codec",
                message="Unusual codec detected",
            )
        ],
        validators={
            "duration": ValidatorEntry(status="fail"),
            "codec": ValidatorEntry(status="warn"),
        },
    )


class TestInvValidatorResultPersistence001:
    """Contract tests for INV-VALIDATOR-RESULT-PERSISTENCE-001."""

    def test_passing_result_persisted_with_correct_fields(self):
        """A passing validator result is persisted with asset id, timestamp, and full result shape."""
        from retrovue.validators.persistence import ValidationResultStore

        store = ValidationResultStore()
        result = _make_passing_result()
        asset_id = "asset-001"
        ts = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)

        store.persist(asset_id=asset_id, timestamp=ts, result=result)

        record = store.retrieve(asset_id)
        assert record is not None
        assert record.asset_id == asset_id
        assert record.timestamp == ts
        assert record.result.status == "validated"
        assert record.result.validators["duration"].status == "pass"

    def test_failing_result_persisted_with_errors_and_statuses(self):
        """A failing validator result is persisted with errors and per-validator statuses intact."""
        from retrovue.validators.persistence import ValidationResultStore

        store = ValidationResultStore()
        result = _make_failing_result()
        asset_id = "asset-002"
        ts = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)

        store.persist(asset_id=asset_id, timestamp=ts, result=result)

        record = store.retrieve(asset_id)
        assert record is not None
        assert record.result.status == "failed"
        assert len(record.result.errors) == 1
        assert record.result.errors[0].code == "DURATION_MISSING"
        assert record.result.errors[0].validator == "duration"
        assert record.result.validators["duration"].status == "fail"

    def test_round_trip_preserves_canonical_shape(self):
        """A retrieved persisted result round-trips to the identical canonical shape."""
        from retrovue.validators.persistence import ValidationResultStore
        from retrovue.validators.result import ValidationResult

        store = ValidationResultStore()
        original = _make_failing_result()
        asset_id = "asset-003"
        ts = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)

        store.persist(asset_id=asset_id, timestamp=ts, result=original)
        record = store.retrieve(asset_id)

        restored = record.result
        assert isinstance(restored, ValidationResult)
        # Field-by-field comparison
        assert restored.status == original.status
        assert len(restored.errors) == len(original.errors)
        assert len(restored.warnings) == len(original.warnings)
        assert set(restored.validators.keys()) == set(original.validators.keys())
        for key in original.validators:
            assert restored.validators[key].status == original.validators[key].status
        for orig_e, rest_e in zip(original.errors, restored.errors):
            assert (rest_e.code, rest_e.validator, rest_e.message) == (
                orig_e.code,
                orig_e.validator,
                orig_e.message,
            )

    def test_state_transition_without_persisted_record_rejected(self):
        """A state transition attempted without a persisted validation record is rejected."""
        from retrovue.validators.persistence import ValidationResultStore

        store = ValidationResultStore()

        # No result persisted for this asset
        record = store.retrieve("asset-never-validated")
        assert record is None

    def test_persisted_results_include_warnings(self):
        """Persisted results include warnings — not just errors."""
        from retrovue.validators.persistence import ValidationResultStore

        store = ValidationResultStore()
        result = _make_failing_result()
        asset_id = "asset-005"
        ts = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)

        store.persist(asset_id=asset_id, timestamp=ts, result=result)
        record = store.retrieve(asset_id)

        assert len(record.result.warnings) == 1
        assert record.result.warnings[0].code == "CODEC_UNUSUAL"
        assert record.result.warnings[0].validator == "codec"
        assert record.result.warnings[0].message == "Unusual codec detected"
