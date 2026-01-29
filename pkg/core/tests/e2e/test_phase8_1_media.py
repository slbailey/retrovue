"""
Phase 8.1 — Air owns MPEG-TS: content only via LoadPreview → AttachStream → SwitchToLive.

Contract: StartChannel (state) → LoadPreview(asset_path) → AttachStream (transport only)
→ SwitchToLive; media output starts only after AttachStream + SwitchToLive success.
GET /channel/mock.ts returns HTTP 200, Content-Type video/mp2t, and MPEG-TS packets (0x47)., Content-Type video/mp2t, and MPEG-TS packets (0x47).

See: pkg/air/docs/contracts/phases/Phase8-1-AirOwnsMpegTs.md
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

# Reuse Phase 8.0 proto/grpc loading
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
    for name in ("samplecontent.mp4", "filler.mp4"):
        p = repo_root / "assets" / name
        if p.is_file():
            return p
    return None


# Stream handler that sends video/mp2t (Phase 8.1)
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


def _run_uds_server_and_http_mp2t(
    uds_path: str,
    http_port: int,
    ready: threading.Event,
    uds_conn_holder: list,
) -> None:
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


@pytest.mark.skipif(
    _grpc_import_error is not None,
    reason=f"Proto/grpc not available: {_grpc_import_error}",
)
def test_phase8_1_load_preview_switch_to_live_ts_stream():
    """StartChannel → LoadPreview → AttachStream → SwitchToLive → GET returns video/mp2t and TS packets."""
    air_exe = _find_retrovue_air()
    if air_exe is None:
        pytest.skip("retrovue_air executable not found (build pkg/air with retrovue_air target)")
    asset_path = _find_sample_asset()
    if asset_path is None:
        pytest.skip("No test asset found (assets/samplecontent.mp4 or assets/filler.mp4)")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not found in PATH (required for Phase 8.1 TS output)")

    with tempfile.TemporaryDirectory(prefix="retrovue_phase8_1_") as tmp:
        uds_path = os.path.join(tmp, "ch_mock.sock")
        http_port = 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            http_port = s.getsockname()[1]

        ready = threading.Event()
        uds_conn_holder: list[socket.socket] = []
        server_thread = threading.Thread(
            target=_run_uds_server_and_http_mp2t,
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

        # Phase 8.1: control-surface-only so engine only tracks preview/live path; service runs ffmpeg
        proc = subprocess.Popen(
            [
                str(air_exe),
                "--port", str(grpc_port),
                "--control-surface-only",
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

            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                start_resp = stub.StartChannel(
                    playout_pb2.StartChannelRequest(
                        channel_id=1,
                        plan_handle="phase81",
                        port=0,
                        program_format_json=_DEFAULT_PROGRAM_FORMAT_JSON,
                    ),
                    timeout=5,
                )
                assert start_resp.success, start_resp.message

                load_resp = stub.LoadPreview(
                    playout_pb2.LoadPreviewRequest(
                        channel_id=1,
                        asset_path=str(asset_path),
                        start_offset_ms=0,
                        hard_stop_time_ms=0,
                    ),
                    timeout=5,
                )
                assert load_resp.success, load_resp.message

                attach_resp = stub.AttachStream(
                    playout_pb2.AttachStreamRequest(
                        channel_id=1,
                        transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                        endpoint=uds_path,
                        replace_existing=False,
                    ),
                    timeout=5,
                )
                assert attach_resp.success, attach_resp.message

                switch_resp = stub.SwitchToLive(
                    playout_pb2.SwitchToLiveRequest(channel_id=1),
                    timeout=5,
                )
                assert switch_resp.success, switch_resp.message

            # Give ffmpeg time to start and produce TS
            time.sleep(1.0)

            r = requests.get(
                f"http://127.0.0.1:{http_port}/channel/mock.ts",
                stream=True,
                timeout=(3, 3),
            )
            assert r.status_code == 200, r.text or r.reason
            ct = r.headers.get("Content-Type", "")
            assert "video/mp2t" in ct or "mp2t" in ct, f"Expected video/mp2t, got Content-Type: {ct}"

            content = b""
            for chunk in r.iter_content(chunk_size=188 * 10):
                content += chunk
                ts_sync_count = content.count(0x47)
                if ts_sync_count >= 10:
                    break
                if len(content) >= 188 * 50:
                    break
            r.close()
            ts_sync_count = content.count(0x47)
            assert ts_sync_count >= 10, (
                f"Expected at least 10 MPEG-TS sync bytes (0x47), got {ts_sync_count} in {len(content)} bytes"
            )

            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stop_resp = stub.StopChannel(
                    playout_pb2.StopChannelRequest(channel_id=1),
                    timeout=5,
                )
                assert stop_resp.success, stop_resp.message
        finally:
            proc.terminate()
            proc.wait(timeout=5)
