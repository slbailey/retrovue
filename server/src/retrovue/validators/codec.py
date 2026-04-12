"""Codec validator — checks that asset has identifiable video and audio codecs."""

from __future__ import annotations

from typing import Any

from .base import BaseValidator
from .result import ValidationResult, ValidatorError, ValidatorWarning, ValidatorEntry


class CodecValidator(BaseValidator):
    """Validates that an asset has at least a video codec identified."""

    @property
    def name(self) -> str:
        return "codec"

    def validate(self, asset: Any) -> ValidationResult:
        video_codec = getattr(asset, "video_codec", None)
        audio_codec = getattr(asset, "audio_codec", None)

        errors: list[ValidatorError] = []
        warnings: list[ValidatorWarning] = []

        if not video_codec:
            errors.append(ValidatorError(
                code="VIDEO_CODEC_MISSING",
                validator=self.name,
                message="Asset has no video_codec value",
            ))

        if not audio_codec:
            warnings.append(ValidatorWarning(
                code="AUDIO_CODEC_MISSING",
                validator=self.name,
                message="Asset has no audio_codec value (audio-less assets may be valid)",
            ))

        if errors:
            return ValidationResult(
                status="failed",
                errors=errors,
                warnings=warnings,
                validators={self.name: ValidatorEntry(status="fail")},
            )

        if warnings:
            return ValidationResult(
                status="validated",
                warnings=warnings,
                validators={self.name: ValidatorEntry(status="warn")},
            )

        return self._pass()
