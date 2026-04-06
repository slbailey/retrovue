"""
INV-LIFECYCLE-OBSERVABILITY-001 — HlsSessionManager structured logging compliance.

Proves that HlsSessionManager lifecycle events (first_viewer, last_viewer,
reap_expiration) emit structured DEBUG-level log lines with key=value fields
and session_id correlation, consistent with ChannelManager format.

Violations tested:
- V8a: first-viewer event must be DEBUG with structured key=value
- V8b: last-viewer event must be DEBUG with structured key=value
- V8c: reap-expiration event must be DEBUG with structured key=value
"""

import logging
import re

import pytest

from retrovue.runtime.hls.session_manager import HlsSessionManager

# Structured lifecycle log pattern: [lifecycle] followed by key=value pairs
# Must contain at minimum: channel=, event=, session_id=
STRUCTURED_LOG_RE = re.compile(
    r"^\[lifecycle\]\s+"
    r"channel=\S+\s+"
    r"event=\S+\s+"
    r".*session_id=\S+"
)


def _collect_debug_lifecycle_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Return all DEBUG records whose message starts with [lifecycle]."""
    return [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "[lifecycle]" in r.getMessage()
    ]


class TestHlsSessionManagerLifecycleObservability:
    """INV-LIFECYCLE-OBSERVABILITY-001 compliance for HlsSessionManager."""

    def test_first_viewer_emits_structured_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """V8a: 0→1 transition must log structured DEBUG event=first_viewer."""
        mgr = HlsSessionManager(channel_id="ch-test", session_timeout_ms=30_000)
        mgr.set_clock(1000)

        with caplog.at_level(logging.DEBUG):
            mgr.touch("sess-001")

        records = _collect_debug_lifecycle_records(caplog)
        assert len(records) == 1, (
            f"Expected exactly 1 structured DEBUG lifecycle record for first_viewer, "
            f"got {len(records)}. All records: {[(r.levelno, r.getMessage()) for r in caplog.records]}"
        )
        msg = records[0].getMessage()
        assert STRUCTURED_LOG_RE.match(msg), (
            f"Log message does not match structured format: {msg!r}"
        )
        assert "event=first_viewer" in msg
        assert "session_id=sess-001" in msg

    def test_last_viewer_emits_structured_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """V8b: 1→0 transition via remove() must log structured DEBUG event=last_viewer."""
        mgr = HlsSessionManager(channel_id="ch-test", session_timeout_ms=30_000)
        mgr.set_clock(1000)
        mgr.touch("sess-001")

        caplog.clear()

        with caplog.at_level(logging.DEBUG):
            mgr.remove("sess-001")

        records = _collect_debug_lifecycle_records(caplog)
        assert len(records) == 1, (
            f"Expected exactly 1 structured DEBUG lifecycle record for last_viewer, "
            f"got {len(records)}. All records: {[(r.levelno, r.getMessage()) for r in caplog.records]}"
        )
        msg = records[0].getMessage()
        assert STRUCTURED_LOG_RE.match(msg), (
            f"Log message does not match structured format: {msg!r}"
        )
        assert "event=last_viewer" in msg
        assert "session_id=sess-001" in msg

    def test_reap_expiration_emits_structured_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """V8c: reap causing 1→0 must log structured DEBUG event=reap_expiration."""
        mgr = HlsSessionManager(channel_id="ch-test", session_timeout_ms=5_000)
        mgr.set_clock(1000)
        mgr.touch("sess-001")

        caplog.clear()

        with caplog.at_level(logging.DEBUG):
            mgr.reap_expired(now_ms=50_000)  # well past timeout

        records = _collect_debug_lifecycle_records(caplog)
        assert len(records) == 1, (
            f"Expected exactly 1 structured DEBUG lifecycle record for reap_expiration, "
            f"got {len(records)}. All records: {[(r.levelno, r.getMessage()) for r in caplog.records]}"
        )
        msg = records[0].getMessage()
        assert STRUCTURED_LOG_RE.match(msg), (
            f"Log message does not match structured format: {msg!r}"
        )
        assert "event=reap_expiration" in msg
        assert "session_id=" in msg

    def test_no_info_level_lifecycle_events(self, caplog: pytest.LogCaptureFixture) -> None:
        """No lifecycle event may use INFO level — all must be DEBUG."""
        mgr = HlsSessionManager(channel_id="ch-test", session_timeout_ms=5_000)
        mgr.set_clock(1000)

        with caplog.at_level(logging.DEBUG):
            mgr.touch("sess-001")
            mgr.remove("sess-001")
            mgr.touch("sess-002")
            mgr.reap_expired(now_ms=50_000)

        info_lifecycle = [
            r for r in caplog.records
            if r.levelno == logging.INFO
            and ("viewer" in r.getMessage().lower() or "expired" in r.getMessage().lower())
        ]
        assert len(info_lifecycle) == 0, (
            f"Found {len(info_lifecycle)} INFO-level lifecycle events — "
            f"INV-LIFECYCLE-OBSERVABILITY-001 requires DEBUG: "
            f"{[r.getMessage() for r in info_lifecycle]}"
        )
