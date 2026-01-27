"""
Phase 8.0 — Transport contract (no media).

Contract: Python creates UDS server, Air connects as client and writes bytes (e.g. HELLO\\n).
Python serves them over HTTP. No ffmpeg, TS, or VLC.

See: docs/air/contracts/Phase8-0-Transport.md
"""

from __future__ import annotations

import os
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

# Load proto stubs from core/proto/retrovue without conflicting with src/retrovue.
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
    # playout_pb2_grpc imports "from retrovue import playout_pb2" - need retrovue to expose it
    import types
    _retrovue_proto = types.ModuleType("retrovue")
    _retrovue_proto.playout_pb2 = playout_pb2
    _retrovue_proto.playout_pb2_grpc = playout_pb2_grpc
    sys.modules["retrovue_playout_proto"] = _retrovue_proto
    _spec_pb2.loader.exec_module(playout_pb2)
    # Temporarily inject retrovue => playout_pb2 for the grpc module's import
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
    # __file__ is .../pkg/core/tests/e2e/test_*.py -> parents[4] = repo root
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


# --- UDS server + HTTP stream server ---


class _StreamHandler(BaseHTTPRequestHandler):
    """Serves GET /channels/mock.ts by streaming bytes from the shared client socket."""

    def do_GET(self):
        if self.path.strip("/") == "channels/mock.ts":
            if self.server.stream_socket is None:
                self.send_error(503, "No stream attached")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
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
def test_phase8_0_transport_air_to_http():
    """StartChannel → AttachStream(UDS) → Air writes HELLO → GET /channels/mock.ts returns it."""
    air_exe = _find_retrovue_air()
    if air_exe is None:
        pytest.skip("retrovue_air executable not found (build pkg/air with retrovue_air target)")

    with tempfile.TemporaryDirectory(prefix="retrovue_phase8_") as tmp:
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

        # Start Air gRPC server
        grpc_port = 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            grpc_port = s.getsockname()[1]
        grpc_addr = f"127.0.0.1:{grpc_port}"

        proc = subprocess.Popen(
            [
                str(air_exe),
                "--port", str(grpc_port),
                "--control-surface-only",  # Phase 8.0: no decode/render
            ],
            cwd=str(air_exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # Wait for gRPC to be up
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

            # StartChannel then AttachStream (contract ordering)
            try:
                with grpc.insecure_channel(grpc_addr) as ch:
                    stub = playout_pb2_grpc.PlayoutControlStub(ch)
                    start_resp = stub.StartChannel(
                        playout_pb2.StartChannelRequest(
                            channel_id=1,
                            plan_handle="phase8",
                            port=0,
                        ),
                        timeout=5,
                    )
                    assert start_resp.success, start_resp.message

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
            except Exception:
                raise

            # Give Air time to connect and write a few HELLO lines
            time.sleep(0.4)

            # GET /channels/mock.ts — must get bytes and see HELLO (per-chunk read timeout)
            r = requests.get(
                f"http://127.0.0.1:{http_port}/channels/mock.ts",
                stream=True,
                timeout=(3, 2),  # connect 3s, per-read 2s
            )
            assert r.status_code == 200, r.text or r.reason
            content = b""
            for chunk in r.iter_content(chunk_size=256):
                content += chunk
                if b"HELLO" in content or len(content) >= 50:
                    break
            r.close()
            assert b"HELLO" in content, f"Expected HELLO in stream, got: {content!r}"

            # StopChannel (implies detach)
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
