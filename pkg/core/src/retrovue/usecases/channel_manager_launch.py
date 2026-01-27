"""
Air (playout engine) process management.

ChannelManager spawns Air processes to play video for the schedule. ChannelManager
must NOT spawn ProgramDirector or the main retrovue process; ProgramDirector
spawns ChannelManager when one doesn't exist for the requested channel. This
module is used by ChannelManager to launch and terminate Air processes.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import subprocess
import time
from pathlib import Path
from typing import Any

# Type alias for subprocess.Process
ProcessHandle = subprocess.Popen[bytes]


def get_uds_socket_path(channel_id: str) -> Path:
    """
    Get the UDS socket path for a channel.
    
    Uses user-writable location:
    - XDG_RUNTIME_DIR/retrovue/air/ (if XDG_RUNTIME_DIR is set)
    - /tmp/retrovue/air/ (fallback)
    
    Args:
        channel_id: Channel identifier
    
    Returns:
        Path to the UDS socket
    """
    # Use XDG_RUNTIME_DIR if available (user-writable)
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        socket_dir = Path(runtime_dir) / "retrovue" / "air"
    else:
        # Fallback to /tmp (user-writable)
        socket_dir = Path("/tmp/retrovue/air")
    
    socket_path = socket_dir / f"channel_{channel_id}.sock"
    return socket_path


def ensure_socket_dir_exists(socket_path: Path) -> None:
    """
    Ensure the directory containing the UDS socket exists.
    
    Args:
        socket_path: Path to the UDS socket
    """
    socket_dir = socket_path.parent
    socket_dir.mkdir(parents=True, exist_ok=True)
    # Ensure directory has proper permissions
    os.chmod(socket_dir, 0o755)


def launch_air(
    *,
    playout_request: dict[str, Any],
    stdin: Any = subprocess.PIPE,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    ts_socket_path: str | Path | None = None,
    use_ffmpeg_fallback: bool = False,  # Deprecated: Phase 0 always uses ffmpeg
) -> tuple[ProcessHandle, Path]:
    """
    Launch the internal playout engine process for a channel.
    
    - Launches the playout engine as child process (or ffmpeg fallback)
    - Sends PlayoutRequest JSON via stdin (Air only)
    - Closes stdin immediately after sending (Air only)
    - Passes --ts-socket-path for UDS TS output
    
    Args:
        playout_request: PlayoutRequest dictionary (asset_path, start_pts, mode, channel_id, metadata)
        stdin: stdin pipe (default: subprocess.PIPE)
        stdout: stdout pipe (default: subprocess.PIPE)
        stderr: stderr pipe (default: subprocess.PIPE)
        ts_socket_path: UDS socket path for TS output. If None, auto-generated.
        use_ffmpeg_fallback: Deprecated - Phase 0 always uses ffmpeg (ignored)
    
    Returns:
        Tuple of (process handle, socket path) for the launched playout engine process
    
    Example:
        ```python
        playout_request = {
            "asset_path": "/path/to/video.mp4",
            "start_pts": 0,
            "mode": "LIVE",
            "channel_id": "retro1",
            "metadata": {}
        }
        process, socket_path = launch_air(playout_request=playout_request, use_ffmpeg_fallback=True)
        ```
    """
    channel_id = playout_request.get("channel_id", "unknown")
    asset_path = playout_request.get("asset_path", "")
    start_pts_ms = playout_request.get("start_pts", 0)
    
    # Generate or use provided UDS socket path
    if ts_socket_path is None:
        socket_path = get_uds_socket_path(channel_id)
    else:
        socket_path = Path(ts_socket_path)
    
    # Ensure socket directory exists
    ensure_socket_dir_exists(socket_path)
    
    # Phase 0: always use ffmpeg fallback (never spawn retrovue_air)
    # For Phase 0, we use ffmpeg to simulate Air
    return _launch_ffmpeg_fallback(
        asset_path=asset_path,
        start_pts_ms=start_pts_ms,
        socket_path=socket_path,
        stdout=stdout,
        stderr=stderr,
    )


def _launch_ffmpeg_fallback(
    asset_path: str,
    start_pts_ms: int,
    socket_path: Path,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> tuple[ProcessHandle, Path]:
    """
    Launch ffmpeg as a fallback to simulate Air playout engine.
    
    Core rule: ffmpeg is a dumb tape deck. RetroVue is the clock.
    
    - Uses input seek (-ss before -i) to reset timestamps and prevent non-monotonic DTS
    - Uses -re for real-time pacing (wall-clock speed output)
    - Never loops media (continuity handled by ChannelManager)
    - Outputs infinite-TS compatible stream to stdout
    - Bridge thread forwards stdout to UDS socket
    
    Args:
        asset_path: Path to video file
        start_pts_ms: Start position in milliseconds (computed by ChannelManager: offset = now - grid_start)
        socket_path: Path to Unix Domain Socket for TS output
        stdout: stdout pipe (default: subprocess.PIPE)
        stderr: stderr pipe (ignored, we always capture stderr)
    
    Returns:
        Tuple of (process handle, socket path)
        
    Note:
        When ffmpeg exits, that segment is complete. ChannelManager will launch the next segment.
    """
    import shutil
    import subprocess
    import socket
    import threading
    
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    
    start_pts_seconds = start_pts_ms / 1000.0
    
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    
    # Create UDS server FIRST
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    
    cmd = [
        ffmpeg,
        "-nostdin",
        "-re",  # Real-time pacing (required for wall-clock speed output)
        "-ss", str(start_pts_seconds),  # Input seek (MUST be before -i to reset timestamps)
        "-i", asset_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "mpegts",
        "-mpegts_flags", "resend_headers+initial_discontinuity",  # Exact order as specified
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-flush_packets", "1",
        "-avoid_negative_ts", "make_zero",
        "-",  # stdout (bridge handles UDS fanout)
    ]
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    
    def log_stderr():
        for line in iter(proc.stderr.readline, b""):
            print("[ffmpeg]", line.decode("utf-8", "replace").rstrip(), flush=True)
    
    threading.Thread(target=log_stderr, daemon=True).start()
    
    def bridge():
        conn = None
        try:
            print(f"[bridge] waiting for UDS client: {socket_path}", flush=True)
            
            # Helper to extract PID from TS packet (188 bytes)
            def get_ts_pid(packet: bytes) -> int | None:
                """Extract PID from TS packet header. Returns None if invalid sync byte."""
                if len(packet) < 4:
                    return None
                if packet[0] != 0x47:  # TS sync byte
                    return None
                # PID is 13 bits: bits 3-7 of byte 1, bits 0-7 of byte 2
                pid = ((packet[1] & 0x1F) << 8) | packet[2]
                return pid
            
            # Startup buffer: capture ~1 second of TS after first PAT (PID 0)
            startup_buffer = bytearray()
            startup_complete = threading.Event()
            pat_seen = threading.Event()
            
            # Ring buffer: keep last ~2MB of TS output (approximately 1593 chunks of 1316 bytes)
            ring_buffer_size = (2 * 1024 * 1024) // 1316  # ~1593 chunks
            ring_buffer = collections.deque(maxlen=ring_buffer_size)
            
            # Queue for live data forwarding (reader -> main thread)
            live_queue = queue.Queue()
            client_connected = threading.Event()
            
            # Reader thread: continuously read from ffmpeg, build startup buffer, fill ring buffer
            def reader():
                capturing_startup = True
                startup_start_time = None
                
                while proc.poll() is None:
                    data = proc.stdout.read(1316)
                    if not data:
                        print("[bridge] ffmpeg stdout EOF", flush=True)
                        break
                    
                    # Check for PAT (PID 0) in TS packets
                    # Each chunk is 1316 bytes = 7 TS packets (1316 / 188 = 7)
                    for i in range(0, len(data), 188):
                        packet = data[i:i+188]
                        if len(packet) == 188:
                            pid = get_ts_pid(packet)
                            if pid == 0:  # PAT found
                                pat_seen.set()
                                if capturing_startup and startup_start_time is None:
                                    startup_start_time = time.time()
                                    print("[bridge] PAT detected, starting startup buffer capture", flush=True)
                    
                    # Build startup buffer: capture ~1 second after first PAT
                    if capturing_startup and pat_seen.is_set():
                        if startup_start_time is None:
                            startup_start_time = time.time()
                        startup_buffer.extend(data)
                        # Capture for ~1 second (at ~1.5Mbps typical, that's ~188KB)
                        if time.time() - startup_start_time >= 1.0:
                            capturing_startup = False
                            startup_complete.set()
                            print(f"[bridge] startup buffer complete ({len(startup_buffer)} bytes)", flush=True)
                    
                    # Add to ring buffer (automatically discards oldest when full)
                    ring_buffer.append(data)
                    
                    # If client is connected, queue for immediate forwarding
                    if client_connected.is_set():
                        try:
                            live_queue.put(data, timeout=0.1)
                        except queue.Full:
                            pass  # Drop if queue full (client can't keep up)
                
                # Signal EOF
                live_queue.put(None)
            
            reader_thread = threading.Thread(target=reader, daemon=True)
            reader_thread.start()
            
            # Wait for startup buffer to be ready (or timeout after 5 seconds)
            if not startup_complete.wait(timeout=5.0):
                print("[bridge] warning: startup buffer not ready after 5s, proceeding anyway", flush=True)
            
            # Wait for client connection
            conn, _ = server.accept()
            print("[bridge] UDS client connected", flush=True)
            client_connected.set()
            
            total = 0
            
            # 1. Send startup buffer first (contains PAT/PMT and initial sync)
            if len(startup_buffer) > 0:
                conn.sendall(startup_buffer)
                total += len(startup_buffer)
                print(f"[bridge] sent {len(startup_buffer)} bytes from startup buffer", flush=True)
            
            # 2. Send last 256-512KB of ring buffer (recent history, not full 2MB)
            # Target: 256-512KB = ~195-390 chunks of 1316 bytes
            ring_send_size = min(len(ring_buffer), 512 * 1024 // 1316)  # ~390 chunks max
            if ring_send_size > 0:
                # Get last N chunks from ring buffer
                ring_chunks = list(ring_buffer)[-ring_send_size:]
                ring_total = 0
                for chunk in ring_chunks:
                    conn.sendall(chunk)
                    ring_total += len(chunk)
                total += ring_total
                print(f"[bridge] sent {ring_total} bytes from ring buffer (last {ring_send_size} chunks)", flush=True)
            
            # 3. Continue streaming live: forward data from queue
            while True:
                try:
                    data = live_queue.get(timeout=1.0)
                    if data is None:  # EOF signal
                        break
                    conn.sendall(data)
                    total += len(data)
                except queue.Empty:
                    # Check if process exited
                    if proc.poll() is not None:
                        break
                    continue
            
            print(f"[bridge] total sent {total} bytes", flush=True)
            
            # Check if ffmpeg exited
            if proc.poll() is not None:
                print(f"[bridge] ffmpeg process exited with code {proc.returncode}", flush=True)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            try:
                server.close()
            except Exception:
                pass
            # Phase 0: Don't unlink socket - ChannelManager will reuse it for next segment
            # The next process will unlink and recreate it
    
    threading.Thread(target=bridge, daemon=True).start()
    
    return proc, socket_path


def terminate_air(process: ProcessHandle) -> None:
    """
    Terminate the internal playout engine process.
    
    - Terminates playout engine process when client_count drops to 0
    
    Args:
        process: Process handle from launch_air()
    
    Example:
        ```python
        process = launch_air(...)
        # ... later ...
        terminate_air(process)
        ```
    """
    if process.poll() is None:  # Process still running
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


__all__ = [
    "launch_air",
    "terminate_air",
    "ProcessHandle",
    "get_uds_socket_path",
    "ensure_socket_dir_exists",
]

