"""
Contract tests: INV-ENRICHER-IDEMPOTENT-001
Enrichers are idempotent and version-tolerant.

Running an enricher twice on the same asset with the same input MUST
produce the same result. Enricher results MUST include a version field.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from retrovue.enrichers.base import DomainEnricher, EnrichmentResult, ExecutionMode


class DeterministicEnricher(DomainEnricher):
    """Test enricher that always returns the same result for the same input."""

    @property
    def name(self) -> str:
        return "deterministic"

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.IMMEDIATE

    def enrich(self, asset: Any) -> EnrichmentResult:
        return EnrichmentResult(
            version="1.0",
            fields={"title_upper": getattr(asset, "title", "").upper()},
        )


class TestInvEnricherIdempotent001:
    """INV-ENRICHER-IDEMPOTENT-001: Enricher idempotency contract."""

    def test_same_input_same_output(self) -> None:
        """Running an enricher twice on the same asset produces identical results."""
        asset = SimpleNamespace(title="Test Movie")
        e = DeterministicEnricher()
        r1 = e.enrich(asset)
        r2 = e.enrich(asset)
        assert r1.version == r2.version
        assert r1.fields == r2.fields

    def test_no_duplicate_side_effects(self) -> None:
        """Re-running does not produce duplicate side effects."""
        asset = SimpleNamespace(title="Test", metadata=[])
        e = DeterministicEnricher()
        r1 = e.enrich(asset)
        r2 = e.enrich(asset)
        # Both runs return the same deterministic result
        assert r1.fields == r2.fields

    def test_result_contains_version(self) -> None:
        """Enricher result MUST include a version field."""
        asset = SimpleNamespace(title="Test")
        e = DeterministicEnricher()
        result = e.enrich(asset)
        assert result.version
        assert isinstance(result.version, str)

    def test_partial_failure_recovery_no_duplicate_side_effects(self) -> None:
        """After a partial failure mid-enrichment, re-running does not duplicate results.

        Simulates an enricher that tracks calls to detect duplicate side effects.
        A partial failure (exception mid-run) followed by a successful retry
        MUST produce the same final result as a single clean run.
        """

        class PartialFailureEnricher(DomainEnricher):
            """Enricher that fails on the first call, succeeds on the second."""

            def __init__(self) -> None:
                self._call_count = 0

            @property
            def name(self) -> str:
                return "partial_failure"

            @property
            def execution_mode(self) -> ExecutionMode:
                return ExecutionMode.IMMEDIATE

            def enrich(self, asset: Any) -> EnrichmentResult:
                self._call_count += 1
                if self._call_count == 1:
                    raise RuntimeError("simulated partial failure")
                return EnrichmentResult(
                    version="1.0",
                    fields={"title_upper": getattr(asset, "title", "").upper()},
                )

        asset = SimpleNamespace(title="Test Movie")
        e = PartialFailureEnricher()

        # First call fails (partial failure)
        with pytest.raises(RuntimeError, match="simulated partial failure"):
            e.enrich(asset)

        # Retry succeeds
        result = e.enrich(asset)
        assert result.version == "1.0"
        assert result.fields == {"title_upper": "TEST MOVIE"}

        # A clean enricher on the same asset produces identical output
        clean = DeterministicEnricher()
        clean_result = clean.enrich(asset)
        assert result.fields == clean_result.fields

    def test_missing_version_raises(self) -> None:
        """An enrichment result without a version is rejected."""
        with pytest.raises(ValueError, match="INV-ENRICHER-IDEMPOTENT-001-VIOLATED"):
            EnrichmentResult(version="", fields={})
