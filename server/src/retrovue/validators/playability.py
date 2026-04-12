"""Playability validator — composite check that asset meets minimum playout requirements."""

from __future__ import annotations

from typing import Any

from .base import BaseValidator
from .result import ValidationResult, ValidatorError, ValidatorEntry


class PlayabilityValidator(BaseValidator):
    """Validates that an asset meets minimum requirements for playout.

    An asset is playable if it has:
    - A positive duration
    - A video codec
    - A non-zero file size
    - A resolvable URI
    """

    @property
    def name(self) -> str:
        return "playability"

    def validate(self, asset: Any) -> ValidationResult:
        errors: list[ValidatorError] = []

        duration_ms = getattr(asset, "duration_ms", None)
        if not duration_ms or (isinstance(duration_ms, (int, float)) and duration_ms <= 0):
            errors.append(ValidatorError(
                code="PLAYABILITY_NO_DURATION",
                validator=self.name,
                message="Asset is not playable: missing or non-positive duration",
            ))

        video_codec = getattr(asset, "video_codec", None)
        if not video_codec:
            errors.append(ValidatorError(
                code="PLAYABILITY_NO_VIDEO_CODEC",
                validator=self.name,
                message="Asset is not playable: missing video codec",
            ))

        size = getattr(asset, "size", None)
        if not size or (isinstance(size, (int, float)) and size <= 0):
            errors.append(ValidatorError(
                code="PLAYABILITY_ZERO_SIZE",
                validator=self.name,
                message="Asset is not playable: file size is zero or missing",
            ))

        uri = getattr(asset, "uri", None) or getattr(asset, "canonical_uri", None)
        if not uri:
            errors.append(ValidatorError(
                code="PLAYABILITY_NO_URI",
                validator=self.name,
                message="Asset is not playable: no resolvable URI",
            ))

        if errors:
            return ValidationResult(
                status="failed",
                errors=errors,
                validators={self.name: ValidatorEntry(status="fail")},
            )
        return self._pass()
