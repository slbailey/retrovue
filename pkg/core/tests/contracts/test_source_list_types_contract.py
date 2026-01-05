"""
Contract tests for `retrovue source list-types` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/SourceListTypesContract.md.

This test enforces the CLI contract rules (B-#) for the source list-types command.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestSourceListTypesContract:
    """Contract tests for retrovue source list-types command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_list_types_help_flag_exits_zero(self):
        """
        Contract B-7: The command MUST support help and exit with code 0.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--help"])
        
        assert result.exit_code == 0
        assert "Show available source types" in result.stdout or "list-types" in result.stdout

    def test_source_list_types_basic_discovery(self):
        """
        Contract B-1: The command MUST return source types derived from discovered 
        importer filenames following {source_type}_importer.py pattern.
        """
        result = self.runner.invoke(app, ["source", "list-types"])
        
        assert result.exit_code == 0
        assert "Available source types:" in result.stdout
        # Should include plex and filesystem based on existing importers
        assert "plex" in result.stdout
        assert "filesystem" in result.stdout

    def test_source_list_types_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields 
        "status", "source_types", and "total" with appropriate data structures 
        including interface compliance status.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
        
        # Verify required fields are present
        assert "status" in output_data
        assert "source_types" in output_data
        assert "total" in output_data
        
        # Verify values
        assert output_data["status"] == "ok"
        assert isinstance(output_data["source_types"], list)
        assert output_data["total"] >= 2  # At least plex and filesystem
        
        # Verify source type structure
        source_types = output_data["source_types"]
        assert len(source_types) >= 2
        
        # Check that both plex and filesystem are present
        type_names = [st["type"] for st in source_types]
        assert "plex" in type_names
        assert "filesystem" in type_names
        
        # Verify each source type has required fields
        for source_type in source_types:
            assert "type" in source_type
            assert "importer_file" in source_type
            assert "display_name" in source_type
            assert "available" in source_type
            assert "interface_compliant" in source_type
            assert "status" in source_type
            assert source_type["available"] is True
            assert source_type["interface_compliant"] is True

    def test_source_list_types_dry_run_support(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be listed without 
        executing external validation. In --dry-run mode, the command MAY use 
        an in-memory view of the registry state instead of re-scanning the filesystem.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--dry-run"])
        
        assert result.exit_code == 0
        assert "Would list" in result.stdout or "DRY RUN" in result.stdout
        assert "source types from registry" in result.stdout or "source types" in result.stdout

    def test_source_list_types_dry_run_json_output(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be listed without 
        executing external validation, including JSON format.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--dry-run", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
        
        # Verify dry-run status
        assert output_data["status"] == "dry_run"
        assert "source_types" in output_data
        assert "total" in output_data

    def test_source_list_types_test_db_support(self):
        """
        Contract: The --test-db flag MUST work for testing in isolated environment.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--test-db"])
        
        assert result.exit_code == 0
        assert "Available source types:" in result.stdout

    def test_source_list_types_deterministic_output(self):
        """
        Contract B-6: Source type enumeration MUST be deterministic - the same 
        registry state MUST produce the same enumeration results.
        """
        # Run the command multiple times
        result1 = self.runner.invoke(app, ["source", "list-types"])
        result2 = self.runner.invoke(app, ["source", "list-types"])
        
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        
        # Output should be identical
        assert result1.stdout == result2.stdout

    def test_source_list_types_json_deterministic_output(self):
        """
        Contract B-6: JSON output MUST also be deterministic.
        """
        # Run the command multiple times with JSON
        result1 = self.runner.invoke(app, ["source", "list-types", "--json"])
        result2 = self.runner.invoke(app, ["source", "list-types", "--json"])
        
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        
        # Parse both outputs
        output1 = json.loads(result1.stdout)
        output2 = json.loads(result2.stdout)
        
        # Output should be identical
        assert output1 == output2

    def test_source_list_types_registry_error_handling(self):
        """
        Contract B-4: On enumeration failure (registry error), the command 
        MUST exit with code 1 and print a human-readable error message.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.side_effect = Exception("Registry access error")
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 1
            assert "Error listing source types" in result.stderr or "Error" in result.stderr

    def test_source_list_types_empty_registry_handling(self):
        """
        Contract B-8: Empty enumeration results (no source types) MUST return 
        exit code 0 with message "No source types available".
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 0
            assert "No source types available" in result.stdout

    def test_source_list_types_empty_registry_json_handling(self):
        """
        Contract B-8: Empty enumeration results in JSON format MUST return 
        exit code 0 with appropriate JSON structure.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            assert output_data["status"] == "ok"
            assert output_data["source_types"] == []
            assert output_data["total"] == 0

    def test_source_list_types_human_output_format(self):
        """
        Contract: Human-readable output MUST match the specified format.
        """
        result = self.runner.invoke(app, ["source", "list-types"])
        
        assert result.exit_code == 0
        
        # Check for expected format elements
        assert "Available source types:" in result.stdout
        assert "Total:" in result.stdout and "source types available" in result.stdout
        
        # Check that interface compliance is displayed
        assert "[OK]" in result.stdout or "[ERROR]" in result.stdout

    def test_source_list_types_validation_compliance(self):
        """
        Contract B-2: The command MUST validate source type uniqueness and 
        interface compliance before reporting.
        """
        result = self.runner.invoke(app, ["source", "list-types"])
        
        assert result.exit_code == 0
        
        # Verify that both plex and filesystem types are properly validated
        assert "plex" in result.stdout
        assert "filesystem" in result.stdout
        
        # Verify interface compliance is checked and reported
        assert "[OK]" in result.stdout or "[ERROR]" in result.stdout

    def test_source_list_types_interface_compliance_reporting(self):
        """
        Contract B-2: Interface compliance MUST be validated and reported.
        """
        result = self.runner.invoke(app, ["source", "list-types", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        output_data = json.loads(result.stdout)
        source_types = output_data["source_types"]
        
        # Verify interface compliance is reported for each source type
        for source_type in source_types:
            assert "interface_compliant" in source_type
            assert source_type["interface_compliant"] is True  # Should be compliant

    def test_source_list_types_valid_and_invalid_importers(self):
        """
        Contract B-7: The command MUST support both valid and invalid importer files, 
        reporting availability and interface compliance appropriately.
        """
        result = self.runner.invoke(app, ["source", "list-types"])
        
        assert result.exit_code == 0
        
        # Should handle both valid importers (plex, filesystem) gracefully
        assert "plex" in result.stdout
        assert "filesystem" in result.stdout
        
        # Should not crash on any importer files present
        assert "Error" not in result.stdout
