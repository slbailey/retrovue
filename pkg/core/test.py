import grpc
import sys
import socket
import threading
import queue
from pathlib import Path

# Single canonical proto stubs: protos/playout.proto -> pkg/core/core/proto/retrovue
# Need both: parent so "retrovue" package is found; _proto_dir so playout_pb2_grpc's "import playout_pb2" resolves
_proto_dir = Path(__file__).resolve().parent / "core" / "proto" / "retrovue"
sys.path.insert(0, str(_proto_dir))
sys.path.insert(0, str(_proto_dir.parent))
from retrovue import playout_pb2, playout_pb2_grpc

# Create UDS server first (like the launch code does)
socket_path = "/tmp/test_air.sock"
import os
if os.path.exists(socket_path):
    os.unlink(socket_path)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(socket_path)
server.listen(1)
reader_queue = queue.Queue()

def accept_once():
    conn, _ = server.accept()
    reader_queue.put(conn)
    server.close()
threading.Thread(target=accept_once, daemon=True).start()

channel = grpc.insecure_channel('localhost:50051')
stub = playout_pb2_grpc.PlayoutControlStub(channel)

print("1. GetVersion...")
print(stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=5))

print("\n2. StartChannel...")
resp = stub.StartChannel(playout_pb2.StartChannelRequest(
    channel_id=1, plan_handle="test", port=0
), timeout=30)
print(f"   success={resp.success}, message={resp.message}")

print("\n3. LoadPreview...")
resp = stub.LoadPreview(playout_pb2.LoadPreviewRequest(
    channel_id=1,
    asset_path="/opt/retrovue/assets/SampleA.mp4",
    start_offset_ms=0,
    hard_stop_time_ms=0,
), timeout=90)
print(f"   success={resp.success}, message={resp.message}")

print("\n4. SwitchToLive...")
resp = stub.SwitchToLive(playout_pb2.SwitchToLiveRequest(channel_id=1), timeout=30)
print(f"   success={resp.success}, message={resp.message}")

print("\n5. AttachStream...")
resp = stub.AttachStream(playout_pb2.AttachStreamRequest(
    channel_id=1,
    transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
    endpoint=socket_path,
    replace_existing=True,
), timeout=30)
print(f"   success={resp.success}, message={resp.message}")

print("\n6. Waiting for UDS connection...")
try:
    conn = reader_queue.get(timeout=20)
    print(f"   Got connection: {conn}")
    # Read some data
    data = conn.recv(1880)
    print(f"   Received {len(data)} bytes, first 16 hex: {data[:16].hex() if data else 'empty'}")
except queue.Empty:
    print("   TIMEOUT waiting for UDS connection")

print("\nDone!")
