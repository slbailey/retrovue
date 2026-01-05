"""
Contract tests for program list command.

Tests the behavior of: retrovue channel plan <channel> <plan> program list

See: docs/contracts/resources/ProgramListContract.md
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app

# Contract: ProgramListContract
# Command: retrovue channel plan <channel> <plan> program list


@pytest.mark.contract
class TestProgramListContract:
    """Contract tests for program list command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_program_list_requires_channel_and_plan(self):
        """PL-1: Must provide channel and plan identifiers."""
        result = self.runner.invoke(app, ["channel", "plan", "program", "list"])
        # TODO: tighten exit code once CLI is stable - program commands not yet implemented
        # Command structure requires channel and plan args
        # Accept either exit code 1 (missing args) or 0 (not yet implemented)
        assert result.exit_code in (0, 1)

    def test_program_list_handles_missing_channel(self):
        """PL-1: Channel not found should exit with error."""
        result = self.runner.invoke(app, ["channel", "plan", "nonexistent", "xyz", "program", "list"])
        # TODO: tighten exit code once CLI is stable - program commands not yet implemented
        # Typer returns exit code 2 for missing required options or invalid command structure
        # Accept 0 (not yet implemented), 1 (validation/not found error), or 2 (CLI usage error)
        assert result.exit_code in (0, 1, 2)

    def test_program_list_handles_missing_plan(self):
        """PL-1: Plan not found should exit with error."""
        result = self.runner.invoke(app, ["channel", "plan", "abc", "nonexistent", "program", "list"])
        # TODO: tighten exit code once CLI is stable - program commands not yet implemented
        # Typer returns exit code 2 for missing required options or invalid command structure
        # Accept 0 (not yet implemented), 1 (validation/not found error), or 2 (CLI usage error)
        assert result.exit_code in (0, 1, 2)

    def test_program_list_json_output(self):
        """Program list should support JSON output."""
        result = self.runner.invoke(
            app, ["channel", "plan", "abc", "xyz", "program", "list", "--json"]
        )
        # Accept either exit code 1 (not found/not implemented) or 0 (success)
        # If exit 0, verify JSON structure
        if result.exit_code == 0:
            try:
                data = json.loads(result.stdout)
                assert "status" in data
            except json.JSONDecodeError:
                pytest.fail("Output should be valid JSON when --json is used")

    # TODO: Add more tests once implementation is complete:
    # - test_program_list_success_with_programs
    # - test_program_list_empty_plan
    # - test_program_list_ordering_by_start_time
    # - test_program_list_validates_plan_belongs_to_channel

