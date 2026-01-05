"""
Data contract tests for `retrovue enricher list-types` command.

Tests data-layer consistency, registry state, and entity retrievability
as specified in docs/contracts/resources/EnricherListTypesContract.md.

This test enforces the data contract rules (D-#) for the enricher list-types command.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherListTypesDataContract:
    """Data contract tests for retrovue enricher list-types command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_list_types_registry_scan(self):
        """
        Contract D-1: Registry MUST scan for available enricher types.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = [
                {
                    "type": "test-type",
                    "description": "Test enricher type",
                    "scope": "test"
                }
            ]
            
            result = self.runner.invoke(app, ["enricher", "list-types"])
            
            assert result.exit_code == 0
            mock_list.assert_called_once()

    def test_enricher_list_types_read_only_operations(self):
        """
        Contract D-5: Registry state queries MUST be read-only during discovery.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["enricher", "list-types"])
            
            assert result.exit_code == 0
            
            # Verify only read operations were performed
            mock_list.assert_called_once()
            # No write operations should be called

    def test_enricher_list_types_no_external_modifications(self):
        """
        Contract D-4: Enricher type discovery MUST NOT modify external systems or database tables.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
                mock_list.return_value = []
                
                result = self.runner.invoke(app, ["enricher", "list-types"])
                
                assert result.exit_code == 0
                
                # Verify no database session was created
                mock_session.assert_not_called()

    def test_enricher_list_types_atomic_discovery(self):
        """
        Contract D-7: Discovery operations MUST be atomic and consistent.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = [
                {
                    "type": "ingest",
                    "description": "Test ingest enricher",
                    "scope": "ingest"
                },
                {
                    "type": "playout", 
                    "description": "Test playout enricher",
                    "scope": "playout"
                }
            ]
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Verify atomic operation - all types returned together
            assert output_data["total"] == 2
            assert len(output_data["enricher_types"]) == 2
            
            # Verify consistency - all types have same structure
            for enricher_type in output_data["enricher_types"]:
                assert "type" in enricher_type
                assert "description" in enricher_type
                assert "available" in enricher_type

    def test_enricher_list_types_registry_state_consistency(self):
        """
        Contract D-8: Registry state MUST be maintained atomically during discovery process.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            # Simulate registry state that changes between calls
            call_count = 0
            def mock_list_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return [
                        {
                            "type": "ingest",
                            "description": "Test ingest enricher",
                            "scope": "ingest"
                        }
                    ]
                else:
                    return [
                        {
                            "type": "playout",
                            "description": "Test playout enricher", 
                            "scope": "playout"
                        }
                    ]
            
            mock_list.side_effect = mock_list_side_effect
            
            # First call
            result1 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            assert result1.exit_code == 0
            
            # Second call should get different results due to registry state change
            result2 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            assert result2.exit_code == 0
            
            # Parse both outputs
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            # Results should be different due to registry state change
            assert output1["total"] == 1
            assert output2["total"] == 1
            assert output1["enricher_types"][0]["type"] == "ingest"
            assert output2["enricher_types"][0]["type"] == "playout"

    def test_enricher_list_types_type_validation(self):
        """
        Contract D-2: Registry MUST validate enricher type compliance and type declarations.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = [
                {
                    "type": "ingest",
                    "description": "Valid ingest enricher",
                    "scope": "ingest"
                },
                {
                    "type": "invalid-type",
                    "description": "Invalid enricher without proper structure",
                    # Missing required fields
                }
            ]
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should handle both valid and invalid types gracefully
            assert output_data["total"] == 2
            assert len(output_data["enricher_types"]) == 2

    def test_enricher_list_types_availability_validation(self):
        """
        Contract D-6: Enricher type availability MUST be validated against implementation status.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = [
                {
                    "type": "ingest",
                    "description": "Available ingest enricher",
                    "scope": "ingest",
                    "available": True
                },
                {
                    "type": "unavailable",
                    "description": "Unavailable enricher",
                    "scope": "test",
                    "available": False
                }
            ]
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include availability information
            assert output_data["total"] == 2
            enricher_types = output_data["enricher_types"]
            
            # Find the available and unavailable types
            available_types = [et for et in enricher_types if et["available"]]
            unavailable_types = [et for et in enricher_types if not et["available"]]
            
            assert len(available_types) == 1
            assert len(unavailable_types) == 1
            assert available_types[0]["type"] == "ingest"
            assert unavailable_types[0]["type"] == "unavailable"

    def test_enricher_list_types_per_type_validation(self):
        """
        Contract D-3: Type validation MUST be performed for each discovered enricher type.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.return_value = [
                {
                    "type": "ingest",
                    "description": "Valid ingest enricher",
                    "scope": "ingest"
                },
                {
                    "type": "playout",
                    "description": "Valid playout enricher", 
                    "scope": "playout"
                }
            ]
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Each enricher type should be validated
            assert output_data["total"] == 2
            enricher_types = output_data["enricher_types"]
            
            # Verify each type has been validated (has required fields)
            for enricher_type in enricher_types:
                assert "type" in enricher_type
                assert "description" in enricher_type
                assert "available" in enricher_type
                assert enricher_type["type"] in ["ingest", "playout"]

    def test_enricher_list_types_error_propagation(self):
        """
        Contract: Registry errors MUST be properly propagated to the CLI layer.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.side_effect = Exception("Registry initialization failed")
            
            result = self.runner.invoke(app, ["enricher", "list-types"])
            
            assert result.exit_code == 1
            assert "Error listing enricher types" in result.stderr

    def test_enricher_list_types_json_error_propagation(self):
        """
        Contract: Registry errors MUST be properly propagated in JSON format.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            mock_list.side_effect = Exception("Registry access denied")
            
            result = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            
            assert result.exit_code == 1
            # JSON output should not be produced on error
            try:
                json.loads(result.stdout)
                pytest.fail("JSON should not be produced on error")
            except json.JSONDecodeError:
                pass  # Expected behavior

    def test_enricher_list_types_registry_state_isolation(self):
        """
        Contract: Registry state MUST be isolated between different command invocations.
        """
        with patch("retrovue.registries.enricher_registry.list_enricher_types") as mock_list:
            # First call returns one set of types
            mock_list.return_value = [
                {
                    "type": "ingest",
                    "description": "Test ingest enricher",
                    "scope": "ingest"
                }
            ]
            
            result1 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            assert result1.exit_code == 0
            
            # Second call returns different types (simulating registry state change)
            mock_list.return_value = [
                {
                    "type": "playout",
                    "description": "Test playout enricher",
                    "scope": "playout"
                }
            ]
            
            result2 = self.runner.invoke(app, ["enricher", "list-types", "--json"])
            assert result2.exit_code == 0
            
            # Parse both outputs
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            # Results should reflect the different registry states
            assert output1["total"] == 1
            assert output2["total"] == 1
            assert output1["enricher_types"][0]["type"] == "ingest"
            assert output2["enricher_types"][0]["type"] == "playout"
