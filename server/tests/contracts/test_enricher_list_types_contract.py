"""
Contract tests for `retrovue enricher list-types` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/EnricherListTypesContract.md.

This test enforces the CLI contract rules (B-#) for the enricher list-types command.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherListTypesContract:
    """Contract tests for retrovue enricher list-types command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_list_types_help_flag_exits_zero(self):
        """
        Contract B-7: The command MUST support help and exit with code 0.
        """
        result = self.runner.invoke(app, ["enricher", "list-types", "--help"])
        
        assert result.exit_code == 0
        assert "Show all enricher types" in result.stdout or "list-types" in result.stdout

    def test_enricher_list_types_basic_discovery(self):
        """
        Contract B-1: The command MUST scan registry for available enricher types 
        and display all discovered types.
        """
        result = self.runner.invoke(app, ["enricher", "list-types"])
        
        assert result.exit_code == 0
        assert "Available enricher types:" in result.stdout
        assert "ingest" in result.stdout
        assert "playout" in result.stdout
        assert "Enrichers that run during content ingestion" in result.stdout
        assert "Enrichers that run during playout" in result.stdout

    def test_enricher_list_types_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields 
        "status", "enricher_types", and "total" with appropriate data structures.
        """
        result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
        
        # Verify required fields are present
        assert "status" in output_data
        assert "enricher_types" in output_data
        assert "total" in output_data
        
        # Verify values
        assert output_data["status"] == "ok"
        assert isinstance(output_data["enricher_types"], list)
        assert output_data["total"] == 9
        
        # Verify enricher type structure
        enricher_types = output_data["enricher_types"]
        assert len(enricher_types) == 9
        
        # Check that both ingest and playout are present
        type_names = [et["type"] for et in enricher_types]
        assert "ingest" in type_names
        assert "playout" in type_names
        
        # Verify each enricher type has required fields
        for enricher_type in enricher_types:
            assert "type" in enricher_type
            assert "description" in enricher_type
            assert "available" in enricher_type
            assert enricher_type["available"] is True

    def test_enricher_list_types_dry_run_support(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be discovered 
        without executing external validation.
        """
        result = self.runner.invoke(app, ["enricher", "list-types", "--dry-run"])
        
        assert result.exit_code == 0
        assert "Would list" in result.stdout or "DRY RUN" in result.stdout
        assert "enricher types from registry" in result.stdout or "enricher types" in result.stdout

    def test_enricher_list_types_dry_run_json_output(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be discovered 
        without executing external validation, including JSON format.
        """
        result = self.runner.invoke(app, ["enricher", "list-types", "--dry-run", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
        
        # Verify dry-run status
        assert output_data["status"] == "dry_run"
        assert "enricher_types" in output_data
        assert "total" in output_data

    def test_enricher_list_types_test_db_support(self):
        """
        Contract: The --test-db flag MUST work for testing in isolated environment.
        """
        result = self.runner.invoke(app, ["enricher", "list-types", "--test-db"])
        
        assert result.exit_code == 0
        assert "Available enricher types:" in result.stdout

    def test_enricher_list_types_deterministic_output(self):
        """
        Contract B-6: Enricher type discovery MUST be deterministic - the same 
        registry state MUST produce the same discovery results.
        """
        # Run the command multiple times
        result1 = self.runner.invoke(app, ["enricher", "list-types"])
        result2 = self.runner.invoke(app, ["enricher", "list-types"])
        
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        
        # Output should be identical
        assert result1.stdout == result2.stdout

    def test_enricher_list_types_json_deterministic_output(self):
        """
        Contract B-6: JSON output MUST also be deterministic.
        """
        # Run the command multiple times with JSON
        result1 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
        result2 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
        
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        
        # Parse both outputs
        output1 = json.loads(result1.stdout)
        output2 = json.loads(result2.stdout)
        
        # Output should be identical
        assert output1 == output2

    def test_enricher_list_types_registry_error_handling(self):
        """
        Contract B-4: On discovery failure (registry access error), the command 
        MUST exit with code 1 and print a human-readable error message.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.side_effect = Exception("Registry access error")
            
            result = self.runner.invoke(app, ["enricher", "list-types"])
            
            assert result.exit_code == 1
            assert "Error listing enricher types" in result.stderr

    def test_enricher_list_types_empty_registry_handling(self):
        """
        Contract B-8: Empty discovery results (no enricher types) MUST return 
        exit code 0 with message "No enricher types available".
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["enricher", "list-types"])
            
            assert result.exit_code == 0
            assert "No enricher types available" in result.stdout

    def test_enricher_list_types_empty_registry_json_handling(self):
        """
        Contract B-8: Empty discovery results in JSON format MUST return 
        exit code 0 with appropriate JSON structure.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            assert output_data["status"] == "ok"
            assert output_data["enricher_types"] == []
            assert output_data["total"] == 0

    def test_enricher_list_types_human_output_format(self):
        """
        Contract: Human-readable output MUST match the specified format.
        """
        result = self.runner.invoke(app, ["enricher", "list-types"])
        
        assert result.exit_code == 0
        
        # Check for expected format elements
        assert "Available enricher types:" in result.stdout
        assert "Total: 9 enricher types available" in result.stdout
        
        # Check that scope information is NOT displayed (per refactoring)
        assert "Scope:" not in result.stdout

    def test_enricher_list_types_validation_compliance(self):
        """
        Contract B-2: The command MUST validate enricher type compliance and type declarations.
        """
        result = self.runner.invoke(app, ["enricher", "list-types"])
        
        assert result.exit_code == 0
        
        # Verify that both ingest and playout types are properly validated
        assert "ingest" in result.stdout
        assert "playout" in result.stdout
        
        # Verify descriptions are present (indicating proper validation)
        assert "content ingestion" in result.stdout
        assert "playout" in result.stdout
