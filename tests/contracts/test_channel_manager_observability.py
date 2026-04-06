"""
INV-LIFECYCLE-OBSERVABILITY-001 — ChannelManager event_scope and trigger_session_id

Contract: All lifecycle events MUST include event_scope (session|channel).
Session-scoped events MUST include session_id.
Channel-scoped events MAY include trigger_session_id when a single session
clearly caused the transition.

These tests verify the revised invariant requirements added in Phase B:
  - event_scope field present on every lifecycle event
  - trigger_session_id on channel_activated and linger_start
  - first_segment and linger_expire emit event_scope=channel without trigger_session_id
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
# Helpers (same capture pattern as test_inv_lifecycle_traceability.py)
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
        channel_id="obs-test",
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
# event_scope tests
# ---------------------------------------------------------------------------


class TestEventScope:
    """All lifecycle events MUST include event_scope=session|channel."""

    def test_viewer_join_has_event_scope_session(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        sid = str(uuid.uuid4())
        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(sid, {"source": "test"})

            events = capture.events_for("viewer_join")
            assert events, "viewer_join not emitted"
            assert events[0].get("event_scope") == "session", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: viewer_join must have event_scope=session. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_viewer_leave_has_event_scope_session(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        sid = str(uuid.uuid4())
        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(sid, {"source": "test"})
                cm.viewer_leave(sid)

            events = capture.events_for("viewer_leave")
            assert events, "viewer_leave not emitted"
            assert events[0].get("event_scope") == "session", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: viewer_leave must have event_scope=session. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_channel_activated_has_event_scope_channel(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        try:
            mock_producer = MagicMock()
            mock_producer.mode.value = "normal"
            mock_producer.health.return_value = "running"
            mock_producer.start.return_value = True
            mock_producer.get_stream_endpoint.return_value = "/stream/obs-test"

            with patch.object(cm, "_build_producer_for_mode", return_value=mock_producer):
                cm._ensure_producer_running()

            events = capture.events_for("channel_activated")
            assert events, "channel_activated not emitted"
            assert events[0].get("event_scope") == "channel", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: channel_activated must have event_scope=channel. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_linger_start_has_event_scope_channel(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        sid = str(uuid.uuid4())
        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(sid, {"source": "test"})
                cm.viewer_leave(sid)

            events = capture.events_for("linger_start")
            assert events, "linger_start not emitted"
            assert events[0].get("event_scope") == "channel", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: linger_start must have event_scope=channel. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_linger_expire_has_event_scope_channel(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        try:
            # Directly call _linger_expire to simulate timer firing
            cm.runtime_state.viewer_count = 0
            cm._linger_handle = True  # Fake handle so _linger_expire runs
            cm._linger_expire()

            events = capture.events_for("linger_expire")
            assert events, "linger_expire not emitted"
            assert events[0].get("event_scope") == "channel", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: linger_expire must have event_scope=channel. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_teardown_has_event_scope_channel(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        try:
            cm.stop_channel(reason="test_stop")

            events = capture.events_for("teardown")
            assert events, "teardown not emitted"
            assert events[0].get("event_scope") == "channel", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: teardown must have event_scope=channel. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_first_segment_has_event_scope_channel(self):
        cm = _make_cm()
        capture = _attach_capture(cm)
        try:
            # Simulate first segment by setting up segmenter state
            mock_segmenter = MagicMock()
            mock_segmenter.last_completed_index.return_value = 0
            cm._hls_segmenter = mock_segmenter
            cm._hls_segment_counter = 0
            cm._first_segment_logged = False

            cm._update_hls_segment_counter()

            events = capture.events_for("first_segment")
            assert events, "first_segment not emitted"
            assert events[0].get("event_scope") == "channel", (
                f"INV-LIFECYCLE-OBSERVABILITY-001: first_segment must have event_scope=channel. "
                f"Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)


# ---------------------------------------------------------------------------
# trigger_session_id tests
# ---------------------------------------------------------------------------


class TestTriggerSessionId:
    """Channel-scoped events MAY include trigger_session_id when causally linked."""

    def test_channel_activated_includes_trigger_session_id(self):
        """channel_activated must include trigger_session_id of the first viewer."""
        cm = _make_cm()
        capture = _attach_capture(cm)
        sid = str(uuid.uuid4())
        try:
            mock_producer = MagicMock()
            mock_producer.mode.value = "normal"
            mock_producer.health.return_value = "running"
            mock_producer.start.return_value = True
            mock_producer.get_stream_endpoint.return_value = "/stream/obs-test"

            with patch.object(cm, "_build_producer_for_mode", return_value=mock_producer):
                cm.viewer_join(sid, {"source": "test"})

            events = capture.events_for("channel_activated")
            assert events, "channel_activated not emitted"
            assert events[0].get("trigger_session_id") == sid, (
                f"INV-LIFECYCLE-OBSERVABILITY-001: channel_activated must include "
                f"trigger_session_id={sid}. Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_linger_start_includes_trigger_session_id(self):
        """linger_start must include trigger_session_id of the last viewer who left."""
        cm = _make_cm()
        capture = _attach_capture(cm)
        sid = str(uuid.uuid4())
        try:
            with patch.object(cm, "_ensure_producer_running"):
                cm.viewer_join(sid, {"source": "test"})
                cm.viewer_leave(sid)

            events = capture.events_for("linger_start")
            assert events, "linger_start not emitted"
            assert events[0].get("trigger_session_id") == sid, (
                f"INV-LIFECYCLE-OBSERVABILITY-001: linger_start must include "
                f"trigger_session_id={sid}. Got: {events[0]}"
            )
        finally:
            _detach_capture(capture)

    def test_first_segment_does_not_require_trigger_session_id(self):
        """first_segment is not causally linked to a single session."""
        cm = _make_cm()
        capture = _attach_capture(cm)
        try:
            mock_segmenter = MagicMock()
            mock_segmenter.last_completed_index.return_value = 0
            cm._hls_segmenter = mock_segmenter
            cm._hls_segment_counter = 0
            cm._first_segment_logged = False

            cm._update_hls_segment_counter()

            events = capture.events_for("first_segment")
            assert events, "first_segment not emitted"
            # trigger_session_id is allowed but not required
        finally:
            _detach_capture(capture)
