"""
Contract tests for INV-HLS-QUIET-POLLING-001.

HLS client polling MUST NOT produce per-request log output at INFO level
or above. Playlist and segment GET requests are high-frequency,
low-information events that MUST be suppressed from default log output.
"""

import logging

import pytest

from retrovue.runtime.program_director import HLSAccessFilter


class TestInvHlsQuietPolling:
    """INV-HLS-QUIET-POLLING-001 contract tests."""

    def test_filter_suppresses_hls_playlist_requests(self):
        """GET /hls/{channel_id}/live.m3u8 MUST NOT pass the filter."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/hls/retro-1/live.m3u8", "1.1", 200),
            exc_info=None,
        )
        assert f.filter(record) is False

    def test_filter_suppresses_hls_segment_requests(self):
        """GET /hls/{channel_id}/seg_XXXXX.ts MUST NOT pass the filter."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/hls/retro-1/seg_00042.ts", "1.1", 200),
            exc_info=None,
        )
        assert f.filter(record) is False

    def test_filter_passes_non_hls_requests(self):
        """Non-HLS requests MUST pass the filter."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/channels", "1.1", 200),
            exc_info=None,
        )
        assert f.filter(record) is True

    def test_filter_passes_channel_ts_stream(self):
        """Direct TS stream requests MUST pass the filter."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/channel/retro-1.ts", "1.1", 200),
            exc_info=None,
        )
        assert f.filter(record) is True

    def test_filter_passes_hls_error_responses(self):
        """HLS requests with error status codes MUST pass the filter."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/hls/retro-1/live.m3u8", "1.1", 503),
            exc_info=None,
        )
        assert f.filter(record) is True

    def test_filter_handles_non_tuple_args(self):
        """Filter MUST not crash on unexpected log record formats."""
        f = HLSAccessFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="some other message",
            args=None,
            exc_info=None,
        )
        assert f.filter(record) is True
