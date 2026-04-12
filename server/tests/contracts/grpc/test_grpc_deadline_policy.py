"""
Contract tests: INV-GRPC-DEADLINE-POLICY-001

Every PlayoutControl RPC from Core to AIR MUST carry a gRPC deadline.
Deadlines MUST be configurable via playout.grpc.*_timeout_seconds config keys.

These tests validate the Core client (PlayoutSession) deadline behavior
without requiring a live AIR process.
"""
from __future__ import annotations

import inspect
import re
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Source inspection: verify every RPC call site has a timeout parameter
# ---------------------------------------------------------------------------
class TestDeadlinePolicySourceInspection:
    """INV-GRPC-DEADLINE-POLICY-001: Static analysis of PlayoutSession source.

    Every unary gRPC call MUST include a timeout= parameter.
    Streaming RPCs (SubscribeBlockEvents) are exempt.
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

    def test_health_check_has_timeout(self):
        """Health Check RPC (readiness probe) carries a timeout.

        INV-GRPC-HEALTH-CHECK-001 replaced GetVersion with
        grpc.health.v1.Health/Check for readiness probing.
        """
        assert re.search(
            r"health_stub\.Check\(.*timeout\s*=", self.source, re.DOTALL
        ), "Health Check RPC missing timeout parameter"

    def test_attach_stream_has_timeout(self):
        """AttachStream RPC carries a timeout."""
        assert re.search(
            r"\.AttachStream\(.*timeout\s*=", self.source, re.DOTALL
        ), "AttachStream RPC missing timeout parameter"

    def test_start_block_plan_session_has_timeout(self):
        """StartBlockPlanSession RPC carries a timeout."""
        assert re.search(
            r"\.StartBlockPlanSession\(.*timeout\s*=", self.source, re.DOTALL
        ), "StartBlockPlanSession RPC missing timeout parameter"

    def test_feed_block_plan_has_timeout(self):
        """FeedBlockPlan RPC carries a timeout."""
        assert re.search(
            r"\.FeedBlockPlan\(.*timeout\s*=", self.source, re.DOTALL
        ), "FeedBlockPlan RPC missing timeout parameter"

    def test_stop_block_plan_session_has_timeout(self):
        """StopBlockPlanSession RPC carries a timeout."""
        assert re.search(
            r"\.StopBlockPlanSession\(.*timeout\s*=", self.source, re.DOTALL
        ), "StopBlockPlanSession RPC missing timeout parameter"

    def test_subscribe_block_events_no_per_call_deadline(self):
        """SubscribeBlockEvents is streaming — no per-call timeout required."""
        # This is a documentation test: streaming RPCs are exempt.
        # Verify SubscribeBlockEvents does NOT have a timeout= parameter
        # (streaming RPCs use keepalive, not per-call deadlines).
        match = re.search(
            r"\.SubscribeBlockEvents\([^)]*timeout\s*=",
            self.source,
        )
        assert match is None, (
            "SubscribeBlockEvents should not have a per-call timeout "
            "(streaming RPCs use keepalive)"
        )

    def test_no_rpc_call_without_timeout(self):
        """No unary RPC stub call site exists without a timeout parameter.

        Scans for self._stub.<Method>( patterns and verifies each has timeout=.
        Excludes SubscribeBlockEvents (streaming).
        """
        # Find all stub method calls
        stub_calls = re.findall(
            r"self\._stub\.(\w+)\(",
            self.source,
        )
        streaming_rpcs = {"SubscribeBlockEvents"}
        unary_rpcs = [rpc for rpc in stub_calls if rpc not in streaming_rpcs]

        for rpc in unary_rpcs:
            # Find the call site and extract until the closing paren
            # that matches the opening paren of the stub call.
            # Use a simple approach: find the stub call, then scan forward
            # tracking paren depth until we find the matching close.
            call_start = self.source.find(f"self._stub.{rpc}(")
            assert call_start != -1, f"Could not find call site for {rpc}"
            # Find matching closing paren
            depth = 0
            end = call_start
            for i, ch in enumerate(self.source[call_start:], start=call_start):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            call_text = self.source[call_start:end]
            assert "timeout=" in call_text, (
                f"INV-GRPC-DEADLINE-POLICY-001: {rpc} RPC call has no timeout"
            )
