from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from retrovue.runtime.clock import SystemClock, SteppedClock
from retrovue.runtime.config import InlineChannelConfigProvider, MOCK_CHANNEL_CONFIG
from retrovue.runtime.execution_runtime_reader import DslExecutionRuntimeReader
from retrovue.runtime.program_director import (
    ExecutionReadinessSnapshot,
    ExecutionReadinessFault,
    ProgramDirector,
)
from retrovue.runtime.schedule_types import ScheduledBlock
from retrovue.config.testing import TEST_RESOLVED_CONFIG


def test_program_director_start_stop_without_channels():
    clock = SystemClock()
    director = ProgramDirector(
        clock=clock,
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([MOCK_CHANNEL_CONFIG]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    director.start()
    thread = getattr(director, "_pace_thread", None)
    assert thread is not None
    assert thread.daemon is True
    assert thread.name == "program-director-pace"

    # Give the pacing loop a moment to spin.
    time.sleep(0.05)
    director.stop(timeout=1.0)

    # Second stop should be idempotent.
    director.stop(timeout=1.0)

    thread = getattr(director, "_pace_thread", None)
    assert thread is None or not thread.is_alive()


def test_program_director_stepped_clock_no_sleep():
    clock = SteppedClock()
    director = ProgramDirector(
        clock=clock,
        target_hz=10.0,
        sleep_fn=None,
        channel_config_provider=InlineChannelConfigProvider([MOCK_CHANNEL_CONFIG]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    director.start()
    # Because sleep_fn=None and clock is stepped, advance time so the loop emits ticks.
    clock.advance(0.1)
    time.sleep(0.01)
    director.stop(timeout=1.0)

    thread = getattr(director, "_pace_thread", None)
    assert thread is None or not thread.is_alive()


class _FakeScheduleService:
    def __init__(self, blocks: list[ScheduledBlock], filled_block_ids: set[str]):
        self._blocks = list(blocks)
        self._filled_block_ids = set(filled_block_ids)

    def _find_in_memory_block(self, utc_ms: int) -> ScheduledBlock | None:
        for block in self._blocks:
            if block.start_utc_ms <= utc_ms < block.end_utc_ms:
                return block
        return None

    def _get_filled_block_by_id(self, block_id: str) -> ScheduledBlock | None:
        if block_id not in self._filled_block_ids:
            return None
        for block in self._blocks:
            if block.block_id == block_id:
                return block
        return None


class _FakeExecutionReader:
    def __init__(
        self,
        *,
        current_block: ScheduledBlock | None = None,
        next_block: ScheduledBlock | None = None,
        playlist_events: dict[str, ScheduledBlock] | None = None,
        execution_depth_ms: int = 0,
    ):
        self._current_block = current_block
        self._next_block = next_block
        self._playlist_events = dict(playlist_events or {})
        self._execution_depth_ms = execution_depth_ms

    def get_current_execution_block(self, channel_id: str, now_ms: int):
        return self._current_block

    def get_next_execution_block(self, channel_id: str, after_utc_ms: int):
        return self._next_block

    def get_execution_depth_ms(self, channel_id: str, now_ms: int) -> int:
        return self._execution_depth_ms

    def get_playlist_event_by_block_id(self, channel_id: str, block_id: str):
        return self._playlist_events.get(block_id)


def test_validate_execution_ready_returns_success_snapshot(monkeypatch):
    channel_config = replace(
        MOCK_CHANNEL_CONFIG,
        schedule_config={
            **(MOCK_CHANNEL_CONFIG.schedule_config or {}),
            "playlog_min_hours": 1,
        },
    )
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    block_a = ScheduledBlock("block-a", 1_000, 2_000, ())
    block_b = ScheduledBlock("block-b", 2_000, 3_000, ())
    execution_reader = _FakeExecutionReader(
        current_block=block_a,
        next_block=block_b,
        playlist_events={"block-a": block_a, "block-b": block_b},
        execution_depth_ms=3_604_000,
    )
    monkeypatch.setattr(
        director,
        "_get_execution_reader_for_channel",
        lambda channel_id, config: execution_reader,
    )
    director._playlog_daemons[channel_config.channel_id] = SimpleNamespace(
        get_health_report=lambda: SimpleNamespace(
            farthest_block_end_utc_ms=3_605_500,
            is_healthy=True,
            last_evaluation_utc_ms=999,
        )
    )

    snapshot = director._validate_execution_ready(channel_config.channel_id, 1_500)

    assert snapshot.channel_id == channel_config.channel_id
    assert snapshot.current_block_id == "block-a"
    assert snapshot.next_block_id == "block-b"
    assert snapshot.forward_depth_ms == 3_604_000
    assert snapshot.required_runtime_depth_ms == 3_600_000
    assert snapshot.current_playlist_event_present is True
    assert snapshot.next_playlist_event_present is True
    assert director._channel_execution_ready[channel_config.channel_id] == snapshot
    assert channel_config.channel_id not in director._channel_startup_faults


def test_validate_execution_ready_raises_structured_fault_for_missing_next_playlog(monkeypatch):
    channel_config = replace(
        MOCK_CHANNEL_CONFIG,
        schedule_config={
            **(MOCK_CHANNEL_CONFIG.schedule_config or {}),
            "playlog_min_hours": 1,
        },
    )
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    block_a = ScheduledBlock("block-a", 1_000, 2_000, ())
    block_b = ScheduledBlock("block-b", 2_000, 3_000, ())
    execution_reader = _FakeExecutionReader(
        current_block=block_a,
        next_block=block_b,
        playlist_events={"block-a": block_a},
        execution_depth_ms=3_999_000,
    )
    monkeypatch.setattr(
        director,
        "_get_execution_reader_for_channel",
        lambda channel_id, config: execution_reader,
    )
    director._playlog_daemons[channel_config.channel_id] = SimpleNamespace(
        get_health_report=lambda: SimpleNamespace(
            farthest_block_end_utc_ms=4_000_000,
            is_healthy=True,
            last_evaluation_utc_ms=999,
        )
    )

    try:
        director._validate_execution_ready(channel_config.channel_id, 1_500)
        raise AssertionError("expected ExecutionReadinessFault")
    except ExecutionReadinessFault as exc:
        assert exc.failed_check == "playlog_next_block_missing"
        assert exc.channel_id == channel_config.channel_id
        assert exc.current_block_id == "block-a"
        assert exc.next_block_id == "block-b"
        assert exc.required_runtime_depth_ms == 3_600_000
        assert director._channel_startup_faults[channel_config.channel_id] is exc


def test_wait_until_execution_ready_retries_until_snapshot(monkeypatch):
    channel_config = replace(
        MOCK_CHANNEL_CONFIG,
        schedule_config={
            **(MOCK_CHANNEL_CONFIG.schedule_config or {}),
            "playlog_min_hours": 1,
        },
    )
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    attempts = {"count": 0}

    def _fake_validate(channel_id: str, now_ms: int):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ExecutionReadinessFault(
                channel_id=channel_id,
                failed_check="forward_execution_depth_insufficient",
                detail="still filling",
                now_ms=now_ms,
                required_runtime_depth_ms=3_600_000,
                forward_depth_ms=1_000,
            )
        return SimpleNamespace(channel_id=channel_id, now_ms=now_ms)

    monkeypatch.setattr(director, "_validate_execution_ready", _fake_validate)
    monkeypatch.setattr("retrovue.runtime.program_director.time.sleep", lambda _: None)

    snapshot = director.wait_until_execution_ready(channel_config.channel_id, 1_500)

    assert snapshot.channel_id == channel_config.channel_id
    assert attempts["count"] == 3


def test_get_execution_reader_for_channel_constructs_and_caches(monkeypatch):
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    fake_schedule_service = SimpleNamespace(
        _blocks=[],
        _lock=SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, exc_type, exc, tb: False),
        _frame_tolerance_ms=40,
    )

    class _FakeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_schedule_service._lock = _FakeLock()

    monkeypatch.setattr(
        director,
        "_get_schedule_service_for_channel",
        lambda channel_id, config: fake_schedule_service,
    )

    reader_a = director._get_execution_reader_for_channel(channel_config.channel_id, channel_config)
    reader_b = director._get_execution_reader_for_channel(channel_config.channel_id, channel_config)

    assert isinstance(reader_a, DslExecutionRuntimeReader)
    assert reader_a is reader_b


def test_recover_unready_channels_once_marks_channel_ready_and_logs(caplog, monkeypatch):
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    fault = ExecutionReadinessFault(
        channel_id=channel_config.channel_id,
        failed_check="forward_execution_depth_insufficient",
        detail="startup gap",
        now_ms=1_000,
        required_runtime_depth_ms=3_600_000,
    )
    with director._channel_readiness_lock:
        director._channel_startup_faults[channel_config.channel_id] = fault

    snapshot = ExecutionReadinessSnapshot(
        channel_id=channel_config.channel_id,
        now_ms=2_000,
        current_block_id="block-a",
        next_block_id="block-b",
        current_block_start_utc_ms=1_000,
        current_block_end_utc_ms=2_000,
        next_block_start_utc_ms=2_000,
        next_block_end_utc_ms=3_000,
        forward_depth_ms=3_700_000,
        required_runtime_depth_ms=3_600_000,
        current_playlist_event_present=True,
        next_playlist_event_present=True,
        playlist_builder_healthy=True,
        playlist_builder_last_evaluation_utc_ms=1_900,
    )

    calls = []

    def _fake_wait(channel_id: str, now_ms: int, *, non_blocking: bool = False):
        calls.append((channel_id, now_ms, non_blocking))
        with director._channel_readiness_lock:
            director._channel_execution_ready[channel_id] = snapshot
            director._channel_startup_faults.pop(channel_id, None)
        return snapshot

    monkeypatch.setattr(director, "wait_until_execution_ready", _fake_wait)

    caplog.set_level(logging.INFO)
    recovered = director._recover_unready_channels_once()

    assert recovered == 1
    assert calls and calls[0][0] == channel_config.channel_id
    assert calls[0][2] is True
    with director._channel_readiness_lock:
        assert director._channel_execution_ready[channel_config.channel_id] is snapshot
        assert channel_config.channel_id not in director._channel_startup_faults
    assert f"READY-RECOVERY channel={channel_config.channel_id}" in caplog.text


def test_recovery_does_not_weaken_hard_gate(monkeypatch):
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    director._startup_complete.set()
    fault = ExecutionReadinessFault(
        channel_id=channel_config.channel_id,
        failed_check="playlog_current_block_missing",
        detail="missing PlaylistEvent",
        now_ms=1_500,
        required_runtime_depth_ms=3_600_000,
    )
    with director._channel_readiness_lock:
        director._channel_startup_faults[channel_config.channel_id] = fault

    monkeypatch.setattr(director, "wait_until_execution_ready", lambda *args, **kwargs: (_ for _ in ()).throw(fault))
    assert director._recover_unready_channels_once() == 0

    with pytest.raises(ExecutionReadinessFault) as excinfo:
        director.start_channel(channel_config.channel_id)
    assert excinfo.value is fault


def test_init_playlog_daemons_calls_wait_until_execution_ready_non_blocking(monkeypatch, caplog):
    channel_config = replace(
        MOCK_CHANNEL_CONFIG,
        schedule_config={
            **(MOCK_CHANNEL_CONFIG.schedule_config or {}),
            "playlog_min_hours": 1,
            "dsl_path": "/tmp/fake.dsl",
        },
    )
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )

    monkeypatch.setattr(
        director,
        "_get_schedule_service_for_channel",
        lambda channel_id, config: SimpleNamespace(_maybe_extend_horizon=lambda *_: None),
    )

    events: list[tuple[str, str, int]] = []

    class _FakePlaylistBuilderDaemon:
        def __init__(self, channel_id: str, **kwargs):
            self.channel_id = channel_id

        def evaluate_once(self):
            return 2

        def get_health_report(self):
            return SimpleNamespace(
                is_healthy=True,
                depth_hours=1.5,
                blocks_in_window=3,
                farthest_block_end_utc_ms=5_000_000,
                last_evaluation_utc_ms=111,
            )

        def start(self):
            events.append(("start", self.channel_id, 0))

    def _fake_wait(channel_id: str, now_ms: int):
        events.append(("wait", channel_id, now_ms))
        raise ExecutionReadinessFault(
            channel_id=channel_id,
            failed_check="forward_execution_depth_insufficient",
            detail="not ready yet",
            now_ms=now_ms,
            required_runtime_depth_ms=3_600_000,
            forward_depth_ms=1_000,
        )

    monkeypatch.setattr(
        "retrovue.runtime.playlist_builder_daemon.PlaylistBuilderDaemon",
        _FakePlaylistBuilderDaemon,
    )
    monkeypatch.setattr(director, "wait_until_execution_ready", _fake_wait)

    caplog.set_level(logging.WARNING)
    director._init_playlog_daemons()

    assert ("start", channel_config.channel_id, 0) in events
    wait_events = [event for event in events if event[0] == "wait"]
    assert len(wait_events) == 1
    assert wait_events[0][1] == channel_config.channel_id
    assert channel_config.channel_id in director._playlog_daemons
    assert "ExecutionReadiness startup observation failed" in caplog.text


def test_healthy_channel_can_activate(monkeypatch):
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    director._startup_complete.set()
    director._channel_execution_ready[channel_config.channel_id] = ExecutionReadinessSnapshot(
        channel_id=channel_config.channel_id,
        now_ms=1_500,
        current_block_id="block-a",
        next_block_id="block-b",
        current_block_start_utc_ms=1_000,
        current_block_end_utc_ms=2_000,
        next_block_start_utc_ms=2_000,
        next_block_end_utc_ms=3_000,
        forward_depth_ms=3_604_000,
        required_runtime_depth_ms=3_600_000,
        current_playlist_event_present=True,
        next_playlist_event_present=True,
        playlist_builder_healthy=True,
        playlist_builder_last_evaluation_utc_ms=1_400,
    )

    fake_schedule_service = SimpleNamespace(_blocks=[object()])
    fake_execution_reader = SimpleNamespace()
    monkeypatch.setattr(
        director,
        "_get_schedule_service_for_channel",
        lambda channel_id, config: fake_schedule_service,
    )
    monkeypatch.setattr(
        director,
        "_get_execution_reader_for_channel",
        lambda channel_id, config: fake_execution_reader,
    )

    created = {}

    class _FakeChannelManager:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self._channel_state = "IDLE"
            self.channel_id = kwargs["channel_id"]
            self.active_producer = None
            self.channel_config = None

    monkeypatch.setattr("retrovue.runtime.channel_manager.ChannelManager", _FakeChannelManager)

    manager = director.start_channel(channel_config.channel_id)

    assert manager.channel_id == channel_config.channel_id
    assert director._managers[channel_config.channel_id] is manager
    assert created["execution_reader"] is fake_execution_reader
    assert "schedule_service" not in created


def test_unhealthy_channel_cannot_activate():
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    director._startup_complete.set()
    fault = ExecutionReadinessFault(
        channel_id=channel_config.channel_id,
        failed_check="playlog_current_block_missing",
        detail="missing PlaylistEvent for current block block-a",
        now_ms=1_500,
        current_block_id="block-a",
        next_block_id="block-b",
        required_runtime_depth_ms=3_600_000,
    )
    director._channel_startup_faults[channel_config.channel_id] = fault

    with pytest.raises(ExecutionReadinessFault) as excinfo:
        director.start_channel(channel_config.channel_id)

    assert excinfo.value is fault
    assert channel_config.channel_id not in director._managers


def test_hls_and_ts_activation_both_fail_through_same_readiness_gate():
    channel_config = replace(MOCK_CHANNEL_CONFIG)
    director = ProgramDirector(
        clock=SystemClock(),
        target_hz=15.0,
        channel_config_provider=InlineChannelConfigProvider([channel_config]),
        resolved_config=TEST_RESOLVED_CONFIG,
    )
    director._startup_complete.set()
    fault = ExecutionReadinessFault(
        channel_id=channel_config.channel_id,
        failed_check="playlog_next_block_missing",
        detail="missing PlaylistEvent for next block block-b",
        now_ms=1_500,
        current_block_id="block-a",
        next_block_id="block-b",
        required_runtime_depth_ms=3_600_000,
    )
    director._channel_startup_faults[channel_config.channel_id] = fault

    with pytest.raises(ExecutionReadinessFault) as ts_excinfo:
        director.start_channel(channel_config.channel_id)

    assert ts_excinfo.value is fault

    result = asyncio.run(
        director._hls_adapter.activate(
            channel_config.channel_id,
            "session-1",
            director,
        )
    )
    assert result is None
    assert channel_config.channel_id not in director._managers
