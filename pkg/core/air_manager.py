"""
Air Process Manager - Integration between retrovue_core and retrovue_air.

This module provides functions to launch and manage retrovue_air processes,
parsing JSON events from stdout and managing process lifecycle.
"""

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError


@dataclass
class AirProcessSpec:
    """Specification for launching a retrovue_air process."""
    input_path: str
    port: int
    channel_id: str
    air_bin: str = "retrovue_air"
    ffmpeg_path: Optional[str] = None


class AirProcessState:
    """Thread-safe state container for air process events."""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.ready_event: Optional[dict] = None
        self.last_heartbeat: Optional[dict] = None
        self.all_events: list[dict] = []
    
    def update_event(self, event: dict):
        """Update state with a new event."""
        with self.lock:
            self.all_events.append(event)
            evt_type = event.get("evt")
            if evt_type == "ready":
                self.ready_event = event
            elif evt_type == "heartbeat":
                self.last_heartbeat = event
    
    def get_ready_event(self) -> Optional[dict]:
        """Get the ready event if it has been received."""
        with self.lock:
            return self.ready_event
    
    def has_ready(self) -> bool:
        """Check if ready event has been received."""
        with self.lock:
            return self.ready_event is not None


def _read_stdout_thread(proc: subprocess.Popen, state: AirProcessState):
    """Background thread that reads stdout line-by-line and parses JSON events."""
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            
            try:
                event = json.loads(line)
                if isinstance(event, dict) and "evt" in event:
                    state.update_event(event)
            except json.JSONDecodeError:
                # Ignore non-JSON lines (e.g., stderr might be mixed in)
                pass
    except Exception:
        # Process likely closed stdout
        pass


def _probe_stream_url(stream_url: str, timeout: float = 2.0) -> bool:
    """Probe HTTP endpoint to check if stream is reachable."""
    try:
        with urlopen(stream_url, timeout=timeout) as response:
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def launch_air_channel(
    spec: AirProcessSpec,
    readiness_timeout_s: float = 5.0
) -> tuple[subprocess.Popen, str]:
    """
    Launch a retrovue_air process and wait for it to be ready.
    
    Args:
        spec: Specification for the air process
        readiness_timeout_s: Maximum time to wait for ready event (default: 5.0)
    
    Returns:
        Tuple of (process, stream_url) where stream_url is the HTTP URL to the TS stream
    
    Raises:
        RuntimeError: If process fails to start, times out, or exits unexpectedly
        FileNotFoundError: If air_bin or ffmpeg_path is not found
    """
    # Check if air_bin exists
    air_bin_path = shutil.which(spec.air_bin)
    if not air_bin_path:
        raise FileNotFoundError(f"retrovue_air binary not found: {spec.air_bin}")
    
    # Build command line
    cmd = [
        air_bin_path,
        "--input", spec.input_path,
        "--port", str(spec.port),
        "--channel-id", spec.channel_id,
    ]
    
    if spec.ffmpeg_path:
        cmd.extend(["--ffmpeg", spec.ffmpeg_path])
    
    # Build stream URL
    stream_url = f"http://127.0.0.1:{spec.port}/channel/{spec.channel_id}.ts"
    
    # Start process
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to start retrovue_air process: {e}") from e
    
    # Create state container and start stdout reader thread
    state = AirProcessState()
    reader_thread = threading.Thread(
        target=_read_stdout_thread,
        args=(proc, state),
        daemon=True
    )
    reader_thread.start()
    
    # Wait for ready event
    start_time = time.time()
    ready_received = False
    
    while time.time() - start_time < readiness_timeout_s:
        # Check if process has exited
        if proc.poll() is not None:
            # Process exited before ready
            stderr_output = ""
            if proc.stderr:
                try:
                    stderr_output = proc.stderr.read()
                except Exception:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise RuntimeError(
                f"retrovue_air process exited before ready (code={proc.returncode}). "
                f"stderr: {stderr_output[:500] if stderr_output else '(unavailable)'}"
            )
        
        # Check if ready event received
        if state.has_ready():
            ready_received = True
            break
        
        time.sleep(0.1)
    
    # Fallback: probe HTTP endpoint if no ready event
    if not ready_received:
        if _probe_stream_url(stream_url, timeout=1.0):
            ready_received = True
        else:
            # Timeout - terminate process
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise RuntimeError(
                f"retrovue_air process did not emit ready event within {readiness_timeout_s}s "
                f"and stream endpoint is not reachable"
            )
    
    return (proc, stream_url)


def stop_air(proc: subprocess.Popen, kill_timeout_s: float = 3.0) -> None:
    """
    Stop a retrovue_air process gracefully.
    
    Args:
        proc: The subprocess.Popen object to stop
        kill_timeout_s: Maximum time to wait after SIGTERM before sending SIGKILL
    """
    if proc.poll() is not None:
        # Already exited
        return
    
    # Send SIGTERM
    proc.terminate()
    
    try:
        proc.wait(timeout=kill_timeout_s)
    except subprocess.TimeoutExpired:
        # Still alive, send SIGKILL
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    """Simple smoke test."""
    import sys
    import os
    
    # Try to find a sample MP4 file
    # Check common locations or use first argument
    if len(sys.argv) > 1:
        sample_path = sys.argv[1]
    else:
        # Try some common test file locations
        test_paths = [
            "test_sample.mp4",
            "sample.mp4",
            "/tmp/test.mp4",
        ]
        sample_path = None
        for path in test_paths:
            if os.path.exists(path):
                sample_path = path
                break
        
        if not sample_path:
            print("Usage: python air_manager.py <path_to_sample.mp4>")
            print("Or place a file named 'test_sample.mp4' or 'sample.mp4' in the current directory")
            sys.exit(1)
    
    if not os.path.exists(sample_path):
        print(f"Error: File not found: {sample_path}")
        sys.exit(1)
    
    print(f"Testing with sample file: {sample_path}")
    
    # Create spec
    spec = AirProcessSpec(
        input_path=sample_path,
        port=8090,
        channel_id="test_channel",
    )
    
    try:
        print("Launching air channel...")
        proc, stream_url = launch_air_channel(spec, readiness_timeout_s=5.0)
        print(f"✓ Process started successfully")
        print(f"✓ Stream URL: {stream_url}")
        
        print("Running for 5 seconds...")
        time.sleep(5)
        
        print("Stopping air process...")
        stop_air(proc)
        print("✓ Process stopped successfully")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

