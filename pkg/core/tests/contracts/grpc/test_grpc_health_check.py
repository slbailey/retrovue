"""
Contract tests: INV-GRPC-HEALTH-CHECK-001

AIR MUST expose grpc.health.v1.Health for readiness probing.
Core MUST use health probing (not GetVersion) for startup readiness detection.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


class TestHealthCheckContract:
    """INV-GRPC-HEALTH-CHECK-001: Health check readiness probing.

    These tests validate that Core uses grpc.health.v1.Health for
    readiness detection during AIR startup.

    STATUS: GREEN — health probing implemented per GRPC-HARD-007/008.
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

    def test_readiness_uses_health_check_not_get_version(self):
        """_wait_for_grpc uses grpc.health.v1.Health, not GetVersion.

        Core imports grpc_health and uses HealthCheckRequest
        for startup readiness instead of the former GetVersion probe.
        """
        assert re.search(
            r"grpc_health|HealthCheckRequest|health_pb2",
            self.source,
        ), (
            "INV-GRPC-HEALTH-CHECK-001: _wait_for_grpc must use "
            "grpc.health.v1.Health for readiness probing"
        )

    def test_readiness_timeout_configurable(self):
        """Readiness timeout is read from config, not hardcoded.

        playout.grpc.readiness_timeout_seconds config key
        controls the health probe timeout.
        """
        assert re.search(
            r"readiness_timeout_seconds|readiness_timeout",
            self.source,
        ), (
            "INV-GRPC-HEALTH-CHECK-001: readiness timeout must be "
            "configurable via playout.grpc.readiness_timeout_seconds"
        )

    def test_wait_for_grpc_has_configurable_timeout(self):
        """_wait_for_grpc accepts a timeout parameter.

        This is already true (timeout_s parameter exists). This test
        documents the existing behavior as part of the health check
        contract migration path.
        """
        assert re.search(
            r"def _wait_for_grpc\(self,\s*timeout_s",
            self.source,
        ), "_wait_for_grpc must accept timeout_s parameter"
