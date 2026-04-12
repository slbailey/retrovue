"""
Abstract base class for asset validators.

Validators inspect asset properties and produce structured results per
INV-VALIDATOR-OUTPUT-SHAPE-001. Each validator is responsible for one
concern (duration, codec, container format, playability).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Any

from .result import ValidationResult, ValidatorEntry, ValidatorError, ValidatorWarning


class BaseValidator(ABC):
    """Abstract base for asset validators.

    Subclasses MUST implement ``name`` and ``validate()``.
    The ``validate()`` method receives an asset-like object and returns
    a single-validator ValidationResult.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique validator name used as key in the validators map."""

    @abstractmethod
    def validate(self, asset: Any) -> ValidationResult:
        """Run this validator against *asset* and return a canonical result.

        The returned ``ValidationResult.validators`` dict MUST contain
        exactly one entry keyed by ``self.name``.
        """

    # ------------------------------------------------------------------
    # Convenience helpers for subclasses
    # ------------------------------------------------------------------

    def _pass(self) -> ValidationResult:
        return ValidationResult(
            status="validated",
            validators={self.name: ValidatorEntry(status="pass")},
        )

    def _fail(self, code: str, message: str) -> ValidationResult:
        return ValidationResult(
            status="failed",
            errors=[ValidatorError(code=code, validator=self.name, message=message)],
            validators={self.name: ValidatorEntry(status="fail")},
        )

    def _warn(self, code: str, message: str) -> ValidationResult:
        return ValidationResult(
            status="validated",
            warnings=[ValidatorWarning(code=code, validator=self.name, message=message)],
            validators={self.name: ValidatorEntry(status="warn")},
        )
