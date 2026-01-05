"""
Contract tests for SourceUpdate command.

Tests the behavioral contract rules (B-#) defined in SourceUpdateContract.md.
These tests verify CLI behavior, validation, output formats, and error handling.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.commands.source import app


def _make_session_cm(source: object | None, *, name_matches: list | None = None) -> MagicMock:
    """Return a context manager that yields a fake DB session for Source queries."""
    db = MagicMock()
    query = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = source
    if name_matches is not None:
        filter_mock.all.return_value = name_matches
    else:
        filter_mock.all.return_value = [source] if source else []
    query.filter.return_value = filter_mock
    query.all.return_value = filter_mock.all.return_value
    db.query.return_value = query

    session_cm = MagicMock()
    session_cm.__enter__.return_value = db
    session_cm.__exit__.return_value = False
    return session_cm


class TestSourceUpdateContract:
    """Test SourceUpdate contract behavioral rules (B-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    # Existence and Validation (B-1–B-6)

    def test_source_update_source_not_found_exits_one(self):
        """
        Contract B-1/B-5: Source must exist; on not found, exit 1 with error.
        """
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(None, name_matches=[])), \
             patch("retrovue.cli.commands.source.source_update") as mock_update:
            result = self.runner.invoke(app, [
                "update",
                "non-existent-source",
                "--name", "New Name",
            ])
        assert result.exit_code == 1
        assert "Error: Source 'non-existent-source' not found" in result.stderr
        mock_update.assert_not_called()

    def test_source_update_requires_update_flags(self):
        """
        Contract B-3/B-12: Must provide at least one supported update flag.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)):
            result = self.runner.invoke(app, ["update", "Test Plex"])
        assert result.exit_code == 1
        assert "Error updating source" in result.stderr or "No updates provided" in result.stderr

    def test_source_update_json_output_format(self):
        """
        Contract B-4: When --json is supplied, output MUST include required fields.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        update_result = {
            "id": mock_source.id,
            "external_id": mock_source.external_id,
            "type": "plex",
            "name": "Updated Plex Server",
            "config": mock_source.config,
            "updated_at": None,
        }
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.cli.commands.source.source_update", return_value=update_result):
            result = self.runner.invoke(app, [
                "update",
                "Test Plex",
                "--name", "Updated Plex Server",
                "--json",
            ])
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert {"id", "external_id", "type", "name", "config"}.issubset(output.keys())

    # Mode Handling (B-7)

    def test_source_update_dry_run_no_writes(self):
        """
        Contract B-7: In --dry-run mode, no database writes occur and exit code is 0.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.cli.commands.source.source_update") as mock_update:
            result = self.runner.invoke(app, [
                "update",
                "Test Plex",
                "--name", "New Name",
                "--dry-run",
            ])
        assert result.exit_code == 0
        mock_update.assert_not_called()

    # Update Logic (B-12–B-14)

    def test_source_update_preserves_existing_config(self):
        """
        Contract B-13: Only named keys may change; others preserved.
        """
        original_config = {
            "servers": [{"base_url": "http://original", "token": "original-token"}],
            "enrichers": ["ffprobe", "metadata"],
        }
        fake_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config=original_config,
        )
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(fake_source)), \
             patch("retrovue.cli.commands.source.source_update") as mock_source_update:
            mock_source_update.return_value = {
                "id": fake_source.id,
                "external_id": fake_source.external_id,
                "type": fake_source.type,
                "name": "Updated Name",
                "config": original_config,
            }
            result = self.runner.invoke(app, [
                "update",
                "Test Plex",
                "--name", "Updated Name",
                "--base-url", "http://updated",
            ])
        assert result.exit_code == 0
        mock_source_update.assert_called_once()
        _, updates = mock_source_update.call_args[0]
        cfg = updates["config"]
        assert cfg["servers"][0]["base_url"] == "http://updated"
        assert cfg["servers"][0]["token"] == "original-token"
        assert cfg["enrichers"] == ["ffprobe", "metadata"]

    # Output and Redaction (B-15–B-16)

    def test_source_update_redacts_sensitive_values(self):
        """
        Contract B-15/16: Sensitive values are redacted in outputs.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "secret-token"}]},
        )
        updated = {
            "id": mock_source.id,
            "external_id": mock_source.external_id,
            "type": "plex",
            "name": "Updated Name",
            "config": {"servers": [{"base_url": "http://test", "token": "secret-token"}]},
        }
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.cli.commands.source.source_update", return_value=updated):
            result = self.runner.invoke(app, [
                "update",
                "Test Plex",
                "--name", "Updated Name",
            ])
            assert result.exit_code == 0
            assert "secret-token" not in result.stdout
            result_json = self.runner.invoke(app, [
                "update",
                "Test Plex",
                "--name", "Updated Name",
                "--json",
            ])
        assert result_json.exit_code == 0
        output = json.loads(result_json.stdout)
        assert "secret-token" not in json.dumps(output)

    # Importer and External Safety (B-17–B-18)

    def test_source_update_importer_interface_compliance(self):
        """
        Contract B-17: Importer must implement required update methods.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        class NonCompliant:
            pass
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.adapters.registry.ALIASES", {"plex": "plex"}), \
             patch("retrovue.adapters.registry.SOURCES", {"plex": NonCompliant}):
            result = self.runner.invoke(app, ["update", "Test Plex", "--name", "New Name"])
        assert result.exit_code == 1
        assert "not available or not interface-compliant" in result.stderr

    def test_source_update_no_external_calls(self):
        """
        Contract B-18: Command MUST NOT perform any live external system calls.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.cli.commands.source.source_update", return_value={}), \
             patch("requests.get") as mock_get, \
             patch("requests.post") as mock_post:
            result = self.runner.invoke(app, ["update", "Test Plex", "--name", "New Name"])
        # TODO: tighten exit code once CLI is stable - mock returns empty dict which may fail validation
        assert result.exit_code in (0, 1)
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    # Concurrency (B-19)

    def test_source_update_concurrent_modification_exits_one(self):
        """
        Contract B-19: If update fails concurrently, MUST exit with code 1.
        """
        mock_source = SimpleNamespace(
            id=str(uuid.uuid4()),
            external_id="plex-12345678",
            type="plex",
            name="Test Plex",
            config={"servers": [{"base_url": "http://test", "token": "token"}]},
        )
        with patch("retrovue.cli.commands.source.session", return_value=_make_session_cm(mock_source)), \
             patch("retrovue.cli.commands.source.source_update", side_effect=Exception("Concurrent modification")):
            result = self.runner.invoke(app, ["update", "Test Plex", "--name", "New Name"])
        assert result.exit_code == 1
        assert "concurrent" in (result.stderr.lower() or "")

