"""
Contract tests for AssetMediaIdentityContract.

Contract: docs/contracts/core/AssetMediaIdentityContract_v0.1.md
"""

import pytest


class TestAssetMediaIdentityContract:
    """Verify AssetMediaIdentityContract guarantees."""

    def test_scheduler_references_assets_not_media(self):
        """Schedule/playlist artifacts reference Asset identifiers, not media as scheduling unit."""
        pytest.skip("Phase 2 not yet implemented")

    def test_media_identity_tuple_unique(self):
        """(source_id, container_id, locator) is unique; no duplicate locator within a container."""
        pytest.skip("Phase 2 not yet implemented")

    def test_same_locator_fingerprint_change_updates_no_new_entry(self):
        """Same locator with different fingerprint updates existing record; no new entry created."""
        pytest.skip("Phase 2 not yet implemented")

    def test_locator_disappears_mark_unavailable_not_delete(self):
        """When locator disappears from source, record is marked unavailable, not hard-deleted."""
        pytest.skip("Phase 2 not yet implemented")
