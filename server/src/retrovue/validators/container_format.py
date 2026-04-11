"""Container format validator — checks that asset has an identifiable container format."""

from __future__ import annotations

from typing import Any

from .base import BaseValidator
from .result import ValidationResult


class ContainerFormatValidator(BaseValidator):
    """Validates that an asset has a recognized container format."""

    @property
    def name(self) -> str:
        return "container"

    def validate(self, asset: Any) -> ValidationResult:
        container_format = getattr(asset, "container_format", None)
        if not container_format:
            return self._fail(
                code="CONTAINER_FORMAT_MISSING",
                message="Asset has no container_format value",
            )
        return self._pass()
