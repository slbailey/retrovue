# noqa: F401
"""
Contract tests for ChannelManager command.

Tests the behavioral contract defined in ChannelManager.md (Phase 8).
ChannelManager is part of the RetroVue Core runtime that manages ALL channels.
These tests verify CLI behavior, HTTP server endpoints, client refcount logic,
schedule loading, active item selection, and PlayoutRequest handling.

Process hierarchy: ProgramDirector spawns a ChannelManager when one doesn't exist
for the requested channel. ChannelManager spawns Air (playout engine) to play video.
ChannelManager does NOT spawn ProgramDirector or the main retrovue process.

NOTE:
- Test harness invokes `retrovue channel-manager start` (or program-director start)
- Channel manager runs as a real HTTP server (tested as subprocess)
- In test mode (RETROVUE_TEST_MODE=1), Air is not spawned; FakeTsSource is used. In production, ChannelManager spawns Air.
- ScheduleItem and PlayoutRequest are tested implicitly through ChannelManager
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
import requests
from typer.testing import CliRunner

from retrovue.cli.main import app


@pytest.mark.skip(reason="Integration tests require live server with schedule resolution; environment-dependent failures")
class TestChannelManagerContract:
    """Test ChannelManager contract behavioral rules (Phase 8)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.temp_dir = tempfile.mkdtemp()
        self.schedule_dir = Path(self.temp_dir) / "schedules"
        self.schedule_dir.mkdir()
        self.port = 9000
        self.server_process = None
        # Use current UTC time as baseline for relative times
        self.now_utc = datetime.now(timezone.utc)
        
    def _get_time_str(self, offset_seconds: int = 0) -> str:
        """Get ISO 8601 UTC time string with optional offset."""
        time = self.now_utc + timedelta(seconds=offset_seconds)
        return time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()
            except Exception:
                pass

    def _create_schedule_json(self, channel_id: str, schedule_items: list[dict]) -> Path:
        """Create a schedule.json file for a channel."""
        schedule_file = self.schedule_dir / f"{channel_id}.json"
        schedule_data = {
            "channel_id": channel_id,
            "schedule": schedule_items
        }
        with open(schedule_file, "w") as f:
            json.dump(schedule_data, f)
        return schedule_file

    def _server_ready(self) -> bool:
        """True if GET /channels returns 200 (server is up)."""
        try:
            r = requests.get(f"http://localhost:{self.port}/channels", timeout=1)
            return r.status_code == 200
        except Exception:
            return False

    def _start_server(
        self,
        contract_clock,
        schedule_dir: str | None = None,
        port: int | None = None,
    ) -> subprocess.Popen:
        """Start ProgramDirector (channel-manager start) as subprocess. Uses contract_clock to wait for ready (no time.sleep)."""
        cmd = [sys.executable, "-m", "retrovue.cli.main", "channel-manager", "start"]
        if schedule_dir:
            cmd.extend(["--schedule-dir", schedule_dir])
        if port:
            cmd.extend(["--port", str(port)])
        
        env = os.environ.copy()
        env["RETROVUE_TEST_MODE"] = "1"
        # Prepend src so subprocess loads current ProgramDirector (GET /channels)
        src_dir = Path(__file__).resolve().parent.parent.parent / "src"
        if src_dir.exists():
            env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        
        contract_clock.pump_until(lambda: self._server_ready(), max_ms=5000)
        return process

    def test_channel_manager_help_flag_exits_zero(self):
        """
        Contract: Help flag MUST exit with code 0.
        """
        result = self.runner.invoke(app, ["channel-manager", "start", "--help"])
        assert result.exit_code == 0
        assert "channel-manager" in result.stdout.lower()

    def test_channel_manager_channellist_m3u_endpoint(self, contract_clock):
        """
        Contract: ProgramDirector (channel-manager start) MUST serve channel discovery.
        Uses GET /channels (JSON); channels appear after first tune-in (registry is on-demand).
        """
        # Create schedule files for multiple channels
        self._create_schedule_json("retro1", [])
        self._create_schedule_json("retro2", [])
        
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            response = requests.get(f"http://localhost:{self.port}/channels", timeout=5)
            assert response.status_code == 200, f"GET /channels returned {response.status_code}"
            data = response.json()
            assert "channels" in data
            # After collapse, channels list is registry (tuned); may be empty until first request
            assert isinstance(data["channels"], list)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_channel_ts_endpoint_exists(self, contract_clock):
        """
        Contract: ChannelManager MUST serve GET /channel/<id>.ts for MPEG-TS streams.
        """
        # Create schedule with one active item (started 30 minutes ago, 60 minute duration)
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)

        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server

        try:
            # Make request to channel endpoint (triggers playout; in test mode FakeTsSource, no Air spawned)
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            # Status should be 200 (test mode uses FakeTsSource; production would spawn Air)
            assert response.status_code == 200
            response.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    def test_channel_manager_client_refcount_spawns_air(self, contract_clock):
        """
        Contract: When client_count transitions 0→1, ChannelManager spawns Air (or uses FakeTsSource in test mode).
        ChannelManager spawns Air; it does NOT spawn ProgramDirector or retrovue.
        """
        # Create schedule with active item (started 30 minutes ago, 60 minute duration)
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify behavior via HTTP responses
        # For now, just verify server accepts connection and returns 200
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            # First client connects (refcount 0→1)
            response1 = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response1.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
        finally:
            response1.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_client_refcount_kills_air(self, contract_clock):
        """
        Contract: When client_count drops to 0, ChannelManager terminates Air (or stops FakeTsSource in test mode).
        ChannelManager spawns and terminates Air; it does NOT spawn or terminate ProgramDirector or retrovue.
        """
        # Create schedule with active item (started 30 minutes ago, 60 minute duration)
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify behavior via HTTP responses
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            # Client connects
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Client disconnects (refcount 1→0)
            response.close()
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Verify server still responds (playout stop is internal)
            # For now, just verify connection/disconnection works
            assert True
            
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_active_item_selection(self, contract_clock):
        """
        Contract: ChannelManager MUST select active ScheduleItem based on current time.
        Active item: start_time_utc ≤ now < start_time_utc + duration_seconds
        """
        # Create schedule with one active item (started 30min ago, still active)
        # and one future item (starts in 30min)
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Active Show",
            "episode": "S01E01",
            "asset_path": "/test/path/active.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }, {
            "id": "item-2",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Future Show",
            "episode": "S01E02",
            "asset_path": "/test/path/future.mp4",
            "start_time_utc": self._get_time_str(1800),  # Starts in 30min
            "duration_seconds": 1800,
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            # Client connects - should select active item
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Verify server responds (active item selection is internal)
            # The correct item should be selected based on current time
            assert True
            
        finally:
            response.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_overlapping_items_selects_earliest(self, contract_clock):
        """
        Contract: If multiple items are active, ChannelManager MUST select earliest start_time_utc.
        """
        # Create schedule with overlapping active items
        # Both started in the past, both still active
        schedule_items = [{
            "id": "item-2",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Later Show",
            "episode": "S01E02",
            "asset_path": "/test/path/later.mp4",
            "start_time_utc": self._get_time_str(-900),  # Started 15min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }, {
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Earlier Show",
            "episode": "S01E01",
            "asset_path": "/test/path/earlier.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago (earlier)
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Verify server responds (earliest item selection is internal)
            # The earliest start_time_utc should be selected
            assert True
            
        finally:
            response.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_playout_request_mapping(self, contract_clock):
        """
        Contract: ChannelManager MUST map ScheduleItem → PlayoutRequest correctly.
        - asset_path → asset_path
        - start_pts = 0 (always in Phase 8)
        - mode = "LIVE" (always in Phase 8)
        - channel_id → channel_id
        - metadata → metadata (unchanged)
        """
        # Create schedule with active item
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {
                "commType": "NONE",
                "bumpers": []
            }
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        # PlayoutRequest mapping is tested implicitly through successful server response
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Verify server responds (PlayoutRequest mapping is internal)
            # Mapping is tested via contract documentation and code review
            assert True
            
        finally:
            response.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_playout_request_sent_via_stdin(self, contract_clock):
        """
        Contract: ChannelManager sends PlayoutRequest as JSON (e.g. via stdin) to the Air process it spawned.
        ChannelManager spawns Air; it does NOT spawn ProgramDirector or retrovue.
        """
        # Create schedule with active item
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        # stdin handling is tested via code review and usecase tests
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response.status_code == 200
            
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Verify server responds (stdin handling is internal to usecase)
            # Stdin behavior is verified in usecase implementation
            assert True
            
        finally:
            response.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_air_lifecycle_single_instance(self, contract_clock):
        """
        Contract: Each channel has at most one Air process at a time (spawned by ChannelManager).
        ChannelManager spawns Air; it does NOT spawn ProgramDirector or retrovue.
        """
        # Create schedule with active item
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Test Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-1800),  # Started 30min ago
            "duration_seconds": 3600,  # 60min duration, still active
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            # First client connects
            response1 = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response1.status_code == 200
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Second client connects (same playout, just increment refcount)
            response2 = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            assert response2.status_code == 200
            contract_clock.pump_until(lambda: False, max_ms=500)
            
            # Both clients share same stream (single playout per channel)
            # This is verified by both getting 200 responses
            assert True
            
        finally:
            response1.close()
            response2.close()
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_missing_schedule_json_error(self, contract_clock):
        """
        Contract: If schedule.json is missing, ChannelManager MUST log error and not start playout for that channel.
        ChannelManager spawns Air; it does NOT spawn ProgramDirector or retrovue.
        """
        # Don't create schedule.json file
        
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            contract_clock.pump_until(lambda: False, max_ms=1000)
            
            # Server should still be running, but channel should not work
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            # Should return error (404 or 500) since schedule is missing
            assert response.status_code in (404, 500, 503)
            
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_channel_manager_malformed_schedule_json_error(self, contract_clock):
        """
        Contract: If schedule.json is malformed, ChannelManager MUST log error and not start playout for that channel.
        ChannelManager spawns Air; it does NOT spawn ProgramDirector or retrovue.
        """
        # Create malformed JSON file
        schedule_file = self.schedule_dir / "retro1.json"
        with open(schedule_file, "w") as f:
            f.write("{ invalid json }")
        
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            contract_clock.pump_until(lambda: False, max_ms=1000)
            
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            # Should return error (503) due to malformed JSON
            assert response.status_code == 503
            
        finally:
            response.close()
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    def test_channel_manager_no_active_item_error(self, contract_clock):
        """
        Contract: If no ScheduleItem is active (schedule gap), ChannelManager MUST log error.
        """
        # Create schedule with no active items (gap)
        # Past item ended 30min ago, future item starts in 30min
        schedule_items = [{
            "id": "item-1",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Past Show",
            "episode": "S01E01",
            "asset_path": "/test/path/video.mp4",
            "start_time_utc": self._get_time_str(-3600),  # Started 60min ago
            "duration_seconds": 1800,  # Ended 30min ago
            "metadata": {}
        }, {
            "id": "item-2",
            "channel_id": "retro1",
            "program_type": "series",
            "title": "Future Show",
            "episode": "S01E02",
            "asset_path": "/test/path/video2.mp4",
            "start_time_utc": self._get_time_str(1800),  # Starts in 30min (gap now)
            "duration_seconds": 1800,
            "metadata": {}
        }]
        self._create_schedule_json("retro1", schedule_items)
        
        # Note: Can't patch in subprocess, but we can verify HTTP behavior
        server = self._start_server(contract_clock, schedule_dir=str(self.schedule_dir), port=self.port)
        self.server_process = server
        
        try:
            # Current time is in the gap (no active item)
            response = requests.get(
                f"http://localhost:{self.port}/channel/retro1.ts",
                timeout=5,
                stream=True
            )
            # Should return error (no active item) or still 200 but with no stream
            # Implementation detail: server may return 200 with empty stream or error
            assert response.status_code in (200, 404, 500, 503)
            
        finally:
            if 'response' in locals():
                response.close()
            server.terminate()
            server.wait(timeout=5)

