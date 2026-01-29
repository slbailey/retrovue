"""
Phase 7 E2E: End-to-end mock channel acceptance.

Sequence:
- 7.0: Minimal TS smoke — one channel, one HTTP client, status 200, bytes flow
- 7.1: Correctness at tune-in — stepped clock, tune in at known times, assert expected asset + offset via probe
- 7.2: Boundary stability — advance clock across boundaries, assert no early/late switches
- 7.3: Drift resistance — many boundaries, same assertions still hold
"""

from __future__ import annotations

import socket
import time
from datetime import datetime, timezone

import pytest
import requests

from retrovue.runtime.channel_stream import ChannelStream, FakeTsSource
from retrovue.runtime.grid import elapsed_in_grid, grid_start
from retrovue.runtime.program_director import ProgramDirector


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Phase 0 grid: 30-min block, program first 20 min, then filler (Phase 7.1 probe)
PROGRAM_DURATION_SECONDS = 20 * 60  # 1200
GRID_MINUTES = 30


def _segment_at_utc_ms(now_utc_ms: int) -> dict:
    """Phase 0 grid: program 0..20min, filler 20..30min. Returns asset_id, start_offset_ms."""
    now = datetime.fromtimestamp(now_utc_ms / 1000.0, tz=timezone.utc)
    start = grid_start(now, GRID_MINUTES)
    elapsed_td = elapsed_in_grid(now, GRID_MINUTES)
    elapsed_sec = elapsed_td.total_seconds()
    if elapsed_sec < PROGRAM_DURATION_SECONDS:
        return {
            "asset_id": "samplecontent",
            "asset_path": "/mock/program",
            "content_type": "program",
            "start_offset_ms": int(elapsed_sec * 1000),
        }
    filler_elapsed_sec = elapsed_sec - PROGRAM_DURATION_SECONDS
    return {
        "asset_id": "filler",
        "asset_path": "/mock/filler",
        "content_type": "filler",
        "start_offset_ms": int(filler_elapsed_sec * 1000),
    }


class _StubChannelManager:
    """Stub manager for Phase 7.0/7.1: tune_in/tune_out, active_producer, optional get_current_segment."""

    def __init__(self, channel_id: str, socket_path: str = "/tmp/phase7-dummy.sock", with_probe: bool = False):
        self.channel_id = channel_id
        self.socket_path = socket_path
        self._sessions: set[str] = set()
        self._with_probe = with_probe

    def tune_in(self, session_id: str, info: dict) -> None:
        self._sessions.add(session_id)

    def tune_out(self, session_id: str) -> None:
        self._sessions.discard(session_id)

    @property
    def active_producer(self) -> object:
        return type("Producer", (), {"socket_path": self.socket_path})()

    def get_current_segment(self, now_utc_ms: int | None = None) -> dict | None:
        """Phase 7.1: Probe for current asset + offset (Phase 0 grid)."""
        if not self._with_probe:
            return None
        if now_utc_ms is None:
            now_utc_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return _segment_at_utc_ms(now_utc_ms)


class _StubChannelManagerProvider:
    """Provider that returns a stub manager for a single channel (e.g. 'mock')."""

    def __init__(self, channel_id: str = "mock", with_probe: bool = False):
        self.channel_id = channel_id
        self._manager = _StubChannelManager(channel_id, with_probe=with_probe)

    def get_channel_manager(self, channel_id: str):
        if channel_id != self.channel_id:
            raise LookupError(f"Unknown channel: {channel_id}")
        return self._manager

    def list_channels(self) -> list[str]:
        return [self.channel_id]


def _start_director(provider: _StubChannelManagerProvider, with_stream_factory: bool = True) -> tuple[ProgramDirector, str]:
    port = _free_port()
    director = ProgramDirector(
        channel_manager_provider=provider,
        host="127.0.0.1",
        port=port,
    )
    if with_stream_factory:
        director._channel_stream_factory = lambda cid, path: ChannelStream(
            cid, ts_source_factory=lambda: FakeTsSource(chunk_size=188 * 10)
        )
    director.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base}/channels", timeout=1)
            if r.status_code == 200:
                return director, base
        except Exception:
            time.sleep(0.1)
    director.stop(timeout=1.0)
    raise RuntimeError("ProgramDirector HTTP server did not become ready")


@pytest.fixture
def phase7_program_director():
    """Start ProgramDirector with stub provider and fake TS source; yield base URL; stop on teardown."""
    provider = _StubChannelManagerProvider("mock")
    director, base = _start_director(provider)
    try:
        yield base
    finally:
        director.stop(timeout=2.0)


@pytest.fixture
def phase7_program_director_with_probe():
    """ProgramDirector with stub that supports get_current_segment (Phase 7.1 probe)."""
    provider = _StubChannelManagerProvider("mock", with_probe=True)
    director, base = _start_director(provider)
    try:
        yield base
    finally:
        director.stop(timeout=2.0)


# --- Phase 7.0: Minimal TS smoke ---

def test_phase7_0_one_channel_http_200_and_bytes_flow(phase7_program_director):
    """
    Phase 7.0: One channel, one HTTP client, status 200, bytes flow.

    - GET /channel/{channel_id}.ts returns 200
    - Content-Type is video/mp2t
    - At least some TS bytes are received (e.g. 1880 = 10 packets)
    """
    base = phase7_program_director
    url = f"{base}/channel/mock.ts"

    with requests.get(url, stream=True, timeout=5) as r:
        assert r.status_code == 200, r.text
        assert r.headers.get("Content-Type", "").split(";")[0].strip() == "video/mp2t"

        # Read a bounded number of bytes to ensure stream starts
        min_bytes = 188 * 10  # 10 TS packets
        received = 0
        for chunk in r.iter_content(chunk_size=4096):
            if not chunk:
                break
            received += len(chunk)
            if received >= min_bytes:
                break

        assert received >= min_bytes, f"Expected at least {min_bytes} bytes, got {received}"


# --- Phase 7.1: Correctness at tune-in (stepped clock, probe) ---

def test_phase7_1_correctness_at_tune_in_asset_and_offset(phase7_program_director_with_probe):
    """
    Phase 7.1: Tune in at known times; assert expected asset + offset via probe.

    Use stepped clock (fixed now_utc_ms). At :02 → samplecontent ~2min offset;
    at :17 → samplecontent ~17min offset; at :29 → filler ~9min into filler.
    """
    base = phase7_program_director_with_probe
    channel_id = "mock"
    # Fixed UTC: 2025-01-01 10:00 block (10:00–10:30)
    base_ts = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp()

    # Tune in (start stream) then probe at :02
    t_02 = int((base_ts + 2 * 60) * 1000)
    with requests.get(f"{base}/channel/{channel_id}.ts", stream=True, timeout=2) as r:
        assert r.status_code == 200
    r2 = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_02},
        timeout=2,
    )
    assert r2.status_code == 200, r2.text
    seg = r2.json()
    assert seg["asset_id"] == "samplecontent"
    assert seg["content_type"] == "program"
    assert 120_000 <= seg["start_offset_ms"] <= 125_000  # ~2 min in ms

    # Probe at :17 (still program)
    t_17 = int((base_ts + 17 * 60) * 1000)
    r3 = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_17},
        timeout=2,
    )
    assert r3.status_code == 200
    seg17 = r3.json()
    assert seg17["asset_id"] == "samplecontent"
    assert 1_020_000 <= seg17["start_offset_ms"] <= 1_025_000  # ~17 min

    # Probe at :29 (filler)
    t_29 = int((base_ts + 29 * 60) * 1000)
    r4 = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_29},
        timeout=2,
    )
    assert r4.status_code == 200
    seg29 = r4.json()
    assert seg29["asset_id"] == "filler"
    assert seg29["content_type"] == "filler"
    assert 540_000 <= seg29["start_offset_ms"] <= 545_000  # 9 min into filler


# --- Phase 7.2: Boundary stability ---

def test_phase7_2_boundary_stability_no_early_late_switch(phase7_program_director_with_probe):
    """
    Phase 7.2: Advance clock across a grid boundary; assert no early/late switch.

    Just before 10:30 → filler. Just after 10:30 → program (new block).
    No program before :30, no filler after :30 at the boundary.
    """
    base = phase7_program_director_with_probe
    channel_id = "mock"
    base_ts = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp()

    # Just before boundary: 10:29:59.9 → still in 10:00–10:30 block, filler
    t_before = int((base_ts + 29 * 60 + 59.9) * 1000)
    r_before = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_before},
        timeout=2,
    )
    assert r_before.status_code == 200
    seg_before = r_before.json()
    assert seg_before["asset_id"] == "filler", "Should still be filler before boundary"

    # Just after boundary: 10:30:00.1 → new block 10:30–11:00, program
    t_after = int((base_ts + 30 * 60 + 0.1) * 1000)
    r_after = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_after},
        timeout=2,
    )
    assert r_after.status_code == 200
    seg_after = r_after.json()
    assert seg_after["asset_id"] == "samplecontent", "Should be program after boundary"
    assert seg_after["start_offset_ms"] < 5000, "Offset into new block should be near 0"


# --- Phase 7.3: Drift resistance ---

def test_phase7_3_drift_resistance_many_boundaries(phase7_program_director_with_probe):
    """
    Phase 7.3: Advance across many boundaries; same assertions still hold (no drift).

    Step through N grid boundaries (e.g. 10:00 → 10:30 → 11:00 → 11:30) and at each
    step assert correct content and that hard-stop / boundaries are still aligned.
    """
    base = phase7_program_director_with_probe
    channel_id = "mock"
    base_ts = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp()

    # Check multiple boundaries: 10:00, 10:30, 11:00, 11:30 (4 blocks)
    # At start of each block we expect program with start_offset_ms ~ 0
    block_starts = [0, 30, 60, 90]  # minutes from base
    for i, mins in enumerate(block_starts):
        t = int((base_ts + mins * 60 + 1) * 1000)  # 1 s into block
        r = requests.get(
            f"{base}/debug/channels/{channel_id}/current-segment",
            params={"now_utc_ms": t},
            timeout=2,
        )
        assert r.status_code == 200, f"Block {i} (min {mins})"
        seg = r.json()
        assert seg["asset_id"] == "samplecontent", f"Block {i} should be program at block start"
        assert seg["start_offset_ms"] <= 2000, f"Block {i} offset should be ~0 (got {seg['start_offset_ms']})"

    # Mid-block filler: 10:25 (5 min into filler segment)
    t_filler = int((base_ts + 25 * 60) * 1000)
    r_filler = requests.get(
        f"{base}/debug/channels/{channel_id}/current-segment",
        params={"now_utc_ms": t_filler},
        timeout=2,
    )
    assert r_filler.status_code == 200
    seg_filler = r_filler.json()
    assert seg_filler["asset_id"] == "filler"
    assert 295_000 <= seg_filler["start_offset_ms"] <= 305_000  # ~5 min into filler
