"""Duration validator — checks that asset has a valid, positive duration."""

from __future__ import annotations

from typing import Any

from .base import BaseValidator
from .result import ValidationResult


class DurationValidator(BaseValidator):
    """Validates that an asset has a positive duration_ms value."""

    @property
    def name(self) -> str:
        return "duration"

    def validate(self, asset: Any) -> ValidationResult:
        duration_ms = getattr(asset, "duration_ms", None)
        if duration_ms is None:
            return self._fail(
                code="DURATION_MISSING",
                message="Asset has no duration_ms value",
            )
        if not isinstance(duration_ms, (int, float)):
            return self._fail(
                code="DURATION_INVALID_TYPE",
                message=f"duration_ms must be numeric, got {type(duration_ms).__name__}",
            )
        if duration_ms <= 0:
            return self._fail(
                code="DURATION_NON_POSITIVE",
                message=f"duration_ms must be positive, got {duration_ms}",
            )
        return self._pass()
