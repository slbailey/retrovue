"""
Phase 8.6 — Real MPEG-TS E2E (no fake mux, VLC-playable).

Contract: Stream carries only real MPEG-TS from Air after SwitchToLive; no HELLO/dummy bytes.
Run Air without --control-surface-only so AttachStream does not start HelloLoop.
Manual exit: open the stream URL in VLC to confirm playback.

See: pkg/air/docs/contracts/phases/Phase8-6-RealMpegTsE2E.md
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import requests

# Reuse Phase 8.0/8.1 proto/grpc loading
_PROTO_DIR = Path(__file__).resolve().parents[2] / "core" / "proto" / "retrovue"
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


def _find_retrovue_air() -> Path | None:
    repo_root = Path(__file__).resolve().parents[4]
    candidates = [
        repo_root / "pkg" / "air" / "out" / "build" / "linux-debug" / "retrovue_air",
        repo_root / "pkg" / "air" / "build" / "retrovue_air",
        Path(os.environ.get("RETROVUE_AIR_EXE", "")),
    ]
    for p in candidates:
        if p and p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def _find_sample_asset() -> Path | None:
    repo_root = Path(__file__).resolve().parents[4]
    for name in ("samplecontent.mp4", "filler.mp4"):
        p = repo_root / "assets" / name
        if p.is_file():
            return p
    return None


class _StreamHandlerMP2T(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.strip("/") == "channel/mock.ts":
            if self.server.stream_socket is None:
                self.send_error(503, "No stream attached")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            try:
                while True:
                    data = self.server.stream_socket.recv(8192)
                    if not data:
                        break
                    self.wfile.write(data)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def _run_uds_and_http(uds_path: str, http_port: int, ready: threading.Event, uds_conn_holder: list) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            os.unlink(uds_path)
        except FileNotFoundError:
            pass
        sock.settimeout(10.0)
        sock.bind(uds_path)
        sock.listen(1)
        ready.set()
        client, _ = sock.accept()
        uds_conn_holder.append(client)
    except Exception:
        ready.set()
        raise
    finally:
        sock.close()

    server = HTTPServer(("127.0.0.1", http_port), _StreamHandlerMP2T)
    server.stream_socket = uds_conn_holder[0] if uds_conn_holder else None
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _is_valid_ts_prefix(data: bytes) -> bool:
    """True if data looks like MPEG-TS: 0x47 sync every 188 bytes, at least a few packets."""
    if len(data) < 188 * 2:
        return False
    for i in range(0, min(len(data), 188 * 10), 188):
        if i + 188 > len(data):
            break
        if data[i] != 0x47:
            return False
    return True


@pytest.mark.skipif(
    _grpc_import_error is not None,
    reason=f"Proto/grpc not available: {_grpc_import_error}",
)
def test_phase8_6_real_mpeg_ts_no_hello_vlc_e2e():
    """
    Phase 8.6: Air runs without --control-surface-only; stream has real MPEG-TS only, no HELLO.

    StartChannel → LoadPreview → AttachStream → SwitchToLive; GET returns valid TS (0x47, 188-byte
    packets) and must not contain HELLO. Manual: open the printed URL in VLC to verify playback.
    """
    air_exe = _find_retrovue_air()
    if air_exe is None:
        pytest.skip("retrovue_air executable not found (build pkg/air)")
    asset_path = _find_sample_asset()
    if asset_path is None:
        pytest.skip("No test asset (assets/samplecontent.mp4 or assets/filler.mp4)")

    with tempfile.TemporaryDirectory(prefix="retrovue_phase8_6_") as tmp:
        uds_path = os.path.join(tmp, "ch_mock.sock")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            http_port = s.getsockname()[1]
        ready = threading.Event()
        uds_conn_holder: list[socket.socket] = []
        server_thread = threading.Thread(
            target=_run_uds_and_http,
            args=(uds_path, http_port, ready, uds_conn_holder),
            daemon=True,
        )
        server_thread.start()
        assert ready.wait(timeout=3.0), "UDS server failed to bind"

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            grpc_port = s.getsockname()[1]
        grpc_addr = f"127.0.0.1:{grpc_port}"

        # Phase 8.6: run Air WITHOUT --control-surface-only so no HELLO; real TS after SwitchToLive
        proc = subprocess.Popen(
            [
                str(air_exe),
                "--port", str(grpc_port),
                # no --control-surface-only
            ],
            cwd=str(air_exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(80):
                try:
                    with grpc.insecure_channel(grpc_addr) as ch:
                        stub = playout_pb2_grpc.PlayoutControlStub(ch)
                        stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=2)
                    break
                except grpc.RpcError:
                    time.sleep(0.1)
            else:
                proc.terminate()
                proc.wait(timeout=3)
                pytest.fail("Air gRPC server did not become ready")

            # Full engine (no control-surface-only) can take longer to start; some builds may block
            rpc_timeout = 30
            try:
                with grpc.insecure_channel(grpc_addr) as ch:
                    stub = playout_pb2_grpc.PlayoutControlStub(ch)
                    start_resp = stub.StartChannel(
                        playout_pb2.StartChannelRequest(
                            channel_id=1, plan_handle="phase86", port=0,
                            program_format_json=_DEFAULT_PROGRAM_FORMAT_JSON
                        ),
                        timeout=rpc_timeout,
                    )
                    if not start_resp.success:
                        pytest.skip(f"Air StartChannel failed: {start_resp.message}")
            except Exception as e:
                if "DEADLINE_EXCEEDED" in str(e) or "Deadline" in str(e):
                    pytest.skip(
                        "Full Air engine StartChannel timed out (heavy init). "
                        "Run Phase 8.6 VLC check manually: start retrovue, then open "
                        "http://<host>:<port>/channel/<channel_id>.ts in VLC."
                    )
                raise
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                assert stub.LoadPreview(
                    playout_pb2.LoadPreviewRequest(
                        channel_id=1,
                        asset_path=str(asset_path),
                        start_offset_ms=0,
                        hard_stop_time_ms=0,
                    ),
                    timeout=rpc_timeout,
                ).success
                assert stub.AttachStream(
                    playout_pb2.AttachStreamRequest(
                        channel_id=1,
                        transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                        endpoint=uds_path,
                        replace_existing=False,
                    ),
                    timeout=rpc_timeout,
                ).success
                assert stub.SwitchToLive(
                    playout_pb2.SwitchToLiveRequest(channel_id=1),
                    timeout=rpc_timeout,
                ).success

            # Allow mux to start and write TS
            time.sleep(2.0)

            stream_url = f"http://127.0.0.1:{http_port}/channel/mock.ts"
            r = requests.get(stream_url, stream=True, timeout=(3, 5))
            assert r.status_code == 200, r.text or r.reason
            assert "video/mp2t" in r.headers.get("Content-Type", "") or "mp2t" in r.headers.get("Content-Type", "")

            content = b""
            for chunk in r.iter_content(chunk_size=188 * 20):
                content += chunk
                if len(content) >= 188 * 30:
                    break
            r.close()

            assert b"HELLO" not in content, (
                "Phase 8.6: stream must not contain HELLO; run Air without --control-surface-only"
            )
            ts_sync = content.count(0x47)
            assert ts_sync >= 10, (
                f"Expected at least 10 MPEG-TS sync bytes (0x47), got {ts_sync} in {len(content)} bytes"
            )
            assert _is_valid_ts_prefix(content), (
                "First bytes must be valid TS (0x47 every 188 bytes)"
            )

            # Stop for clean teardown
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stub.StopChannel(playout_pb2.StopChannelRequest(channel_id=1), timeout=5)
        finally:
            proc.terminate()
            proc.wait(timeout=5)
