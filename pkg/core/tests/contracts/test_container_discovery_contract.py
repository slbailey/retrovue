"""
Contract tests for ContainerDiscoveryContract.

Contract: docs/contracts/core/ContainerDiscoveryContract_v0.1.md
"""

import pytest


class TestContainerDiscoveryContract:
    """Verify ContainerDiscoveryContract guarantees."""

    def test_discovery_occurs_through_containers(self):
        """Media discovery is performed per container; no path bypasses a container."""
        pytest.skip("Phase 1 not yet implemented")

    def test_source_may_have_multiple_containers(self):
        """A source can have multiple collections/containers; discovery is invoked per container."""
        pytest.skip("Phase 1 not yet implemented")

    def test_discovery_returns_locators_without_catalog_writes(self):
        """Discovery step returns locator-like data and does not write to the catalog."""
        pytest.skip("Phase 1 not yet implemented")

    def test_locator_deterministic_for_same_item(self):
        """For the same importer item, the derived locator string is identical across calls."""
        pytest.skip("Phase 1 not yet implemented")
