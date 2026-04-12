"""
Readiness gate validator — checks that all processors marked
required_for_readiness=True have completed (their produced_metadata
fields are populated on the asset).

Enforces INV-PROCESSOR-READINESS-GATE-001.
"""

from __future__ import annotations

from typing import Any

from ..catalog.processor_capability import get_readiness_required_processors
from .base import BaseValidator
from .result import ValidationResult


class ReadinessGateValidator(BaseValidator):
    """Blocks ready transition unless all required processors have run."""

    @property
    def name(self) -> str:
        return "readiness_gate"

    def validate(self, asset: Any) -> ValidationResult:
        missing_by_processor: dict[str, list[str]] = {}

        for cap in get_readiness_required_processors():
            missing_fields = [
                field for field in cap.produced_metadata
                if getattr(asset, field, None) is None
            ]
            if missing_fields:
                missing_by_processor[cap.processor_id] = missing_fields

        if not missing_by_processor:
            return self._pass()

        errors = []
        for proc_id, fields in missing_by_processor.items():
            errors.append(self._make_error(proc_id, fields))

        return ValidationResult(
            status="failed",
            errors=errors,
            validators={self.name: self._fail_entry()},
        )

    def _make_error(self, processor_id: str, missing_fields: list[str]) -> Any:
        from .result import ValidatorError

        return ValidatorError(
            code="READINESS_PROCESSOR_INCOMPLETE",
            validator=self.name,
            message=(
                f"Processor '{processor_id}' required for readiness but missing "
                f"fields: {', '.join(missing_fields)}"
            ),
        )

    @staticmethod
    def _fail_entry() -> Any:
        from .result import ValidatorEntry

        return ValidatorEntry(status="fail")
