"""
Data contract tests for `retrovue source list-types` command.

Tests data-layer consistency, registry state, and entity retrievability
as specified in docs/contracts/resources/SourceListTypesContract.md.

This test enforces the data contract rules (D-#) for the source list-types command.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


def create_mock_importer(name):
    """Create a mock importer class that implements ImporterInterface."""
    return type(f'Mock{name.title()}Importer', (), {
        'name': name,
        'get_config_schema': lambda: type('Config', (), {})(),
        'discover': lambda: [],
        'get_help': lambda: {},
        'list_asset_groups': lambda: [],
        'enable_asset_group': lambda x: True,
        'disable_asset_group': lambda x: True,
    })


def create_mock_sources_mapping(importer_names):
    """Create a mock SOURCES mapping for the given importer names."""
    mapping = {}
    for name in importer_names:
        mapping[name] = create_mock_importer(name)
    return mapping


class TestSourceListTypesDataContract:
    """Data contract tests for retrovue source list-types command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_list_types_registry_scan(self):
        """
        Contract D-1: Registry MUST maintain mapping from importer identifiers to importer 
        implementations. Registry returns simple identifiers (strings), not rich objects.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["test-type"]
            mock_sources.get.return_value = create_mock_importer("test-type")
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 0
            mock_list.assert_called_once()
            mock_sources.get.assert_called_once_with("test-type")

    def test_source_list_types_read_only_operations(self):
        """
        Contract D-5: Registry state queries MUST be read-only during enumeration.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.return_value = []
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 0
            
            # Verify only read operations were performed
            mock_list.assert_called_once()
            # No write operations should be called

    def test_source_list_types_no_external_modifications(self):
        """
        Contract D-4: Source type enumeration MUST NOT modify external systems or database tables.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            with patch("retrovue.cli.commands.source.list_importers") as mock_list:
                mock_list.return_value = []
                
                result = self.runner.invoke(app, ["source", "list-types"])
                
                assert result.exit_code == 0
                
                # Verify no database session was created
                mock_session.assert_not_called()

    def test_source_list_types_atomic_discovery(self):
        """
        Contract D-2: CLI MUST resolve importer identifiers to classes and validate 
        ImporterInterface implementation at CLI time.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["plex", "filesystem"]
            mock_sources.get.side_effect = lambda x: create_mock_importer(x)
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Verify atomic operation - all types returned together
            assert output_data["total"] == 2
            assert len(output_data["source_types"]) == 2
            
            # Verify consistency - all types have same structure
            for source_type in output_data["source_types"]:
                assert "type" in source_type
                assert "importer_file" in source_type
                assert "display_name" in source_type
                assert "available" in source_type
                assert "interface_compliant" in source_type
                assert "status" in source_type
            
            mock_list.assert_called_once()
            assert mock_sources.get.call_count == 2

    def test_source_list_types_registry_state_consistency(self):
        """
        Contract D-3: Source type derivation MUST follow {source_type}_importer.py filename pattern.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            # Simulate registry state that changes between calls
            call_count = 0
            def mock_list_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return ["plex"]
                else:
                    return ["filesystem"]

            mock_list.side_effect = mock_list_side_effect
            mock_sources.get.side_effect = lambda x: create_mock_importer(x)

            # First call
            result1 = self.runner.invoke(app, ["source", "list-types", "--json"])
            assert result1.exit_code == 0
            
            # Second call
            result2 = self.runner.invoke(app, ["source", "list-types", "--json"])
            assert result2.exit_code == 0
            
            # Verify different results due to registry state change
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            assert output1["total"] == 1
            assert output2["total"] == 1
            assert output1["source_types"][0]["type"] == "plex"
            assert output2["source_types"][0]["type"] == "filesystem"

    def test_source_list_types_filename_pattern_validation(self):
        """
        Contract D-3: Source type derivation MUST follow {source_type}_importer.py filename pattern.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["plex", "filesystem"]
            mock_sources.get.side_effect = lambda x: create_mock_importer(x)
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should handle both valid filename patterns gracefully
            assert output_data["total"] == 2
            assert len(output_data["source_types"]) == 2
            
            # Verify filename pattern compliance
            for source_type in output_data["source_types"]:
                assert source_type["type"] in ["plex", "filesystem"]
                assert source_type["importer_file"].endswith("_importer.py")

    def test_source_list_types_interface_compliance_validation(self):
        """
        Contract D-5: Interface compliance validation MUST occur at CLI time, not registry time.
        """
        # Create a mock importer that doesn't implement the interface
        broken_importer = type('BrokenImporter', (), {
            'name': 'broken',
            # Missing required methods
        })
        
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["plex", "broken"]
            mock_sources.get.side_effect = lambda x: create_mock_importer("plex") if x == "plex" else broken_importer
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include interface compliance information
            assert output_data["total"] == 2
            source_types = output_data["source_types"]
            
            # Find the compliant and non-compliant types
            compliant_types = [st for st in source_types if st["interface_compliant"]]
            non_compliant_types = [st for st in source_types if not st["interface_compliant"]]
            
            assert len(compliant_types) == 1
            assert len(non_compliant_types) == 1
            assert compliant_types[0]["type"] == "plex"
            assert non_compliant_types[0]["type"] == "broken"

    def test_source_list_types_duplicate_source_type_handling(self):
        """
        Contract D-3: Multiple importers claiming the same source type MUST cause 
        registration failure with clear error message.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            # Simulate duplicate source type scenario
            mock_list.side_effect = Exception("Multiple importers claim source type 'plex'")
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 1
            assert "Error listing source types" in result.stderr or "Error" in result.stderr

    def test_source_list_types_per_type_validation(self):
        """
        Contract D-2: CLI MUST resolve importer identifiers to classes and validate 
        ImporterInterface implementation at CLI time.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["plex", "filesystem"]
            mock_sources.get.side_effect = lambda x: create_mock_importer(x)
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Each source type should be validated
            assert output_data["total"] == 2
            source_types = output_data["source_types"]
            
            # Verify each type has been validated (has required fields)
            for source_type in source_types:
                assert "type" in source_type
                assert "importer_file" in source_type
                assert "display_name" in source_type
                assert "available" in source_type
                assert "interface_compliant" in source_type
                assert "status" in source_type
                assert source_type["type"] in ["plex", "filesystem"]

    def test_source_list_types_error_propagation(self):
        """
        Contract: Registry errors MUST be properly propagated to the CLI layer.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.side_effect = Exception("Registry initialization failed")
            
            result = self.runner.invoke(app, ["source", "list-types"])
            
            assert result.exit_code == 1
            assert "Error listing source types" in result.stderr or "Error" in result.stderr

    def test_source_list_types_json_error_propagation(self):
        """
        Contract: Registry errors MUST be properly propagated in JSON format.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list:
            mock_list.side_effect = Exception("Registry access denied")
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 1
            # JSON output should not be produced on error
            try:
                json.loads(result.stdout)
                pytest.fail("JSON should not be produced on error")
            except json.JSONDecodeError:
                pass  # Expected behavior

    def test_source_list_types_registry_state_isolation(self):
        """
        Contract: Registry state MUST be isolated between different command invocations.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            # First call returns one set of types
            mock_list.return_value = ["plex"]
            mock_sources.get.side_effect = lambda x: create_mock_importer(x)
            
            result1 = self.runner.invoke(app, ["source", "list-types", "--json"])
            assert result1.exit_code == 0
            
            # Second call returns different types (simulating registry state change)
            mock_list.return_value = ["filesystem"]
            
            result2 = self.runner.invoke(app, ["source", "list-types", "--json"])
            assert result2.exit_code == 0
            
            # Parse both outputs
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            # Results should reflect the different registry states
            assert output1["total"] == 1
            assert output2["total"] == 1
            assert output1["source_types"][0]["type"] == "plex"
            assert output2["source_types"][0]["type"] == "filesystem"

    def test_source_list_types_importer_interface_validation(self):
        """
        Contract D-2: CLI MUST resolve importer identifiers to classes and validate 
        ImporterInterface implementation at CLI time.
        """
        # Create a mock importer that doesn't implement the interface
        invalid_importer = type('InvalidImporter', (), {
            'name': 'invalid',
            # Missing required methods
        })
        
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.SOURCES") as mock_sources:
            
            mock_list.return_value = ["valid", "invalid"]
            mock_sources.get.side_effect = lambda x: create_mock_importer("valid") if x == "valid" else invalid_importer
            
            result = self.runner.invoke(app, ["source", "list-types", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include both valid and invalid importers
            assert output_data["total"] == 2
            source_types = output_data["source_types"]
            
            # Verify interface compliance is properly reported
            valid_types = [st for st in source_types if st["interface_compliant"]]
            invalid_types = [st for st in source_types if not st["interface_compliant"]]
            
            assert len(valid_types) == 1
            assert len(invalid_types) == 1
            assert valid_types[0]["type"] == "valid"
            assert invalid_types[0]["type"] == "invalid"
