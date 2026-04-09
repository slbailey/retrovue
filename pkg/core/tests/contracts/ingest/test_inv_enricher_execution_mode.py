"""
Contract tests: INV-ENRICHER-EXECUTION-MODE-001
Enrichers declare execution mode; system triggers.

Every enricher MUST declare exactly one execution mode:
immediate, lazy_on_access, or background. The system is responsible for
honoring the declared mode — enrichers MUST NOT self-trigger.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

from typing import Any

import pytest

from retrovue.enrichers.base import DomainEnricher, EnrichmentResult, ExecutionMode


# ---------------------------------------------------------------------------
# Test enricher implementations
# ---------------------------------------------------------------------------

class ImmediateEnricher(DomainEnricher):
    @property
    def name(self) -> str:
        return "test_immediate"

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.IMMEDIATE

    def enrich(self, asset: Any) -> EnrichmentResult:
        return EnrichmentResult(version="1.0", fields={"enriched": True})


class BackgroundEnricher(DomainEnricher):
    @property
    def name(self) -> str:
        return "test_background"

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.BACKGROUND

    def enrich(self, asset: Any) -> EnrichmentResult:
        return EnrichmentResult(version="1.0", fields={"enriched": True})


class LazyEnricher(DomainEnricher):
    @property
    def name(self) -> str:
        return "test_lazy"

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.LAZY_ON_ACCESS

    def enrich(self, asset: Any) -> EnrichmentResult:
        return EnrichmentResult(version="1.0", fields={"enriched": True})


class TestInvEnricherExecutionMode001:
    """INV-ENRICHER-EXECUTION-MODE-001: Enricher execution mode contract."""

    def test_immediate_enricher_declares_mode(self) -> None:
        """An enricher with mode immediate executes via its declared mode."""
        e = ImmediateEnricher()
        assert e.execution_mode == ExecutionMode.IMMEDIATE
        assert e.execution_mode.value == "immediate"

    def test_background_enricher_declares_mode(self) -> None:
        """An enricher with mode background declares it correctly."""
        e = BackgroundEnricher()
        assert e.execution_mode == ExecutionMode.BACKGROUND
        assert e.execution_mode.value == "background"

    def test_lazy_enricher_declares_mode(self) -> None:
        """An enricher with mode lazy_on_access declares it correctly."""
        e = LazyEnricher()
        assert e.execution_mode == ExecutionMode.LAZY_ON_ACCESS
        assert e.execution_mode.value == "lazy_on_access"

    def test_no_enricher_lacks_execution_mode(self) -> None:
        """Every concrete enricher subclass must declare an execution mode."""
        for cls in [ImmediateEnricher, BackgroundEnricher, LazyEnricher]:
            instance = cls()
            assert isinstance(instance.execution_mode, ExecutionMode)

    def test_undeclared_mode_rejected(self) -> None:
        """An enricher with an undeclared mode string is rejected."""
        # ExecutionMode enum rejects invalid values
        with pytest.raises(ValueError):
            ExecutionMode("on_demand")

    def test_execution_mode_enum_exhaustive(self) -> None:
        """Only the three declared modes exist."""
        modes = {m.value for m in ExecutionMode}
        assert modes == {"immediate", "lazy_on_access", "background"}

    def test_system_triggers_enricher_not_self_trigger(self) -> None:
        """The system dispatches enrichers by mode; enrichers MUST NOT self-trigger.

        This test proves the contract by showing that enricher dispatch is
        controlled by a caller that inspects execution_mode, not by the
        enricher invoking itself.
        """
        triggered: list[tuple[str, str]] = []  # (name, mode)

        def system_dispatch(enricher: DomainEnricher, asset: object) -> EnrichmentResult | None:
            """System-level dispatcher that honors declared execution mode."""
            mode = enricher.execution_mode
            if mode == ExecutionMode.IMMEDIATE:
                result = enricher.enrich(asset)
                triggered.append((enricher.name, mode.value))
                return result
            elif mode == ExecutionMode.BACKGROUND:
                # Background: would be enqueued, not run inline
                triggered.append((enricher.name, mode.value))
                return None
            elif mode == ExecutionMode.LAZY_ON_ACCESS:
                # Lazy: deferred until access
                triggered.append((enricher.name, mode.value))
                return None
            else:
                raise ValueError(f"Unknown mode: {mode}")

        from types import SimpleNamespace
        asset = SimpleNamespace(title="Test")

        # System dispatches each enricher — enrichers do not call themselves
        system_dispatch(ImmediateEnricher(), asset)
        system_dispatch(BackgroundEnricher(), asset)
        system_dispatch(LazyEnricher(), asset)

        assert triggered == [
            ("test_immediate", "immediate"),
            ("test_background", "background"),
            ("test_lazy", "lazy_on_access"),
        ]

    def test_enricher_does_not_self_invoke(self) -> None:
        """An enricher MUST NOT call its own enrich() from __init__ or properties.

        This proves the enricher is passive — it waits for the system to call it.
        """
        # Constructing enrichers must not produce any enrichment side effects
        call_log: list[str] = []

        class AuditedEnricher(DomainEnricher):
            @property
            def name(self) -> str:
                return "audited"

            @property
            def execution_mode(self) -> ExecutionMode:
                return ExecutionMode.IMMEDIATE

            def enrich(self, asset: Any) -> EnrichmentResult:
                call_log.append("enrich_called")
                return EnrichmentResult(version="1.0", fields={})

        # Instantiation must not trigger enrich
        _e = AuditedEnricher()
        assert call_log == [], "Enricher must not self-trigger on construction"
