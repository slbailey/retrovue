"""
Contract tests: INV-VALIDATOR-OUTPUT-SHAPE-001
Validator outputs are structured and deterministic.

Every validator run MUST produce a structured result object with:
- status: "validated" or "failed"
- errors: list with code, validator, message
- warnings: list with code, validator, message
- validators: dict keyed by validator name

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

import pytest

from retrovue.validators.result import (
    ValidationResult,
    ValidatorEntry,
    ValidatorError,
    ValidatorWarning,
)


class TestInvValidatorOutputShape001:
    """INV-VALIDATOR-OUTPUT-SHAPE-001: Validator output shape contract."""

    def test_valid_result_accepted(self) -> None:
        """A result with all required fields populated is accepted."""
        result = ValidationResult(
            status="validated",
            errors=[],
            warnings=[],
            validators={"duration": ValidatorEntry(status="pass")},
        )
        assert result.status == "validated"
        assert result.errors == []
        assert result.warnings == []
        assert result.validators["duration"].status == "pass"

    def test_missing_status_raises(self) -> None:
        """A result missing the status field raises ValueError with invariant tag."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidationResult(
                status="",
                errors=[],
                warnings=[],
                validators={},
            )

    def test_invalid_status_raises(self) -> None:
        """A result with an invalid status value is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidationResult(
                status="partial",
                errors=[],
                warnings=[],
                validators={},
            )

    def test_error_missing_code_raises(self) -> None:
        """An error entry missing the code field is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorError(code="", validator="duration", message="bad")

    def test_error_missing_validator_raises(self) -> None:
        """An error entry missing the validator field is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorError(code="ERR_1", validator="", message="bad")

    def test_error_missing_message_raises(self) -> None:
        """An error entry missing the message field is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorError(code="ERR_1", validator="duration", message="")

    def test_warning_missing_code_raises(self) -> None:
        """A warning entry missing the code field is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorWarning(code="", validator="codec", message="warn")

    def test_warning_missing_validator_raises(self) -> None:
        """A warning entry missing the validator field is rejected."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorWarning(code="WARN_1", validator="", message="warn")

    def test_shape_is_additive_only(self) -> None:
        """Adding extra fields to a valid result MUST NOT cause rejection."""
        result = ValidationResult(
            status="validated",
            errors=[],
            warnings=[],
            validators={"codec": ValidatorEntry(status="pass")},
        )
        # Extra attributes can be set without raising
        result.extra_field = "should not cause rejection"  # type: ignore[attr-defined]
        assert result.status == "validated"

    def test_failed_result_accepted(self) -> None:
        """A failed result with proper error entries is accepted."""
        err = ValidatorError(
            code="DURATION_MISSING",
            validator="duration",
            message="Asset has no duration_ms value",
        )
        result = ValidationResult(
            status="failed",
            errors=[err],
            validators={"duration": ValidatorEntry(status="fail")},
        )
        assert result.status == "failed"
        assert len(result.errors) == 1
        assert result.errors[0].code == "DURATION_MISSING"

    def test_per_validator_status_invalid(self) -> None:
        """Per-validator status must be pass, fail, or warn."""
        with pytest.raises(ValueError, match="INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED"):
            ValidatorEntry(status="unknown")

    def test_per_validator_status_pass(self) -> None:
        assert ValidatorEntry(status="pass").status == "pass"

    def test_per_validator_status_fail(self) -> None:
        assert ValidatorEntry(status="fail").status == "fail"

    def test_per_validator_status_warn(self) -> None:
        assert ValidatorEntry(status="warn").status == "warn"
