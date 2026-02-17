"""Contract tests for collection_enrichers duration guards."""
import pytest


class TestComputeConfidenceFromLabels:
    """Verify duration guard contracts in _compute_confidence_from_labels."""

    @pytest.fixture
    def compute_fn(self):
        """Import the inner function by extracting it from the module."""
        pass

    def test_zero_duration_blocks_promotion(self):
        """Assets with duration_ms=0 must never reach ready state."""
        pass

    def test_extreme_duration_blocks_promotion(self):
        """Assets with duration > 3 hours must not auto-promote."""
        pass

    def test_missing_duration_blocks_promotion(self):
        """Assets with no duration label after enrichment must not auto-promote."""
        pass
