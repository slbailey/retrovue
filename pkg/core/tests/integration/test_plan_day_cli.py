"""
Integration tests for plan-day CLI and plan_day().

Covers: basic planning, artifact immutability, determinism,
invalid date format, unknown channel.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retrovue.cli.plan_day import UnknownChannelError, plan_day
from retrovue.planning.transmission_log_artifact_writer import (
    TransmissionLogArtifactExistsError,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CHANNELS_CONFIG = REPO_ROOT / "config" / "channels.json"
ASSET_CATALOG = REPO_ROOT / "config" / "asset_catalog.json"


@pytest.fixture
def artifact_dir(tmp_path: Path) -> Path:
    return tmp_path


# -----------------------------------------------------------------------------
# 1) Basic planning
# -----------------------------------------------------------------------------


def test_plan_day_writes_tlog_and_jsonl(artifact_dir: Path) -> None:
    """Call plan_day(); assert .tlog and .tlog.jsonl exist."""
    if not CHANNELS_CONFIG.exists():
        pytest.skip("config/channels.json not found (run from repo root)")
    if not ASSET_CATALOG.exists():
        pytest.skip("config/asset_catalog.json not found")

    plan_day(
        channel_id="cheers-24-7",
        broadcast_date=date(2026, 2, 13),
        channels_config_path=CHANNELS_CONFIG,
        artifact_base_path=artifact_dir,
        asset_catalog_path=ASSET_CATALOG,
    )

    channel_dir = artifact_dir / "cheers-24-7"
    tlog = channel_dir / "2026-02-13.tlog"
    jsonl = channel_dir / "2026-02-13.tlog.jsonl"
    assert tlog.exists(), f"Expected {tlog} to exist"
    assert jsonl.exists(), f"Expected {jsonl} to exist"


# -----------------------------------------------------------------------------
# 2) Immutability
# -----------------------------------------------------------------------------


def test_plan_day_second_call_raises_artifact_exists(artifact_dir: Path) -> None:
    """Call plan_day() twice for same channel+date; second raises TransmissionLogArtifactExistsError."""
    if not CHANNELS_CONFIG.exists():
        pytest.skip("config/channels.json not found")
    if not ASSET_CATALOG.exists():
        pytest.skip("config/asset_catalog.json not found")

    plan_day(
        channel_id="cheers-24-7",
        broadcast_date=date(2026, 2, 14),
        channels_config_path=CHANNELS_CONFIG,
        artifact_base_path=artifact_dir,
        asset_catalog_path=ASSET_CATALOG,
    )

    with pytest.raises(TransmissionLogArtifactExistsError):
        plan_day(
            channel_id="cheers-24-7",
            broadcast_date=date(2026, 2, 14),
            channels_config_path=CHANNELS_CONFIG,
            artifact_base_path=artifact_dir,
            asset_catalog_path=ASSET_CATALOG,
        )


# -----------------------------------------------------------------------------
# 3) Determinism
# -----------------------------------------------------------------------------


def test_plan_day_deterministic_same_tlog_bytes(artifact_dir: Path) -> None:
    """Delete artifact, run twice, byte-compare .tlog files; must be identical."""
    if not CHANNELS_CONFIG.exists():
        pytest.skip("config/channels.json not found")
    if not ASSET_CATALOG.exists():
        pytest.skip("config/asset_catalog.json not found")

    channel_id = "cheers-24-7"
    broadcast_date = date(2026, 2, 15)
    channel_dir = artifact_dir / channel_id
    tlog_path = channel_dir / "2026-02-15.tlog"

    plan_day(
        channel_id=channel_id,
        broadcast_date=broadcast_date,
        channels_config_path=CHANNELS_CONFIG,
        artifact_base_path=artifact_dir,
        asset_catalog_path=ASSET_CATALOG,
    )
    first_bytes = tlog_path.read_bytes()

    tlog_path.unlink()
    (channel_dir / "2026-02-15.tlog.jsonl").unlink()

    plan_day(
        channel_id=channel_id,
        broadcast_date=broadcast_date,
        channels_config_path=CHANNELS_CONFIG,
        artifact_base_path=artifact_dir,
        asset_catalog_path=ASSET_CATALOG,
    )
    second_bytes = tlog_path.read_bytes()

    assert first_bytes == second_bytes, "Same inputs must produce identical .tlog bytes"


# -----------------------------------------------------------------------------
# 4) Invalid date format
# -----------------------------------------------------------------------------


def test_plan_day_cli_invalid_date_exits_nonzero() -> None:
    """CLI with invalid --date prints clear message and exits non-zero."""
    from retrovue.cli.main import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["plan-day", "--channel", "cheers-24-7", "--date", "2026-13-45"],
    )
    assert result.exit_code != 0
    combined = result.output + (getattr(result, "stderr", "") or "")
    assert "YYYY-MM-DD" in combined or "Invalid date" in combined


# -----------------------------------------------------------------------------
# 5) Unknown channel
# -----------------------------------------------------------------------------


def test_plan_day_unknown_channel_raises(artifact_dir: Path) -> None:
    """plan_day() with unknown channel_id raises UnknownChannelError."""
    if not CHANNELS_CONFIG.exists():
        pytest.skip("config/channels.json not found")

    with pytest.raises(UnknownChannelError) as exc_info:
        plan_day(
            channel_id="nonexistent-channel-xyz",
            broadcast_date=date(2026, 2, 13),
            channels_config_path=CHANNELS_CONFIG,
            artifact_base_path=artifact_dir,
        )
    assert "nonexistent-channel-xyz" in str(exc_info.value)
