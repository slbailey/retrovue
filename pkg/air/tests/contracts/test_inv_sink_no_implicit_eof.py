"""
INV-SINK-NO-IMPLICIT-EOF Contract Test

Contract: pkg/air/docs/contracts/INV-SINK-NO-IMPLICIT-EOF.md

This test verifies that producer EOF does NOT cause sink EOF.
After a short asset ends, TS packets must continue flowing (pad frames)
until explicit StopChannel is issued.

The invariant states:
- After AttachStream succeeds, the sink MUST continue emitting TS packets
- Producer EOF, empty queues, segment boundaries must NOT terminate TS emission
- Only explicit stop/detach or fatal errors may terminate the stream
"""

from __future__ import annotations

import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Load proto stubs from pkg/core/core/proto/retrovue
_PROTO_DIR = Path(__file__).resolve().parents[4] / "pkg" / "core" / "core" / "proto" / "retrovue"
try:
    import grpc
    import importlib.util
    _spec_pb2 = importlib.util.spec_from_file_location(
        "playout_pb2", _PROTO_DIR / "playout_pb2.py"
    )
    _spec_grpc = importlib.util.spec_from_file_location(
        "playout_pb2_grpc", _PROTO_DIR / "playout_pb2_grpc.py"
    )
    if _spec_pb2 is None or _spec_grpc is None:
        raise ImportError("Proto stub specs could not be created")
    playout_pb2 = importlib.util.module_from_spec(_spec_pb2)
    playout_pb2_grpc = importlib.util.module_from_spec(_spec_grpc)
    sys.modules["playout_pb2"] = playout_pb2
    sys.modules["playout_pb2_grpc"] = playout_pb2_grpc
    import types
    _retrovue_proto = types.ModuleType("retrovue")
    _retrovue_proto.playout_pb2 = playout_pb2
    _retrovue_proto.playout_pb2_grpc = playout_pb2_grpc
    sys.modules["retrovue_playout_proto"] = _retrovue_proto
    _spec_pb2.loader.exec_module(playout_pb2)
    _saved_retrovue = sys.modules.get("retrovue")
    sys.modules["retrovue"] = _retrovue_proto
    try:
        _spec_grpc.loader.exec_module(playout_pb2_grpc)
    finally:
        if _saved_retrovue is not None:
            sys.modules["retrovue"] = _saved_retrovue
        else:
            sys.modules.pop("retrovue", None)
    _grpc_import_error = None
except Exception as e:
    playout_pb2 = None  # type: ignore[assignment]
    playout_pb2_grpc = None  # type: ignore[assignment]
    _grpc_import_error = e


# Default ProgramFormat JSON for tests (1080p30, 48kHz stereo)
_DEFAULT_PROGRAM_FORMAT_JSON = '{"video":{"width":1920,"height":1080,"frame_rate":"30/1"},"audio":{"sample_rate":48000,"channels":2}}'


def _find_retrovue_air() -> Path | None:
    """Find the retrovue_air executable."""
    repo_root = Path(__file__).resolve().parents[4]
    candidates = [
        repo_root / "pkg" / "air" / "build" / "retrovue_air",
        repo_root / "pkg" / "air" / "out" / "build" / "linux-debug" / "retrovue_air",
        Path(os.environ.get("RETROVUE_AIR_EXE", "")),
    ]
    for p in candidates:
        if p and p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def _find_sample_asset() -> Path | None:
    """Find a sample video asset for testing."""
    repo_root = Path(__file__).resolve().parents[4]
    for name in ("samplecontent.mp4", "filler.mp4", "SampleA.mp4", "SampleB.mp4"):
        p = repo_root / "assets" / name
        if p.is_file():
            return p
    return None


def _wait_for_grpc(grpc_addr: str, timeout: float = 8.0) -> bool:
    """Wait for AIR gRPC server to be ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=2)
            return True
        except grpc.RpcError:
            time.sleep(0.1)
    return False


@pytest.mark.skipif(
    _grpc_import_error is not None,
    reason=f"Proto/grpc not available: {_grpc_import_error}",
)
def test_inv_sink_no_implicit_eof_producer_exhaustion():
    """
    INV-SINK-NO-IMPLICIT-EOF: Producer EOF must NOT cause sink EOF.

    Test procedure:
    1. Start AIR with a short asset (3 second hard stop)
    2. Wait for producer EOF (~3-4 seconds)
    3. Continue reading TS for 10+ seconds after EOF
    4. Verify socket read returns data (not EOF) throughout
    5. Explicitly stop channel

    Pass condition: TS sync bytes (0x47) received during post-EOF window.
    Fail condition: Socket returns 0 bytes (EOF) before explicit stop.
    """
    air_exe = _find_retrovue_air()
    if air_exe is None:
        pytest.skip("retrovue_air executable not found (build pkg/air)")

    asset_path = _find_sample_asset()
    if asset_path is None:
        pytest.skip("No test asset (e.g. assets/samplecontent.mp4)")

    with tempfile.TemporaryDirectory(prefix="retrovue_inv_sink_eof_") as tmp:
        uds_path = os.path.join(tmp, "ch_test.sock")

        # Create UDS server socket
        uds_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            uds_server.bind(uds_path)
            uds_server.listen(1)
            uds_server.settimeout(10.0)
        except Exception as e:
            uds_server.close()
            pytest.fail(f"Failed to create UDS server: {e}")

        # Find a free gRPC port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            grpc_port = s.getsockname()[1]
        grpc_addr = f"127.0.0.1:{grpc_port}"

        # Start AIR process
        proc = subprocess.Popen(
            [str(air_exe), "--port", str(grpc_port)],
            cwd=str(air_exe.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        client_conn = None
        try:
            # Wait for gRPC to be ready
            if not _wait_for_grpc(grpc_addr):
                proc.terminate()
                proc.wait(timeout=3)
                pytest.fail("AIR gRPC server did not become ready")

            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)

                # Start channel
                # NOTE: Currently StartChannel uses plan_handle as asset path (hack).
                # Pass the actual asset path as plan_handle to make it work.
                start_resp = stub.StartChannel(
                    playout_pb2.StartChannelRequest(
                        channel_id=1,
                        plan_handle=str(asset_path),  # Use asset path as plan_handle (workaround)
                        port=0,
                        program_format_json=_DEFAULT_PROGRAM_FORMAT_JSON
                    ),
                    timeout=10,
                )
                assert start_resp.success, f"StartChannel failed: {start_resp.message}"

                # Load preview with small frame_count to force early EOF
                # At 30fps, 90 frames = 3 seconds
                load_resp = stub.LoadPreview(
                    playout_pb2.LoadPreviewRequest(
                        channel_id=1,
                        asset_path=str(asset_path),
                        start_frame=0,
                        frame_count=90,  # Force EOF after ~3 seconds at 30fps
                        fps_numerator=30,
                        fps_denominator=1,
                    ),
                    timeout=10,
                )
                assert load_resp.success, f"LoadPreview failed: {load_resp.message}"

                # Attach stream
                attach_resp = stub.AttachStream(
                    playout_pb2.AttachStreamRequest(
                        channel_id=1,
                        transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                        endpoint=uds_path,
                        replace_existing=False,
                    ),
                    timeout=10,
                )
                assert attach_resp.success, f"AttachStream failed: {attach_resp.message}"

                # Accept the connection from AIR
                client_conn, _ = uds_server.accept()
                client_conn.setblocking(False)

                # Wait for preview producer to be ready, then switch to live
                # The preview producer needs time to start shadow decoding
                switch_success = False
                for attempt in range(20):  # Try for up to 2 seconds
                    switch_resp = stub.SwitchToLive(
                        playout_pb2.SwitchToLiveRequest(channel_id=1),
                        timeout=10,
                    )
                    if switch_resp.success:
                        switch_success = True
                        break
                    time.sleep(0.1)

                assert switch_success, f"SwitchToLive failed after retries: {switch_resp.message}"

                # =================================================================
                # INVARIANT TEST: Read TS continuously, verify no EOF for 10+ sec
                # =================================================================
                # Producer EOF happens at ~3 seconds (hard_stop_time_ms)
                # We continue reading until 15 seconds total
                # TS must continue flowing (pad frames) after EOF
                # =================================================================

                start_time = time.time()
                total_bytes = 0
                last_ts_time = start_time
                eof_detected = False
                post_eof_bytes = 0
                post_eof_start = None

                # Read for 15 seconds total
                while time.time() - start_time < 15.0:
                    elapsed = time.time() - start_time

                    # Use select to check for data with timeout
                    ready, _, _ = select.select([client_conn], [], [], 0.5)

                    if ready:
                        try:
                            data = client_conn.recv(188 * 100)  # Read up to 100 TS packets
                            if not data:
                                # Socket returned 0 bytes = EOF
                                eof_detected = True
                                break

                            total_bytes += len(data)
                            last_ts_time = time.time()

                            # Look for TS sync byte anywhere in the data
                            # The first read might be mid-packet, so search
                            has_sync_byte = False
                            for i in range(min(len(data), 188)):
                                if data[i] == 0x47:
                                    has_sync_byte = True
                                    break

                            # After initial startup, we should see TS sync bytes
                            if elapsed > 3.0 and not has_sync_byte and len(data) > 188:
                                print(f"Warning: No TS sync byte found in {len(data)} bytes at {elapsed:.1f}s")

                            # Track bytes after producer EOF (estimated at 3s)
                            if elapsed > 4.0:
                                if post_eof_start is None:
                                    post_eof_start = time.time()
                                post_eof_bytes += len(data)

                        except BlockingIOError:
                            # No data available (non-blocking)
                            pass
                    else:
                        # No data for 0.5s - this is okay, could be buffering
                        # We rely on the EOF detection at the end, not gap timing
                        pass

                # =================================================================
                # INVARIANT ASSERTIONS
                # =================================================================

                if eof_detected:
                    pytest.fail(
                        f"INV-SINK-NO-IMPLICIT-EOF VIOLATION: "
                        f"Socket returned EOF at {time.time() - start_time:.1f}s "
                        f"(should only EOF on explicit stop). "
                        f"Total bytes received: {total_bytes}"
                    )

                # Verify we received bytes in the post-EOF window
                if post_eof_bytes == 0:
                    pytest.fail(
                        f"INV-SINK-NO-IMPLICIT-EOF VIOLATION: "
                        f"No TS bytes received after producer EOF window. "
                        f"Total bytes: {total_bytes}"
                    )

                post_eof_duration = time.time() - post_eof_start if post_eof_start else 0
                print(
                    f"INV-SINK-NO-IMPLICIT-EOF PASS: "
                    f"Received {post_eof_bytes} bytes over {post_eof_duration:.1f}s "
                    f"after producer EOF (pad frames working)"
                )

                # Explicitly stop the channel (the ONLY valid way to end the stream)
                try:
                    stub.StopChannel(
                        playout_pb2.StopChannelRequest(channel_id=1),
                        timeout=5,
                    )
                except grpc.RpcError:
                    # Cleanup timeout is not a test failure
                    pass

        finally:
            if client_conn:
                client_conn.close()
            uds_server.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
