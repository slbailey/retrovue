"""Startup regression guard for Core -> AIR BlockPlan contract."""

from __future__ import annotations

import io
import queue
import socket as real_socket
import sys
import types
from datetime import datetime, timezone

import pytest

from retrovue.runtime.config import DEFAULT_PROGRAM_FORMAT, ChannelConfig
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.infra.settings import settings
from retrovue.usecases import channel_manager_launch as mod

if not settings.test_database_url:
    settings.test_database_url = "sqlite:////tmp/retrovue_test_startup_regression.sqlite"
if settings.test_database_url == settings.database_url:
    settings.database_url = "sqlite:////tmp/retrovue_dev_placeholder.sqlite"


def _make_channel_config(channel_id_int: int = 42) -> ChannelConfig:
    return ChannelConfig(
        channel_id="test-chan",
        number=channel_id_int,
        channel_id_int=channel_id_int,
        name="Test Channel",
        program_format=DEFAULT_PROGRAM_FORMAT,
        schedule_source="dsl",
    )


def _make_block(block_id: str, start_utc_ms: int, durations_ms: list[int]) -> ScheduledBlock:
    segments = tuple(
        ScheduledSegment(
            segment_type="content",
            asset_uri=f"/media/{block_id}_{idx}.mp4",
            asset_start_offset_ms=0,
            segment_duration_ms=duration_ms,
        )
        for idx, duration_ms in enumerate(durations_ms)
    )
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + sum(durations_ms),
        segments=segments,
    )


class _ProtoMessage:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _ProtoBlockPlan(_ProtoMessage):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.segments: list[object] = []


class _Response:
    def __init__(self, *, success: bool = True, message: str = "", version: str = "1.0.0"):
        self.success = success
        self.message = message
        self.version = version


class _FakeGrpcModule:
    class RpcError(Exception):
        pass

    def __init__(self, stub):
        self._stub = stub

    def insecure_channel(self, addr: str):
        stub = self._stub

        class _Channel:
            def __enter__(self_inner):
                return stub

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return _Channel()


class _RecordingStub:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def GetVersion(self, request, timeout=None):
        self.calls.append(("GetVersion", request))
        return _Response(version="1.0.0")

    def StartChannel(self, request, timeout=None):
        self.calls.append(("StartChannel", request))
        return _Response()

    def AttachStream(self, request, timeout=None):
        self.calls.append(("AttachStream", request))
        return _Response()

    def StartBlockPlanSession(self, request, timeout=None):
        self.calls.append(("StartBlockPlanSession", request))
        return _Response()

    def LoadPreview(self, request, timeout=None):  # pragma: no cover - must not be called
        self.calls.append(("LoadPreview", request))
        raise AssertionError("legacy LoadPreview must not be used at startup")

    def SwitchToLive(self, request, timeout=None):  # pragma: no cover - must not be called
        self.calls.append(("SwitchToLive", request))
        raise AssertionError("legacy SwitchToLive must not be used at startup")


class _FakePb2(types.SimpleNamespace):
    STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET = 1
    SEGMENT_TYPE_CONTENT = 1
    SEGMENT_TYPE_FILLER = 2
    SEGMENT_TYPE_PAD = 3
    TRANSITION_NONE = 0
    TRANSITION_FADE = 1

    BlockPlan = _ProtoBlockPlan
    BlockSegment = _ProtoMessage
    StartChannelRequest = _ProtoMessage
    AttachStreamRequest = _ProtoMessage
    StartBlockPlanSessionRequest = _ProtoMessage
    ApiVersionRequest = _ProtoMessage


class _FakePb2Grpc(types.SimpleNamespace):
    def __init__(self, stub):
        super().__init__(PlayoutControlStub=lambda _channel: stub)


class _FakeSocketBase:
    def close(self):
        self.closed = True


class _FakeUnixServerSocket(_FakeSocketBase):
    def __init__(self):
        self.bound = None
        self.closed = False

    def bind(self, path):
        self.bound = path

    def listen(self, backlog):
        self.backlog = backlog

    def accept(self):
        return (object(), None)


class _FakeInetSocket(_FakeSocketBase):
    def __init__(self):
        self.addr = ("127.0.0.1", 43123)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def bind(self, addr):
        self.addr = ("127.0.0.1", 43123)

    def getsockname(self):
        return self.addr


class _FakeThread:
    def __init__(self, *, target, daemon=False, name=None):
        self._target = target

    def start(self):
        self._target()


class _FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0


@pytest.mark.contract
def test_startup_launch_uses_startblockplansession_only(monkeypatch):
    stub = _RecordingStub()
    fake_grpc = _FakeGrpcModule(stub)
    monkeypatch.setitem(sys.modules, "grpc", fake_grpc)

    pb2 = _FakePb2()
    pb2_grpc = _FakePb2Grpc(stub)
    monkeypatch.setattr(mod, "_get_playout_stubs", lambda: (pb2, pb2_grpc))
    monkeypatch.setattr(mod, "_open_air_log", lambda _channel_id: io.StringIO())
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr(mod.threading, "Thread", _FakeThread)

    def _fake_socket(family, sock_type):
        if family == real_socket.AF_UNIX:
            return _FakeUnixServerSocket()
        if family == real_socket.AF_INET:
            return _FakeInetSocket()
        raise AssertionError(f"unexpected socket family {family}")

    monkeypatch.setattr(mod.socket, "socket", _fake_socket)

    cfg = _make_channel_config()
    block_a = _make_block("B0", 1_700_000_000_000, [15_000, 15_000])
    block_b = _make_block("B1", block_a.end_utc_ms, [15_000, 15_000])

    proc, socket_path, reader_q, grpc_addr = mod._launch_air_binary(
        air_bin=mod.Path("/tmp/retrovue_air"),
        socket_path=mod.Path("/tmp/retrovue-test.sock"),
        channel_id="test-chan",
        channel_config=cfg,
        join_utc_ms=block_a.start_utc_ms,
        current_block=block_a,
        next_block=block_b,
        reader_socket_queue=queue.Queue(),
        stdout=None,
        stderr=None,
    )

    assert isinstance(proc, _FakeProcess)
    assert str(socket_path) == "/tmp/retrovue-test.sock"
    assert grpc_addr == "127.0.0.1:43123"
    assert reader_q.get_nowait() is not None

    call_names = [name for name, _ in stub.calls]
    assert call_names == [
        "GetVersion",
        "StartChannel",
        "AttachStream",
        "StartBlockPlanSession",
    ]

    start_req = stub.calls[1][1]
    session_req = stub.calls[3][1]
    assert start_req.channel_id == cfg.channel_id_int
    assert session_req.join_utc_ms == block_a.start_utc_ms
    assert session_req.block_a.block_id == "B0"
    assert session_req.block_b.block_id == "B1"
    assert not any(name in {"LoadPreview", "SwitchToLive"} for name in call_names)


@pytest.mark.contract
def test_legacy_segment_startup_payload_fails_loudly(caplog):
    cfg = _make_channel_config()
    caplog.set_level("ERROR", logger="retrovue.usecases.channel_manager_launch")

    with pytest.raises(mod.LegacyStartupPathError) as exc_info:
        mod.launch_air(
            playout_request={
                "channel_id": "test-chan",
                "join_utc_ms": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
                "segment_index": 0,
                "asset_uri": "/media/only-segment.mp4",
                "asset_start_offset_ms": 0,
                "segment_duration_ms": 30_000,
            },
            channel_config=cfg,
        )

    msg = str(exc_info.value)
    assert "segment-only payload" in msg
    assert "block_a/block_b" in msg
    assert "INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001" in caplog.text


@pytest.mark.contract
@pytest.mark.parametrize(
    ("operation", "call"),
    [
        (
            "LoadPreview",
            lambda: mod.air_load_preview(
                "127.0.0.1:50051",
                42,
                "/media/legacy.mp4",
                0,
                900,
                30,
                1,
            ),
        ),
        (
            "SwitchToLive",
            lambda: mod.air_switch_to_live(
                "127.0.0.1:50051",
                42,
                clock=types.SimpleNamespace(now_utc_ms=lambda: 1_700_000_000_000),
            ),
        ),
    ],
)
def test_legacy_startup_helpers_fail_immediately(operation, call, caplog):
    caplog.set_level("ERROR", logger="retrovue.usecases.channel_manager_launch")

    with pytest.raises(mod.LegacyStartupPathError) as exc_info:
        call()

    assert operation in str(exc_info.value)
    assert "StartBlockPlanSession" in str(exc_info.value)
    assert "INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001" in caplog.text
