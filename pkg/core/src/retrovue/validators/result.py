"""
Canonical validator output shape per INV-VALIDATOR-OUTPUT-SHAPE-001.

Every validator run MUST produce a structured result with:
- status: "validated" or "failed"
- errors: list of structured error entries
- warnings: list of structured warning entries
- validators: dict keyed by validator name with per-validator status

Each error/warning entry MUST include code, validator, and message.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidatorError:
    """A single validation error with machine-readable code."""

    code: str
    validator: str
    message: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "error entry missing required 'code' field"
            )
        if not self.validator:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "error entry missing required 'validator' field"
            )
        if not self.message:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "error entry missing required 'message' field"
            )


@dataclass(frozen=True)
class ValidatorWarning:
    """A single validation warning with machine-readable code."""

    code: str
    validator: str
    message: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "warning entry missing required 'code' field"
            )
        if not self.validator:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "warning entry missing required 'validator' field"
            )
        if not self.message:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "warning entry missing required 'message' field"
            )


@dataclass(frozen=True)
class ValidatorEntry:
    """Per-validator result within a ValidationResult."""

    status: str  # "pass", "fail", or "warn"

    def __post_init__(self) -> None:
        if self.status not in ("pass", "fail", "warn"):
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                f"per-validator status must be 'pass', 'fail', or 'warn', got {self.status!r}"
            )


_VALID_STATUSES = frozenset({"validated", "failed"})


@dataclass
class ValidationResult:
    """Canonical validator output shape per INV-VALIDATOR-OUTPUT-SHAPE-001.

    The shape is additive-only: extra fields beyond the required set are
    permitted and MUST NOT cause rejection.
    """

    status: str
    errors: list[ValidatorError] = field(default_factory=list)
    warnings: list[ValidatorWarning] = field(default_factory=list)
    validators: dict[str, ValidatorEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.status:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                "result missing required 'status' field"
            )
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                "INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED: "
                f"status must be 'validated' or 'failed', got {self.status!r}"
            )

    @property
    def passed(self) -> bool:
        return self.status == "validated"
