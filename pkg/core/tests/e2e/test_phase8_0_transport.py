"""
Phase 8.0 — Transport contract (TS-oriented).

Contract: Python creates UDS server, Air connects as client and writes real MPEG-TS.
GET /channel/{id}.ts returns bytes starting with TS sync 0x47 (no HELLO).
Runtime is Air-only; no ffmpeg.

See: pkg/air/docs/contracts/phases/Phase8-0-Transport.md
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import pytest
import requests

# Load proto stubs from pkg/core/core/proto/retrovue (canonical: protos/playout.proto)
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

# Default ProgramFormat JSON for tests (1080p30, 48kHz stereo)
_DEFAULT_PROGRAM_FORMAT_JSON = '{"video":{"width":1920,"height":1080,"frame_rate":"30/1"},"audio":{"sample_rate":48000,"channels":2}}'


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
    for name in ("samplecontent.mp4", "filler.mp4", "SampleA.mp4", "SampleB.mp4"):
        p = repo_root / "assets" / name
        if p.is_file():
            return p
    return None


class _StreamHandler(BaseHTTPRequestHandler):
    """Serves GET /channel/mock.ts by streaming bytes from the shared client socket."""

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


def _run_uds_server_and_http(
    uds_path: str,
    http_port: int,
    ready: threading.Event,
    uds_conn_holder: list,
) -> None:
    """Create UDS server, accept one connection, then run HTTP server streaming from it."""
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

    server = HTTPServer(("127.0.0.1", http_port), _StreamHandler)
    server.stream_socket = uds_conn_holder[0] if uds_conn_holder else None
    try:
        server.serve_forever()
    finally:
        server.server_close()


@pytest.mark.skipif(
    _grpc_import_error is not None,
    reason=f"Proto/grpc not available: {_grpc_import_error}",
)
def test_phase8_0_transport_ts_sync_once_live():
    """
    Transport contract: Air connects to UDS and writes real MPEG-TS.
    GET returns bytes; first sync byte must be 0x47 (no HELLO). Air-only.
    """
    air_exe = _find_retrovue_air()
    if air_exe is None:
        pytest.skip("retrovue_air executable not found (build pkg/air)")
    asset_path = _find_sample_asset()
    if asset_path is None:
        pytest.skip("No test asset (e.g. assets/samplecontent.mp4 or assets/SampleA.mp4)")

    with tempfile.TemporaryDirectory(prefix="retrovue_phase8_0_") as tmp:
        uds_path = os.path.join(tmp, "ch_mock.sock")
        http_port = 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            http_port = s.getsockname()[1]

        ready = threading.Event()
        uds_conn_holder: list[socket.socket] = []
        server_thread = threading.Thread(
            target=_run_uds_server_and_http,
            args=(uds_path, http_port, ready, uds_conn_holder),
            daemon=True,
        )
        server_thread.start()
        assert ready.wait(timeout=3.0), "UDS server failed to bind"

        grpc_port = 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            grpc_port = s.getsockname()[1]
        grpc_addr = f"127.0.0.1:{grpc_port}"

        # Air full mode (no --control-surface-only) so real TS after SwitchToLive
        proc = subprocess.Popen(
            [str(air_exe), "--port", str(grpc_port)],
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

            timeout_s = 30
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                start_resp = stub.StartChannel(
                    playout_pb2.StartChannelRequest(
                        channel_id=1, plan_handle="mock", port=0,
                        program_format_json=_DEFAULT_PROGRAM_FORMAT_JSON
                    ),
                    timeout=timeout_s,
                )
                assert start_resp.success, start_resp.message
                assert stub.LoadPreview(
                    playout_pb2.LoadPreviewRequest(
                        channel_id=1,
                        asset_path=str(asset_path),
                        start_offset_ms=0,
                        hard_stop_time_ms=0,
                    ),
                    timeout=timeout_s,
                ).success
                assert stub.AttachStream(
                    playout_pb2.AttachStreamRequest(
                        channel_id=1,
                        transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                        endpoint=uds_path,
                        replace_existing=False,
                    ),
                    timeout=timeout_s,
                ).success
                assert stub.SwitchToLive(
                    playout_pb2.SwitchToLiveRequest(channel_id=1),
                    timeout=timeout_s,
                ).success

            time.sleep(1.5)

            r = requests.get(
                f"http://127.0.0.1:{http_port}/channel/mock.ts",
                stream=True,
                timeout=(3, 5),
            )
            assert r.status_code == 200, r.text or r.reason
            content = b""
            for chunk in r.iter_content(chunk_size=188 * 10):
                content += chunk
                if len(content) >= 188 * 5:
                    break
            r.close()

            assert len(content) >= 1, "Expected at least one byte from stream"
            assert content[0] == 0x47, (
                f"Expected MPEG-TS sync byte 0x47 once live, got first byte 0x{content[0]:02x}; "
                "stream must be real TS from Air, not HELLO."
            )

            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stub.StopChannel(
                    playout_pb2.StopChannelRequest(channel_id=1),
                    timeout=5,
                )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
