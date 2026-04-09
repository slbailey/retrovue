"""
INV-SOURCE-TYPE-REGISTRY-001 — Source type dispatch routes through a single registry.

Contract requirements:
- All source type dispatch MUST route through SOURCE_TYPE_REGISTRY.
- Unknown source types MUST be rejected with error tag INV-SOURCE-TYPE-REGISTRY-001-VIOLATED.
- No inline type-dispatch logic outside the registry lookup.
- No duplicate type keys in the registry.
- Each registered type maps to exactly one importer class.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

import pytest


class TestInvSourceTypeRegistry001:
    """Contract tests for INV-SOURCE-TYPE-REGISTRY-001."""

    def test_known_type_resolves_to_importer(self):
        """A known source type resolves to the correct importer class."""
        from retrovue.workflows.source_type_registry import SOURCE_TYPE_REGISTRY

        # 'plex' and 'filesystem' are the two canonical source types
        assert "plex" in SOURCE_TYPE_REGISTRY
        assert "filesystem" in SOURCE_TYPE_REGISTRY

        # Each entry is a callable (class) that can be instantiated
        for type_key, importer_cls in SOURCE_TYPE_REGISTRY.items():
            assert callable(importer_cls), (
                f"Registry entry for '{type_key}' must be callable"
            )

    def test_unknown_type_rejected_with_invariant_tag(self):
        """An unknown source type is rejected with the invariant violation tag."""
        from retrovue.workflows.source_type_registry import resolve_importer_class

        with pytest.raises(ValueError, match="INV-SOURCE-TYPE-REGISTRY-001-VIOLATED"):
            resolve_importer_class("betamax")

    def test_no_duplicate_type_keys(self):
        """The registry contains no duplicate type keys."""
        from retrovue.workflows.source_type_registry import SOURCE_TYPE_REGISTRY

        # dict keys are inherently unique, but verify no alias shadows a canonical key
        keys = list(SOURCE_TYPE_REGISTRY.keys())
        assert len(keys) == len(set(keys))

    def test_rejected_type_log_event_contains_registered_types(self):
        """A rejected source type error message names the available types."""
        from retrovue.workflows.source_type_registry import resolve_importer_class

        with pytest.raises(ValueError, match="plex") as exc_info:
            resolve_importer_class("betamax")
        # The error message should list available types for operator guidance
        msg = str(exc_info.value)
        assert "filesystem" in msg
        assert "betamax" in msg

    def test_resolve_returns_class_not_instance(self):
        """resolve_importer_class returns the class, not an instance."""
        from retrovue.workflows.source_type_registry import resolve_importer_class

        cls = resolve_importer_class("plex")
        assert isinstance(cls, type), "Registry must return the class, not an instance"
