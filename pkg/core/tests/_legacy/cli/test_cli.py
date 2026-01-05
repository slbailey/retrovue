"""
Tests for CLI functionality.

This module contains tests for the Typer-based CLI commands,
validating output schemas and command behavior.
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

# Add src to path for imports
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from retrovue.cli.main import app  # noqa: E402
from retrovue.infra.uow import session  # noqa: E402


class TestCLI:
    """Test cases for CLI functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    def test_help_output(self):
        """Test that help output is generated correctly."""
        result = self.runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Retrovue - Retro IPTV Simulation Project" in result.output
    
    def test_ingest_help(self):
        """Test ingest command help."""
        result = self.runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "Content ingestion operations" in result.output
    
    def test_assets_help(self):
        """Test assets command help."""
        result = self.runner.invoke(app, ["assets", "--help"])
        assert result.exit_code == 0
        assert "Asset management operations" in result.output
    
    def test_review_help(self):
        """Test review command help."""
        result = self.runner.invoke(app, ["review", "--help"])
        assert result.exit_code == 0
        assert "Review queue operations" in result.output


class TestIngestCommand:
    """Test cases for ingest command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('retrovue.cli.commands.ingest.session')
    @patch('retrovue.cli.commands.ingest.IngestService')
    def test_ingest_run_success(self, mock_service_class, mock_session):
        """Test successful ingest run."""
        # Mock the service and session
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.run_ingest.return_value = {
            "discovered": 10,
            "registered": 8,
            "enriched": 6,
            "canonicalized": 4,
            "queued_for_review": 2
        }
        
        # Mock session context manager
        mock_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_session.return_value.__exit__ = Mock(return_value=None)
        
        result = self.runner.invoke(app, ["ingest", "run", "filesystem:/test"])
        assert result.exit_code == 0
        assert "Ingest completed for source: filesystem:/test" in result.output
        assert "Discovered: 10" in result.output
    
    @patch('retrovue.cli.commands.ingest.session')
    @patch('retrovue.cli.commands.ingest.IngestService')
    def test_ingest_run_json_output(self, mock_service_class, mock_session):
        """Test ingest run with JSON output."""
        # Mock the service and session
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.run_ingest.return_value = {
            "discovered": 5,
            "registered": 4,
            "enriched": 3,
            "canonicalized": 2,
            "queued_for_review": 1
        }
        
        # Mock session context manager
        mock_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_session.return_value.__exit__ = Mock(return_value=None)
        
        result = self.runner.invoke(app, ["ingest", "run", "filesystem:/test", "--json"])
        assert result.exit_code == 0
        
        # Parse JSON output
        output_lines = result.output.strip().split('\n')
        json_output = '\n'.join(output_lines[1:])  # Skip the first line which might be a warning
        data = json.loads(json_output)
        
        assert data["source"] == "filesystem:/test"
        assert data["counts"]["discovered"] == 5


class TestAssetsCommand:
    """Test cases for assets command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('retrovue.cli.commands.assets.session')
    @patch('retrovue.cli.commands.assets.LibraryService')
    def test_assets_list_success(self, mock_service_class, mock_session):
        """Test successful assets list."""
        # Mock the service and session
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        
        # Mock asset data
        mock_asset = Mock()
        mock_asset.id = "test-id"
        mock_asset.uri = "file:///test/path"
        mock_asset.canonical = True
        mock_service.list_assets.return_value = [mock_asset]
        
        # Mock session context manager
        mock_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_session.return_value.__exit__ = Mock(return_value=None)
        
        result = self.runner.invoke(app, ["assets", "list"])
        assert result.exit_code == 0
        assert "Found 1 assets" in result.output


class TestReviewCommand:
    """Test cases for review command."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
    
    @patch('retrovue.cli.commands.review.session')
    @patch('retrovue.cli.commands.review.LibraryService')
    def test_review_list_success(self, mock_service_class, mock_session):
        """Test successful review list."""
        # Mock the service and session
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        
        # Mock review data
        mock_review = Mock()
        mock_review.id = "review-id"
        mock_review.asset_id = "asset-id"
        mock_review.reason = "Low confidence"
        mock_review.confidence = 0.3
        mock_service.list_review_queue.return_value = [mock_review]
        
        # Mock session context manager
        mock_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_session.return_value.__exit__ = Mock(return_value=None)
        
        result = self.runner.invoke(app, ["review", "list"])
        assert result.exit_code == 0
        assert "Found 1 items in review queue" in result.output
    
    @patch('retrovue.cli.commands.review.session')
    @patch('retrovue.cli.commands.review.LibraryService')
    def test_review_resolve_success(self, mock_service_class, mock_session):
        """Test successful review resolve."""
        # Mock the service and session
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.resolve_review.return_value = True
        
        # Mock session context manager
        mock_session.return_value.__enter__ = Mock(return_value=Mock())
        mock_session.return_value.__exit__ = Mock(return_value=None)
        
        result = self.runner.invoke(app, [
            "review", "resolve", 
            "123e4567-e89b-12d3-a456-426614174000",
            "987fcdeb-51a2-43d1-b456-426614174000"
        ])
        assert result.exit_code == 0
        assert "Successfully resolved review" in result.output


class TestUoW:
    """Test cases for Unit of Work."""
    
    @patch('retrovue.cli.uow.SessionLocal')
    def test_session_context_manager_success(self, mock_session_local):
        """Test successful session context manager."""
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        with session() as db:
            assert db == mock_session
        
        # Verify commit was called
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()
    
    @patch('retrovue.cli.uow.SessionLocal')
    def test_session_context_manager_error(self, mock_session_local):
        """Test session context manager with error."""
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        with pytest.raises(ValueError):
            with session() as _db:
                raise ValueError("Test error")
        
        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
