"""MasterClock Contract Tests

Behavioral tests for MasterClockContract.md.
"""

import json

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestMasterClockContract:
    """Contract tests for retrovue test masterclock command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_basic_success_json(self):
        """Test masterclock command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "uses_masterclock_only" in payload
        assert "tzinfo_ok" in payload
        assert "monotonic_ok" in payload
        assert "naive_timestamp_rejected" in payload
        assert "max_skew_seconds" in payload

    def test_masterclock_basic_success_human(self):
        """Test masterclock command with human output."""
        result = self.runner.invoke(app, ["runtime", "masterclock"])
        assert result.exit_code == 0
        assert "masterclock" in result.stdout.lower() or "passed" in result.stdout.lower()

    def test_masterclock_precision_option(self):
        """Test masterclock command accepts precision option."""
        result = self.runner.invoke(
            app, ["runtime", "masterclock", "--precision", "microsecond", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")


class TestMasterClockMonotonicContract:
    """Contract tests for retrovue test masterclock-monotonic command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_monotonic_success_json(self):
        """Test masterclock-monotonic command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock-monotonic", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "monotonic_ok" in payload
        assert "seconds_since_negative_ok" in payload
        assert "future_timestamp_clamp_ok" in payload

    def test_masterclock_monotonic_success_human(self):
        """Test masterclock-monotonic command with human output."""
        result = self.runner.invoke(app, ["runtime", "masterclock-monotonic"])
        assert result.exit_code == 0
        assert "monotonic" in result.stdout.lower() or "passed" in result.stdout.lower()


class TestMasterClockLoggingContract:
    """Contract tests for retrovue test masterclock-logging command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_logging_success_json(self):
        """Test masterclock-logging command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock-logging", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "tzinfo_ok" in payload
        assert "utc_local_consistent" in payload
        assert "precision_maintained" in payload

    def test_masterclock_logging_success_human(self):
        """Test masterclock-logging command with human output."""
        result = self.runner.invoke(app, ["runtime", "masterclock-logging"])
        assert result.exit_code == 0


class TestMasterClockSchedulerAlignmentContract:
    """Contract tests for retrovue test masterclock-scheduler-alignment command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_scheduler_alignment_success_json(self):
        """Test masterclock-scheduler-alignment command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock-scheduler-alignment", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "scheduler_uses_masterclock" in payload
        assert "uses_masterclock_only" in payload
        assert "naive_timestamp_rejected" in payload
        assert "boundary_conditions_ok" in payload
        assert "dst_edge_cases_ok" in payload

    def test_masterclock_scheduler_alignment_success_human(self):
        """Test masterclock-scheduler-alignment command with human output."""
        result = self.runner.invoke(app, ["runtime", "masterclock-scheduler-alignment"])
        assert result.exit_code == 0


class TestMasterClockStabilityContract:
    """Contract tests for retrovue test masterclock-stability command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_stability_success_json(self):
        """Test masterclock-stability command with JSON output matches contract."""
        result = self.runner.invoke(
            app, ["runtime", "masterclock-stability", "--iterations", "100", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "peak_calls_per_second" in payload
        assert "min_calls_per_second" in payload
        assert "final_calls_per_second" in payload

    def test_masterclock_stability_iterations_option(self):
        """Test masterclock-stability command accepts iterations option."""
        result = self.runner.invoke(
            app, ["runtime", "masterclock-stability", "--iterations", "50", "--json"]
        )
        # With 50 iterations, we may not have enough samples (samples every 100), so test may pass or fail
        # The contract allows exit 1 if performance degrades, but we should still get valid JSON
        if result.exit_code == 1:
            # Check that we got valid error JSON
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
        else:
            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload["status"] in ("ok", "error")


class TestMasterClockConsistencyContract:
    """Contract tests for retrovue test masterclock-consistency command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_consistency_success_json(self):
        """Test masterclock-consistency command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock-consistency", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "max_skew_seconds" in payload
        assert "tzinfo_ok" in payload
        assert "roundtrip_ok" in payload
        assert "all_tz_aware" in payload


class TestMasterClockSerializationContract:
    """Contract tests for retrovue test masterclock-serialization command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_serialization_success_json(self):
        """Test masterclock-serialization command with JSON output matches contract."""
        result = self.runner.invoke(app, ["runtime", "masterclock-serialization", "--json"])
        # TODO: tighten exit code once CLI is stable - split into separate tests for success/failure cases
        # Serialization test may fail if timezone preservation fails, but should return valid JSON
        assert result.exit_code in (0, 1)  # Contract allows exit 1 on validation failure
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        assert "roundtrip_ok" in payload
        assert "iso8601_ok" in payload
        assert "tzinfo_preserved" in payload


class TestMasterClockPerformanceContract:
    """Contract tests for retrovue test masterclock-performance command."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_masterclock_performance_success_json(self):
        """Test masterclock-performance command with JSON output matches contract."""
        result = self.runner.invoke(
            app, ["runtime", "masterclock-performance", "--iterations", "100", "--json"]
        )
        # TODO: tighten exit code once CLI is stable - split into separate tests for success/failure cases
        # Performance test may fail if performance degrades or errors occur, but should return valid JSON
        assert result.exit_code in (0, 1)  # Contract allows exit 1 on performance failure
        payload = json.loads(result.stdout)
        assert payload["status"] in ("ok", "error")
        assert "test_passed" in payload
        # On error, check for errors field; on success, check for performance metrics
        if payload["status"] == "error":
            assert "errors" in payload
        else:
            assert "iterations" in payload
            assert "peak_calls_per_second" in payload
            assert "min_calls_per_second" in payload
            assert "final_calls_per_second" in payload

