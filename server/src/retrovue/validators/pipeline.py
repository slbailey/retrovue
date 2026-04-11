"""
Validation pipeline — runs registered validators and merges results.

The pipeline produces a single aggregate ValidationResult per
INV-VALIDATOR-OUTPUT-SHAPE-001.
"""

from __future__ import annotations

from typing import Any

from .base import BaseValidator
from .result import ValidationResult, ValidatorEntry


class ValidationPipeline:
    """Ordered collection of validators that produces an aggregate result."""

    def __init__(self, validators: list[BaseValidator] | None = None) -> None:
        self._validators: list[BaseValidator] = list(validators or [])

    def add(self, validator: BaseValidator) -> None:
        self._validators.append(validator)

    def run(self, asset: Any) -> ValidationResult:
        """Run all validators against *asset* and merge into one result.

        The aggregate status is ``"validated"`` only if no validator fails.
        """
        all_errors = []
        all_warnings = []
        all_entries: dict[str, ValidatorEntry] = {}
        any_failed = False

        for v in self._validators:
            result = v.validate(asset)
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
            all_entries.update(result.validators)
            if result.status == "failed":
                any_failed = True

        return ValidationResult(
            status="failed" if any_failed else "validated",
            errors=all_errors,
            warnings=all_warnings,
            validators=all_entries,
        )
