"""
Tests for the plugin registry system.

This module tests the registry functionality for importers and enrichers.
"""

import pytest

from retrovue.adapters.enrichers.base import EnricherNotFoundError
from retrovue.adapters.importers.base import DiscoveredItem, ImporterNotFoundError
from retrovue.adapters.registry import (
    clear_registries,
    get_enricher,
    get_importer,
    get_registry_stats,
    list_enrichers,
    list_importers,
    register_enricher,
    register_importer,
    unregister_enricher,
    unregister_importer,
)


class MockImporter:
    """Mock importer for testing."""
    
    def __init__(self, name: str):
        self.name = name
    
    def discover(self) -> list[DiscoveredItem]:
        return []


class MockEnricher:
    """Mock enricher for testing."""
    
    def __init__(self, name: str):
        self.name = name
    
    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        return discovered_item


class TestRegistry:
    """Test cases for the plugin registry."""
    
    def setup_method(self):
        """Set up test fixtures."""
        clear_registries()
    
    def teardown_method(self):
        """Clean up after tests."""
        clear_registries()
    
    def test_register_importer(self):
        """Test registering an importer."""
        importer = MockImporter("test_importer")
        
        register_importer(importer)
        
        # Check that it's registered
        assert get_importer("test_importer") is importer
        assert "test_importer" in [i.name for i in list_importers()]
    
    def test_register_importer_duplicate(self):
        """Test registering a duplicate importer."""
        importer1 = MockImporter("test_importer")
        importer2 = MockImporter("test_importer")
        
        register_importer(importer1)
        
        with pytest.raises(ValueError, match="already registered"):
            register_importer(importer2)
    
    def test_register_importer_empty_name(self):
        """Test registering an importer with empty name."""
        importer = MockImporter("")
        
        with pytest.raises(ValueError, match="cannot be empty"):
            register_importer(importer)
    
    def test_get_importer_not_found(self):
        """Test getting a nonexistent importer."""
        with pytest.raises(ImporterNotFoundError):
            get_importer("nonexistent")
    
    def test_unregister_importer(self):
        """Test unregistering an importer."""
        importer = MockImporter("test_importer")
        
        register_importer(importer)
        assert get_importer("test_importer") is importer
        
        unregister_importer("test_importer")
        
        with pytest.raises(ImporterNotFoundError):
            get_importer("test_importer")
    
    def test_unregister_importer_not_found(self):
        """Test unregistering a nonexistent importer."""
        with pytest.raises(ImporterNotFoundError):
            unregister_importer("nonexistent")
    
    def test_list_importers(self):
        """Test listing importers."""
        importer1 = MockImporter("importer1")
        importer2 = MockImporter("importer2")
        
        register_importer(importer1)
        register_importer(importer2)
        
        importers = list_importers()
        
        assert len(importers) == 2
        assert importer1 in importers
        assert importer2 in importers
    
    def test_register_enricher(self):
        """Test registering an enricher."""
        enricher = MockEnricher("test_enricher")
        
        register_enricher(enricher)
        
        # Check that it's registered
        assert get_enricher("test_enricher") is enricher
        assert "test_enricher" in [e.name for e in list_enrichers()]
    
    def test_register_enricher_duplicate(self):
        """Test registering a duplicate enricher."""
        enricher1 = MockEnricher("test_enricher")
        enricher2 = MockEnricher("test_enricher")
        
        register_enricher(enricher1)
        
        with pytest.raises(ValueError, match="already registered"):
            register_enricher(enricher2)
    
    def test_register_enricher_empty_name(self):
        """Test registering an enricher with empty name."""
        enricher = MockEnricher("")
        
        with pytest.raises(ValueError, match="cannot be empty"):
            register_enricher(enricher)
    
    def test_get_enricher_not_found(self):
        """Test getting a nonexistent enricher."""
        with pytest.raises(EnricherNotFoundError):
            get_enricher("nonexistent")
    
    def test_unregister_enricher(self):
        """Test unregistering an enricher."""
        enricher = MockEnricher("test_enricher")
        
        register_enricher(enricher)
        assert get_enricher("test_enricher") is enricher
        
        unregister_enricher("test_enricher")
        
        with pytest.raises(EnricherNotFoundError):
            get_enricher("test_enricher")
    
    def test_unregister_enricher_not_found(self):
        """Test unregistering a nonexistent enricher."""
        with pytest.raises(EnricherNotFoundError):
            unregister_enricher("nonexistent")
    
    def test_list_enrichers(self):
        """Test listing enrichers."""
        enricher1 = MockEnricher("enricher1")
        enricher2 = MockEnricher("enricher2")
        
        register_enricher(enricher1)
        register_enricher(enricher2)
        
        enrichers = list_enrichers()
        
        assert len(enrichers) == 2
        assert enricher1 in enrichers
        assert enricher2 in enrichers
    
    def test_clear_registries(self):
        """Test clearing all registries."""
        importer = MockImporter("test_importer")
        enricher = MockEnricher("test_enricher")
        
        register_importer(importer)
        register_enricher(enricher)
        
        assert len(list_importers()) == 1
        assert len(list_enrichers()) == 1
        
        clear_registries()
        
        assert len(list_importers()) == 0
        assert len(list_enrichers()) == 0
    
    def test_get_registry_stats(self):
        """Test getting registry statistics."""
        importer1 = MockImporter("importer1")
        importer2 = MockImporter("importer2")
        enricher1 = MockEnricher("enricher1")
        
        register_importer(importer1)
        register_importer(importer2)
        register_enricher(enricher1)
        
        stats = get_registry_stats()
        
        assert stats["importers"]["count"] == 2
        assert "importer1" in stats["importers"]["names"]
        assert "importer2" in stats["importers"]["names"]
        
        assert stats["enrichers"]["count"] == 1
        assert "enricher1" in stats["enrichers"]["names"]
    
    def test_registry_isolation(self):
        """Test that importers and enrichers are isolated."""
        importer = MockImporter("test_importer")
        enricher = MockEnricher("test_enricher")
        
        register_importer(importer)
        register_enricher(enricher)
        
        # Check that they don't interfere with each other
        assert get_importer("test_importer") is importer
        assert get_enricher("test_enricher") is enricher
        
        # Check that names don't conflict
        with pytest.raises(ImporterNotFoundError):
            get_importer("test_enricher")
        
        with pytest.raises(EnricherNotFoundError):
            get_enricher("test_importer")
