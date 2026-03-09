"""
Contract test for INV-PLAYLOG-PREFILL-001 traffic passthrough.

Invariant: PlaylistBuilderDaemon MUST forward the channel DSL's traffic
policy and break_config to expand_editorial_block() so that Tier-2
blocks contain interstitial/ad breaks.

Rules covered:
- R-1: When dsl_path contains a traffic section, policy and break_config
       are resolved and passed to expand_editorial_block.
- R-2: When dsl_path is absent or has no traffic section, policy and
       break_config default to None (no crash, no breaks).
- R-3: ProgramDirector passes dsl_path from schedule_config to the daemon.
- R-4: evaluate_once() forwards resolved policy/break_config to
       expand_editorial_block at the actual call site.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# R-1: Traffic policy resolved and forwarded
# ---------------------------------------------------------------------------

class TestTrafficPolicyPassthrough:
    """R-1: expand_editorial_block receives policy + break_config from DSL."""

    def test_daemon_passes_traffic_policy_to_expand(self, tmp_path):
        """Daemon constructed with dsl_path resolves traffic and passes it."""
        # Write a minimal DSL YAML with a traffic section
        dsl_file = tmp_path / "test-channel.yaml"
        dsl_file.write_text(
            "channel: test\n"
            "traffic:\n"
            "  breaks_per_hour: 2\n"
            "  break_duration_minutes: 2\n"
            "  pools:\n"
            "    - source: Interstitials\n"
            "      collection: commercials\n"
        )

        sentinel_policy = object()
        sentinel_break_config = object()

        with patch(
            "retrovue.runtime.playlist_builder_daemon.expand_editorial_block"
        ) as mock_expand, patch(
            "retrovue.runtime.dsl_schedule_service.parse_dsl",
            return_value={"traffic": {"breaks_per_hour": 2}},
        ), patch(
            "retrovue.runtime.traffic_dsl.resolve_traffic_policy",
            return_value=sentinel_policy,
        ), patch(
            "retrovue.runtime.traffic_dsl.resolve_break_config",
            return_value=sentinel_break_config,
        ):
            from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon

            daemon = PlaylistBuilderDaemon(
                "test-channel",
                dsl_path=str(dsl_file),
            )

            assert daemon._traffic_policy is sentinel_policy
            assert daemon._break_config is sentinel_break_config


# ---------------------------------------------------------------------------
# R-2: No traffic section → None defaults
# ---------------------------------------------------------------------------

class TestNoTrafficDefaults:
    """R-2: Without traffic in DSL, policy/break_config are None."""

    def test_no_dsl_path_gives_none(self):
        from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon

        daemon = PlaylistBuilderDaemon("test-channel")
        assert daemon._traffic_policy is None
        assert daemon._break_config is None

    def test_dsl_without_traffic_section_gives_none(self, tmp_path):
        dsl_file = tmp_path / "bare.yaml"
        dsl_file.write_text("channel: bare\nschedule:\n  type: weekly\n")

        with patch(
            "retrovue.runtime.dsl_schedule_service.parse_dsl",
            return_value={"channel": "bare", "schedule": {"type": "weekly"}},
        ):
            from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon

            daemon = PlaylistBuilderDaemon("bare", dsl_path=str(dsl_file))
            assert daemon._traffic_policy is None
            assert daemon._break_config is None


# ---------------------------------------------------------------------------
# R-3: ProgramDirector passes dsl_path
# ---------------------------------------------------------------------------

class TestProgramDirectorDslPath:
    """R-3: ProgramDirector forwards dsl_path to PlaylistBuilderDaemon."""

    def test_dsl_path_forwarded_from_schedule_config(self):
        """The daemon constructor call in _start_playlist_builders passes dsl_path."""
        import inspect
        from retrovue.runtime.program_director import ProgramDirector

        # Read the source of _init_playlog_daemons and verify dsl_path= is present
        source = inspect.getsource(ProgramDirector._init_playlog_daemons)
        assert "dsl_path=" in source, (
            "ProgramDirector._init_playlog_daemons must pass dsl_path= "
            "to PlaylistBuilderDaemon"
        )


# ---------------------------------------------------------------------------
# R-4: evaluate_once forwards policy/break_config at the call site
# ---------------------------------------------------------------------------

class TestExtendForwardsTraffic:
    """R-4: _extend_to_target forwards policy/break_config to expand_editorial_block."""

    def test_expand_called_with_policy_and_break_config(self):
        from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        sentinel_policy = {"type": "sentinel_policy"}
        sentinel_break_config = {"type": "sentinel_break_config"}

        daemon = PlaylistBuilderDaemon("test-channel")
        daemon._traffic_policy = sentinel_policy
        daemon._break_config = sentinel_break_config

        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        fake_block = {
            "block_id": "blk-test-001",
            "start_utc_ms": now_ms,
            "end_utc_ms": now_ms + 1_800_000,
            "segments": [
                {
                    "segment_type": "content",
                    "asset_uri": "/media/test.mp4",
                    "segment_duration_ms": 1_800_000,
                    "asset_start_offset_ms": 0,
                },
            ],
        }

        mock_filled = ScheduledBlock(
            block_id="blk-test-001",
            start_utc_ms=now_ms,
            end_utc_ms=now_ms + 1_800_000,
            segments=[
                ScheduledSegment(
                    segment_type="content",
                    asset_uri="/media/test.mp4",
                    segment_duration_ms=1_800_000,
                    asset_start_offset_ms=0,
                ),
            ],
        )

        mock_db = MagicMock()

        with patch.object(
            daemon, "_load_tier1_blocks", return_value=[fake_block],
        ), patch.object(
            daemon, "_batch_block_exists_in_txlog", return_value=set(),
        ), patch.object(
            daemon, "_get_asset_library", return_value=None,
        ), patch.object(
            daemon, "_write_to_txlog",
        ), patch(
            "retrovue.runtime.playlist_builder_daemon.expand_editorial_block",
            return_value=mock_filled,
        ) as mock_expand:
            # Target: 3 hours of coverage from now
            daemon._extend_to_target(now_ms, 3 * 3_600_000, db=mock_db)

            # THE INVARIANT: expand_editorial_block was called with the
            # daemon's traffic policy and break_config, not None.
            assert mock_expand.called, "expand_editorial_block was never called"
            _, kwargs = mock_expand.call_args
            assert kwargs["policy"] is sentinel_policy, (
                f"Expected sentinel_policy, got {kwargs.get('policy')!r}"
            )
            assert kwargs["break_config"] is sentinel_break_config, (
                f"Expected sentinel_break_config, got {kwargs.get('break_config')!r}"
            )
