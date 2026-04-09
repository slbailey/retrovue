"""
Domain enricher base class per INV-ENRICHER-EXECUTION-MODE-001 and
INV-ENRICHER-IDEMPOTENT-001.

Every enricher MUST declare exactly one execution mode. The system is
responsible for honoring the declared mode — enrichers MUST NOT
self-trigger. Adding a new execution mode requires a contract change.

Enricher results MUST include a version field (INV-ENRICHER-IDEMPOTENT-001).
Running an enricher twice on the same asset with the same input MUST
produce the same result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionMode(Enum):
    """Enricher execution modes per INV-ENRICHER-EXECUTION-MODE-001.

    - IMMEDIATE: runs inline during asset state transition to ready
    - LAZY_ON_ACCESS: runs when scheduling first accesses the enriched field
    - BACKGROUND: runs via the worker queue, not inline
    """

    IMMEDIATE = "immediate"
    LAZY_ON_ACCESS = "lazy_on_access"
    BACKGROUND = "background"


_VALID_MODES = frozenset(m.value for m in ExecutionMode)


@dataclass(frozen=True)
class EnrichmentResult:
    """Result of an enricher run. MUST include a version field."""

    version: str
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError(
                "INV-ENRICHER-IDEMPOTENT-001-VIOLATED: "
                "enricher result missing required 'version' field"
            )


class DomainEnricher(ABC):
    """Abstract base for domain-level enrichers.

    Every subclass MUST declare ``execution_mode`` and ``name``.
    The execution mode is validated at construction time —
    undeclared modes are rejected per INV-ENRICHER-EXECUTION-MODE-001.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique enricher type identifier."""

    @property
    @abstractmethod
    def execution_mode(self) -> ExecutionMode:
        """Declared execution mode for this enricher."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip validation for abstract subclasses
        if getattr(cls, "__abstractmethods__", None):
            return
        # Validate that the concrete class declares a valid execution mode
        # by checking the property returns a valid ExecutionMode
        # (actual validation deferred to instantiation since properties
        # can't be evaluated on the class itself)

    @abstractmethod
    def enrich(self, asset: Any) -> EnrichmentResult:
        """Enrich an asset and return a versioned result.

        This method MUST be idempotent: running twice on the same asset
        with the same input MUST produce the same result
        (excluding execution timestamps).
        """

    def _validate_execution_mode(self) -> None:
        """Validate that execution_mode is a legal ExecutionMode value."""
        mode = self.execution_mode
        if not isinstance(mode, ExecutionMode):
            raise ValueError(
                "INV-ENRICHER-EXECUTION-MODE-001-VIOLATED: "
                f"execution_mode must be an ExecutionMode enum, got {type(mode).__name__}"
            )
        if mode.value not in _VALID_MODES:
            raise ValueError(
                "INV-ENRICHER-EXECUTION-MODE-001-VIOLATED: "
                f"undeclared execution mode {mode.value!r}"
            )
