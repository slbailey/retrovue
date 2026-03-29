"""
INV-LIFECYCLE-TRACEABILITY-001

Contract: A complete viewer session (tune-in → tune-out) must emit structured
lifecycle events in the correct order, all carrying the same session_id
correlation ID so the full lifecycle is traceable in logs.

Expected event sequence for a TS/blockplan viewer session:
  channel_activated  — producer started
  viewer_join        — viewer registered (session_id present)
  viewer_leave       — viewer deregistered (session_id present)
  linger_start       — linger grace period starts

This test drives ChannelManager directly (no PD, no HTTP) with a fake
clock and a stubbed producer so it runs fully in-process and never touches disk.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.channel_manager import ChannelManager

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _LifecycleCapture(logging.Handler):
    """Capture [lifecycle] debug log records emitted by ChannelManager."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.events: list[dict[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "[lifecycle]" not in msg:
            return
        # Parse: [lifecycle] channel=<cid> event=<ev> [key=val ...]
        parts = {}
        for token in msg.split():
            if "=" in token:
                k, _, v = token.partition("=")
                parts[k] = v
        self.events.append(parts)

    def event_names(self) -> list[str]:
        return [e.get("event", "") for e in self.events]

    def events_for(self, event_name: str) -> list[dict[str, str]]:
        return [e for e in self.events if e.get("event") == event_name]


_LOGGER_NAME = "retrovue.runtime.channel_manager"


def _make_cm(linger_expired_cb=None) -> ChannelManager:
    clock = MagicMock()
    clock.now_utc.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    schedule_service = MagicMock()
    block = MagicMock()
    block.start_utc_ms = 1735732800000
    block.duration_ms = 3600000
    schedule_service.get_block_at.return_value = block

    cb = linger_expired_cb if linger_expired_cb is not None else (lambda: None)

    cm = ChannelManager(
        channel_id="trace-test",
        clock=clock,
        schedule_service=schedule_service,
        program_director=MagicMock(),
        resolved_config=TEST_RESOLVED_CONFIG,
        on_linger_expired=cb,
    )
    cm.set_blockplan_mode(True)
    return cm


def _attach_capture(cm: ChannelManager) -> _LifecycleCapture:
    capture = _LifecycleCapture()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    return capture


def _detach_capture(capture: _LifecycleCapture) -> None:
    logging.getLogger(_LOGGER_NAME).removeHandler(capture)


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvLifecycleTraceability:
    """INV-LIFECYCLE-TRACEABILITY-001: end-to-end session must be traceable."""

    def test_channel_activated_event_emitted_on_producer_start(self):
        """channel_activated must fire when _ensure_producer_running() succeeds."""
        cm = _make_cm()
        capture = _attach_capture(cm)

        try:
            mock_producer = MagicMock()
            mock_producer.mode.value = "normal"
            mock_producer.health.return_value = "running"
            mock_producer.start.return_value = True
            mock_producer.get_stream_endpoint.return_value = "/stream/trace-test"

            with patch.object(cm, "_build_producer_for_mode", return_value=mock_producer):
                cm._ensure_producer_running()

            assert "channel_activated" in capture.event_names(), (
                "INV-LIFECYCLE-TRACEABILITY-001: channel_activated event must be emitted "
                "when producer starts successfully."
            )
        finally:
            _detach_capture(capture)

    def test_viewer_join_event_carries_session_id(self):
        """viewer_join event must be emitted with session_id on tune-in.

        _ensure_producer_running is stubbed (no-op) so this test isolates
        the viewer lifecycle events from producer startup mechanics.
        """
        cm = _make_cm()
        capture = _attach_capture(cm)
        session_id = str(uuid.uuid4())

        try:
            # Stub out producer startup so viewer_join can complete
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(session_id, {"source": "test"})

            join_events = capture.events_for("viewer_join")
            assert join_events, (
                "INV-LIFECYCLE-TRACEABILITY-001: viewer_join event must be emitted on tune-in."
            )
            found = any(session_id in str(v) for e in join_events for v in e.values())
            assert found, (
                f"INV-LIFECYCLE-TRACEABILITY-001: viewer_join event must carry "
                f"session_id={session_id}. Found events: {join_events}"
            )
        finally:
            _detach_capture(capture)

    def test_viewer_leave_event_carries_session_id(self):
        """viewer_leave event must be emitted with session_id on tune-out."""
        cm = _make_cm()
        capture = _attach_capture(cm)
        session_id = str(uuid.uuid4())

        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(session_id, {"source": "test"})
                cm.viewer_leave(session_id)

            leave_events = capture.events_for("viewer_leave")
            assert leave_events, (
                "INV-LIFECYCLE-TRACEABILITY-001: viewer_leave event must be emitted on tune-out."
            )
            found = any(session_id in str(v) for e in leave_events for v in e.values())
            assert found, (
                f"INV-LIFECYCLE-TRACEABILITY-001: viewer_leave event must carry "
                f"session_id={session_id}. Found events: {leave_events}"
            )
        finally:
            _detach_capture(capture)

    def test_linger_start_event_emitted_after_last_viewer_leaves(self):
        """linger_start must fire immediately after the last viewer leaves."""
        cm = _make_cm()
        capture = _attach_capture(cm)
        session_id = str(uuid.uuid4())

        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(session_id, {"source": "test"})
                cm.viewer_leave(session_id)

            assert "linger_start" in capture.event_names(), (
                "INV-LIFECYCLE-TRACEABILITY-001: linger_start event must be emitted "
                "when the last viewer leaves."
            )
        finally:
            _detach_capture(capture)

    def test_full_session_event_sequence_is_ordered(self):
        """Full lifecycle events appear in correct causal order:
        viewer_join → viewer_leave → linger_start
        """
        cm = _make_cm()
        capture = _attach_capture(cm)
        session_id = str(uuid.uuid4())

        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(session_id, {"source": "test"})
                cm.viewer_leave(session_id)

            names = capture.event_names()
            assert "viewer_join" in names, "viewer_join missing from lifecycle events"
            assert "viewer_leave" in names, "viewer_leave missing from lifecycle events"
            assert "linger_start" in names, "linger_start missing from lifecycle events"

            join_idx = names.index("viewer_join")
            leave_idx = names.index("viewer_leave")
            linger_idx = names.index("linger_start")

            assert join_idx < leave_idx < linger_idx, (
                f"INV-LIFECYCLE-TRACEABILITY-001: event order violation. "
                f"Expected viewer_join < viewer_leave < linger_start. "
                f"Got indices: join={join_idx}, leave={leave_idx}, linger={linger_idx}. "
                f"Full sequence: {names}"
            )
        finally:
            _detach_capture(capture)

    def test_teardown_event_emitted_on_stop_channel(self):
        """teardown event must fire when stop_channel() is called."""
        cm = _make_cm()
        capture = _attach_capture(cm)

        try:
            cm.stop_channel(reason="test_stop")

            assert "teardown" in capture.event_names(), (
                "INV-LIFECYCLE-TRACEABILITY-001: teardown event must be emitted "
                "when stop_channel() is called."
            )
        finally:
            _detach_capture(capture)
