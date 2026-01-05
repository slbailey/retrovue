"""
Tests for the fake importer ingest flow.

This module tests the ingest service using the fake importer
to verify the complete ingest pipeline works correctly.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")

from retrovue.content_manager.ingest_service import IngestService  # noqa: E402


class TestFakeImporterIngest:
    """Test cases for fake importer ingest flow."""

    def test_run_ingest_fake(self, ingest_service: IngestService):
        """Test running ingest with fake importer."""
        # Run ingest with fake importer
        counts = ingest_service.run_ingest("fake")

        # Verify counts
        assert counts["discovered"] == 2
        assert counts["registered"] == 2
        assert counts["canonicalized"] >= 1  # At least one should be canonicalized
        assert counts["queued_for_review"] >= 0  # Some might be queued for review

        # Verify total processed (all registered assets should be either canonical or queued)
        assert counts["registered"] == 2
        assert counts["canonicalized"] + counts["queued_for_review"] == 2

    def test_fake_importer_discovery(self):
        """Test fake importer discovery directly."""
        from retrovue.adapters.importers.fake_importer import FakeImporter

        importer = FakeImporter()
        discovered = importer.discover()

        # Verify discovery results
        assert len(discovered) == 2

        # Check first item (TV show with season/episode)
        show_item = discovered[0]
        assert show_item["path_uri"] == "file:///media/retro/Show.S01E01.mkv"
        assert show_item["size"] == 1234567890
        assert show_item["provider"] == "fake"
        assert show_item["raw_labels"]["title_guess"] == "Show"
        assert show_item["raw_labels"]["season"] == 1
        assert show_item["raw_labels"]["episode"] == 1

        # Check second item (movie with year)
        movie_item = discovered[1]
        assert movie_item["path_uri"] == "file:///media/retro/Movie.2024.mkv"
        assert movie_item["size"] == 2345678901
        assert movie_item["provider"] == "fake"
        assert movie_item["raw_labels"]["title_guess"] == "Movie"
        assert movie_item["raw_labels"]["year"] == 2024

    def test_importer_registry(self):
        """Test importer registry functionality."""
        from retrovue.adapters.registry import registry

        # Test getting fake importer
        importer = registry.get_importer("fake")
        assert importer is not None

        # Test listing importers
        importers = registry.list_importers()
        assert "fake" in importers

        # Test unknown importer
        with pytest.raises(ValueError):
            registry.get_importer("unknown")

    def test_confidence_calculation(self, ingest_service: IngestService):
        """Test confidence calculation for different discovery items."""
        # Test TV show item (should have high confidence)
        show_item = {"raw_labels": {"title_guess": "Show", "season": 1, "episode": 1}}
        confidence = ingest_service._calculate_confidence(show_item)
        assert confidence >= 0.8  # Should be high confidence

        # Test movie item (should have medium confidence)
        movie_item = {"raw_labels": {"title_guess": "Movie", "year": 2024}}
        confidence = ingest_service._calculate_confidence(movie_item)
        assert 0.5 <= confidence < 0.8  # Should be medium confidence

        # Test minimal item (should have low confidence)
        minimal_item = {"raw_labels": {"title_guess": "Unknown"}}
        confidence = ingest_service._calculate_confidence(minimal_item)
        assert confidence < 0.8  # Should be low confidence

    def test_ingest_pipeline_flow(self, ingest_service: IngestService, temp_db_session):
        """Test the complete ingest pipeline flow."""
        # Run ingest
        counts = ingest_service.run_ingest("fake")

        # Verify all items were processed
        assert counts["discovered"] == 2
        assert counts["registered"] == 2

        # Check that assets were created in database
        from retrovue.domain.entities import Asset

        assets = temp_db_session.query(Asset).all()
        assert len(assets) == 2

        # Check that at least one asset is canonical
        canonical_assets = [asset for asset in assets if asset.canonical]
        assert len(canonical_assets) >= 1

        # Check that some assets might be in review queue
        from retrovue.domain.entities import ReviewQueue

        reviews = temp_db_session.query(ReviewQueue).all()
        # Total should be 2 (all assets either canonical or in review)
        assert len(canonical_assets) + len(reviews) == 2
