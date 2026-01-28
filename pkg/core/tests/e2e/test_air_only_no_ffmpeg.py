"""
Air-only runtime: ffmpeg is never launched; 503 when Air unavailable.

- launch_air() raises when Air binary not found (no fallback).
- _launch_ffmpeg_fallback() raises if ever called (removed path).
- GET /channel/{id}.ts returns 503 "Air playout engine unavailable" when Air cannot start.
- No Popen with ffmpeg in the playout path (spy test).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def test_launch_air_raises_when_air_not_found():
    """When Air binary is not found, launch_air raises RuntimeError (no ffmpeg fallback)."""
    from retrovue.usecases import channel_manager_launch

    with patch.object(channel_manager_launch, "_find_air_binary", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            channel_manager_launch.launch_air(
                playout_request={
                    "channel_id": "test-1",
                    "asset_path": "/nonexistent/sample.mp4",
                    "start_pts": 0,
                },
            )
        assert "Air playout engine unavailable" in str(exc_info.value)
        assert "retrovue_air" in str(exc_info.value) or "RETROVUE_AIR_EXE" in str(exc_info.value)


def test_launch_ffmpeg_fallback_raises():
    """_launch_ffmpeg_fallback is disabled and raises (ffmpeg fallback removed)."""
    from retrovue.usecases import channel_manager_launch

    with pytest.raises(RuntimeError) as exc_info:
        channel_manager_launch._launch_ffmpeg_fallback(
            asset_path="/tmp/x.mp4",
            start_pts_ms=0,
            socket_path=Path("/tmp/retrovue/air/ch_1.sock"),
        )
    assert "ffmpeg fallback removed" in str(exc_info.value)
    assert "Air is the only playout engine" in str(exc_info.value)


def test_get_channel_ts_503_when_air_unavailable():
    """GET /channel/{id}.ts returns 503 when Air cannot be started (no placeholder)."""
    import socket
    import threading
    import time

    import requests

    from retrovue.runtime.channel_manager_daemon import ChannelManagerDaemon
    from retrovue.usecases import channel_manager_launch

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    with patch.object(channel_manager_launch, "_find_air_binary", return_value=None):
        daemon = ChannelManagerDaemon(
            schedule_dir=None,
            host="127.0.0.1",
            port=port,
            mock_schedule_ab_mode=True,
            asset_a_path="/tmp/a.mp4",
            asset_b_path="/tmp/b.mp4",
            segment_seconds=10.0,
        )
        t = threading.Thread(target=daemon.start, daemon=True)
        t.start()
        r = None
        for _ in range(100):
            try:
                r = requests.get(
                    f"http://127.0.0.1:{port}/channel/test-1.ts",
                    timeout=(2, 2),
                    stream=True,
                )
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.1)
        else:
            daemon.stop()
            pytest.fail("Server did not start")
        daemon.stop()

    assert r is not None
    assert r.status_code == 503
    assert "Air playout engine unavailable" in (r.text or r.content.decode("utf-8", "replace"))


def test_ffmpeg_never_launched_in_playout_path():
    """When launch_air is used, subprocess.Popen is never called with ffmpeg."""
    from retrovue.usecases import channel_manager_launch

    air_bin = channel_manager_launch._find_air_binary()
    if air_bin is None:
        pytest.skip("retrovue_air not found (build pkg/air); cannot prove Air path")

    seen_popens = []

    real_popen = subprocess.Popen

    def record_popen(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, (list, tuple)):
            cmd_str = " ".join(str(c) for c in cmd)
        else:
            cmd_str = str(cmd)
        seen_popens.append(cmd_str)
        return real_popen(*args, **kwargs)

    with patch("subprocess.Popen", side_effect=record_popen):
        try:
            process, path, queue, _grpc_addr = channel_manager_launch.launch_air(
                playout_request={
                    "channel_id": "test-1",
                    "asset_path": str(air_bin.parent / "nonexistent.mp4"),
                    "start_pts": 0,
                },
            )
        except Exception:
            pass
        else:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    for inv in seen_popens:
        assert "ffmpeg" not in inv.lower(), (
            f"ffmpeg must not be launched in playout path; saw: {inv[:200]}"
        )
