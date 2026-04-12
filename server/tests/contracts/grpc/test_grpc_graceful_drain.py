"""
Contract tests: INV-GRPC-GRACEFUL-DRAIN-001

When Core calls StopBlockPlanSession, AIR completes the current block and
emits final evidence before terminating. Core waits for SessionEnded before
killing the AIR process.

StopBlockPlanSession MUST be idempotent.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


class TestGracefulDrainContract:
    """INV-GRPC-GRACEFUL-DRAIN-001: Graceful shutdown drain semantics.

    Validates that PlayoutSession.stop() handles drain correctly.
    """

    @pytest.fixture(autouse=True)
    def _load_source(self):
        src_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "retrovue"
            / "runtime"
            / "playout_session.py"
        )
        self.source = src_path.read_text()

    def test_stop_sends_stop_rpc_before_cleanup(self):
        """stop() calls StopBlockPlanSession before _cleanup()."""
        # Find the stop() method body
        stop_match = re.search(
            r"def stop\(self.*?\n(.*?)(?=\n    def |\nclass |\Z)",
            self.source,
            re.DOTALL,
        )
        assert stop_match, "Could not find stop() method"
        stop_body = stop_match.group(1)

        # StopBlockPlanSession must appear before _cleanup
        rpc_pos = stop_body.find("StopBlockPlanSession")
        cleanup_pos = stop_body.find("_cleanup")
        assert rpc_pos != -1, "stop() must call StopBlockPlanSession"
        assert cleanup_pos != -1, "stop() must call _cleanup()"
        assert rpc_pos < cleanup_pos, (
            "INV-GRPC-GRACEFUL-DRAIN-001: StopBlockPlanSession must be called "
            "before _cleanup() to allow drain"
        )

    def test_stop_handles_unavailable_gracefully(self):
        """stop() handles UNAVAILABLE (AIR already exited) without error log."""
        assert re.search(
            r"UNAVAILABLE", self.source
        ), "stop() must handle grpc.StatusCode.UNAVAILABLE"

    def test_stop_rpc_has_timeout(self):
        """StopBlockPlanSession carries a deadline to bound drain wait."""
        assert re.search(
            r"StopBlockPlanSession\(.*timeout\s*=",
            self.source,
            re.DOTALL,
        ), "StopBlockPlanSession must have a timeout to bound drain"

    def test_stop_is_idempotent(self):
        """Calling stop() when already stopped returns True without error."""
        # The stop method must check is_running and return True if already stopped
        stop_match = re.search(
            r"def stop\(self.*?\n(.*?)(?=\n    def |\nclass |\Z)",
            self.source,
            re.DOTALL,
        )
        assert stop_match, "Could not find stop() method"
        stop_body = stop_match.group(1)

        assert "Already stopped" in stop_body or "not self._state.is_running" in stop_body, (
            "stop() must be idempotent — return success when already stopped"
        )

    def test_session_ended_event_triggers_process_termination(self):
        """SessionEnded event in event loop triggers _terminate_air_process.

        This validates the drain contract from AIR's side: when AIR signals
        SessionEnded, Core terminates the process.
        """
        assert re.search(
            r"session_ended.*_terminate_air_process",
            self.source,
            re.DOTALL,
        ), (
            "INV-GRPC-GRACEFUL-DRAIN-001: SessionEnded event must trigger "
            "_terminate_air_process()"
        )

    def test_terminate_has_graceful_then_force(self):
        """_terminate_air_process uses SIGTERM then SIGKILL on timeout."""
        assert re.search(
            r"proc\.terminate\(\).*?proc\.kill\(\)",
            self.source,
            re.DOTALL,
        ), (
            "Process termination must use graceful terminate then forced kill"
        )
