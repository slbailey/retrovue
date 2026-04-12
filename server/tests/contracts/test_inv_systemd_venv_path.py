"""Contract test: systemd units must use server/.venv, not pkg/core/.venv.

The canonical Python venv is at server/.venv. Systemd service units must
reference this path for PATH, VIRTUAL_ENV, and ExecStart.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SYSTEMD_DIR = REPO_ROOT / "config" / "systemd"

SERVICE_FILES = list(SYSTEMD_DIR.glob("retrovue*.service"))


class TestSystemdVenvPaths:
    """Systemd units must use server/.venv exclusively."""

    @pytest.mark.parametrize(
        "service_file",
        SERVICE_FILES,
        ids=lambda p: p.name,
    )
    def test_no_legacy_venv_path(self, service_file: Path):
        content = service_file.read_text()
        assert "pkg/core/.venv" not in content, (
            f"{service_file.name} references legacy pkg/core/.venv path"
        )

    @pytest.mark.parametrize(
        "service_file",
        SERVICE_FILES,
        ids=lambda p: p.name,
    )
    def test_uses_canonical_venv(self, service_file: Path):
        content = service_file.read_text()
        assert "server/.venv" in content, (
            f"{service_file.name} does not reference canonical server/.venv path"
        )
