"""
Air (playout engine) process management.

ChannelManager spawns Air processes to play video for the schedule. ChannelManager
must NOT spawn ProgramDirector or the main retrovue process; ProgramDirector
spawns ChannelManager when one doesn't exist for the requested channel. This
module is used by ChannelManager to launch and terminate Air processes.

Air logging (stdout/stderr):
  Air output is written to runtime/logs/<channel_id>-air.log (one file per channel).
  The log file is truncated on every launch so it does not grow without bound.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# Type alias for subprocess.Process
ProcessHandle = subprocess.Popen[bytes]

# Air stdout/stderr go here: runtime/logs/<channel_id>-air.log
_AIR_LOG_DIR = Path(__file__).resolve().parents[4] / "runtime" / "logs"


def _air_log_path(channel_id: str) -> Path:
    """Path to the Air log file for this channel (same as subprocess redirect)."""
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel_id) or "unknown"
    return _AIR_LOG_DIR / f"{safe_id}-air.log"

# Import ChannelConfig for type hints
from retrovue.runtime.config import ChannelConfig, MOCK_CHANNEL_CONFIG
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


def _rotate_air_log(log_path: Path) -> None:
    """Preserve the previous AIR log so crash reasons survive reconnect."""
    if log_path.exists() and log_path.stat().st_size > 0:
        log_path.rename(log_path.with_suffix(".log.prev"))


def _open_air_log(channel_id: str):
    """Open Air log file for this channel (truncate on open, line-buffered). Caller closes after Popen."""
    log_path = _air_log_path(channel_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_air_log(log_path)
    return open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")


def _find_air_binary() -> Path | None:
    """Locate retrovue_air executable. Returns None if not found."""
    # __file__ is .../server/src/retrovue/usecases/channel_manager_launch.py -> parents[4] = repo root
    repo_root = Path(__file__).resolve().parents[4]
    candidates = [
        Path(os.environ.get("RETROVUE_AIR_EXE", "")),
        repo_root / "runtime" / "build" / "retrovue_air",
        repo_root / "runtime" / "out" / "build" / "linux-debug" / "retrovue_air",
    ]
    for p in candidates:
        if p and p.is_file() and os.access(p, os.X_OK):
            return p
    return None


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


def _get_playout_stubs() -> tuple[types.ModuleType, types.ModuleType]:
    """Load playout_pb2 and playout_pb2_grpc from server/src/retrovue/proto/. Returns (playout_pb2, playout_pb2_grpc)."""
    candidates = [
        Path(__file__).resolve().parent.parent / "proto",
        Path("/opt/retrovue/server/src/retrovue/proto"),
    ]
    _proto_retrovue_dir = None
    for p in candidates:
        if p.is_dir() and (p / "playout_pb2.py").exists():
            _proto_retrovue_dir = p
            break
    if _proto_retrovue_dir is None:
        raise RuntimeError(
            "Proto stubs not found. "
            "Run scripts/air/generate_proto.sh or equivalent to generate playout_pb2(_grpc).py."
        )
    _spec_pb2 = importlib.util.spec_from_file_location(
        "playout_pb2", _proto_retrovue_dir / "playout_pb2.py"
    )
    _spec_grpc = importlib.util.spec_from_file_location(
        "playout_pb2_grpc", _proto_retrovue_dir / "playout_pb2_grpc.py"
    )
    if _spec_pb2 is None or _spec_grpc is None:
        raise RuntimeError("Failed to create spec for proto stubs")
    playout_pb2 = importlib.util.module_from_spec(_spec_pb2)
    playout_pb2_grpc = importlib.util.module_from_spec(_spec_grpc)
    _retrovue_saved = sys.modules.get("retrovue")
    _playout_pb2_saved = sys.modules.get("playout_pb2")
    _proto_retrovue = types.ModuleType("retrovue")
    _proto_retrovue.playout_pb2 = playout_pb2
    sys.modules["retrovue"] = _proto_retrovue
    try:
        _spec_pb2.loader.exec_module(playout_pb2)
        sys.modules["playout_pb2"] = playout_pb2
        _spec_grpc.loader.exec_module(playout_pb2_grpc)
        return (playout_pb2, playout_pb2_grpc)
    finally:
        if _retrovue_saved is not None:
            sys.modules["retrovue"] = _retrovue_saved
        else:
            sys.modules.pop("retrovue", None)
        if _playout_pb2_saved is not None:
            sys.modules["playout_pb2"] = _playout_pb2_saved
        else:
            sys.modules.pop("playout_pb2", None)


# Phase 8: ResultCode enum values (must match proto)
RESULT_CODE_UNSPECIFIED = 0
RESULT_CODE_OK = 1
RESULT_CODE_NOT_READY = 2
RESULT_CODE_REJECTED_BUSY = 3
RESULT_CODE_PROTOCOL_VIOLATION = 4  # Caller violated the protocol
RESULT_CODE_FAILED = 5


# P11D-005: Exceptions for SwitchToLive protocol (no retry)
class SwitchTimingError(Exception):
    """Raised when SwitchToLive issued with insufficient lead time (PROTOCOL_VIOLATION)."""
    pass


class SwitchProtocolError(Exception):
    """Raised when AIR protocol contract violated (e.g. deprecated NOT_READY in deadline mode)."""
    pass


def _sum_segment_duration_ms(block: ScheduledBlock) -> int:
    return sum(int(seg.segment_duration_ms) for seg in block.segments)


def _broadcast_date_for(utc_ms: int, day_start_hour: int = 6) -> date:
    dt = datetime.fromtimestamp(utc_ms / 1000.0, tz=timezone.utc)
    if dt.hour < day_start_hour:
        dt -= timedelta(days=1)
    return dt.date()


def _validate_block_for_air(block: ScheduledBlock, *, context: str) -> None:
    if not block.segments:
        raise RuntimeError(f"{context}: block {block.block_id} has no segments")

    block_duration_ms = int(block.end_utc_ms) - int(block.start_utc_ms)
    if block_duration_ms <= 0:
        raise RuntimeError(
            f"{context}: block {block.block_id} has invalid timing "
            f"start_utc_ms={block.start_utc_ms} end_utc_ms={block.end_utc_ms}"
        )

    segment_sum_ms = _sum_segment_duration_ms(block)
    if segment_sum_ms != block_duration_ms:
        raise RuntimeError(
            f"{context}: block {block.block_id} segment duration mismatch "
            f"sum_segment_ms={segment_sum_ms} block_duration_ms={block_duration_ms}"
        )

    for idx, seg in enumerate(block.segments):
        if int(seg.segment_duration_ms) <= 0:
            raise RuntimeError(
                f"{context}: block {block.block_id} segment {idx} has invalid "
                f"segment_duration_ms={seg.segment_duration_ms}"
            )
        if int(seg.asset_start_offset_ms) < 0:
            raise RuntimeError(
                f"{context}: block {block.block_id} segment {idx} has invalid "
                f"asset_start_offset_ms={seg.asset_start_offset_ms}"
            )


def _segment_type_enum(playout_pb2: types.ModuleType, segment: ScheduledSegment) -> int:
    segment_type = str(segment.segment_type).lower()
    if segment_type in {"pad", "padding"}:
        return playout_pb2.SEGMENT_TYPE_PAD
    if segment_type == "filler":
        return playout_pb2.SEGMENT_TYPE_FILLER
    return playout_pb2.SEGMENT_TYPE_CONTENT


def _transition_type_enum(playout_pb2: types.ModuleType, value: str) -> int:
    if str(value).upper() == "TRANSITION_FADE":
        return playout_pb2.TRANSITION_FADE
    return playout_pb2.TRANSITION_NONE


def _scheduled_block_to_proto(
    playout_pb2: types.ModuleType,
    channel_id_int: int,
    block: ScheduledBlock,
) -> Any:
    _validate_block_for_air(block, context="Core→AIR BlockPlan contract")

    proto = playout_pb2.BlockPlan(
        block_id=block.block_id,
        channel_id=channel_id_int,
        start_utc_ms=int(block.start_utc_ms),
        end_utc_ms=int(block.end_utc_ms),
        broadcast_date=_broadcast_date_for(int(block.start_utc_ms)).isoformat(),
        broadcast_day_anchor_utc_ms=0,
    )
    for idx, seg in enumerate(block.segments):
        proto.segments.append(
            playout_pb2.BlockSegment(
                segment_index=idx,
                asset_uri=seg.asset_uri,
                asset_start_offset_ms=int(seg.asset_start_offset_ms),
                segment_duration_ms=int(seg.segment_duration_ms),
                segment_type=_segment_type_enum(playout_pb2, seg),
                transition_in=_transition_type_enum(playout_pb2, seg.transition_in),
                transition_in_duration_ms=int(seg.transition_in_duration_ms),
                transition_out=_transition_type_enum(playout_pb2, seg.transition_out),
                transition_out_duration_ms=int(seg.transition_out_duration_ms),
                gain_db=float(seg.gain_db),
            )
        )
    return proto


def log_core_intent_frame_range(
    *,
    channel_id: str,
    segment_id: str,
    asset_path: str,
    start_frame: int,
    end_frame: int,
    fps: float,
    CT_start_us: int,
    MT_start_us: int,
) -> None:
    """Emit structured CORE_INTENT_FRAME_RANGE probe (once per segment hand-off to AIR)."""
    import logging
    msg = (
        f"CORE_INTENT_FRAME_RANGE channel_id={channel_id} segment_id={segment_id} asset_path={asset_path} "
        f"start_frame={start_frame} end_frame={end_frame} fps={fps} CT_start_us={CT_start_us} MT_start_us={MT_start_us}"
    )
    logging.getLogger(__name__).info("%s", msg)
    # Also append to the channel's Air log so intent and AIR_AS_RUN appear together for comparison.
    try:
        log_path = _air_log_path(channel_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write("[Core] " + msg + "\n")
    except OSError:
        pass  # Do not fail hand-off if log write fails


def start_blockplan_session(
    grpc_addr: str,
    *,
    channel_id: str,
    channel_id_int: int,
    join_utc_ms: int,
    current_block: ScheduledBlock,
    next_block: ScheduledBlock,
    channel_config: ChannelConfig,
    timeout_s: int = 30,
) -> bool:
    import grpc

    if join_utc_ms <= 0:
        raise RuntimeError("Core→AIR BlockPlan contract: join_utc_ms is required")
    if int(current_block.end_utc_ms) != int(next_block.start_utc_ms):
        raise RuntimeError(
            "Core→AIR BlockPlan contract: startup blocks must be contiguous "
            f"current_end={current_block.end_utc_ms} next_start={next_block.start_utc_ms}"
        )

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    block_a = _scheduled_block_to_proto(playout_pb2, channel_id_int, current_block)
    block_b = _scheduled_block_to_proto(playout_pb2, channel_id_int, next_block)

    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        response = stub.StartBlockPlanSession(
            playout_pb2.StartBlockPlanSessionRequest(
                channel_id=channel_id_int,
                block_a=block_a,
                block_b=block_b,
                join_utc_ms=int(join_utc_ms),
                program_format_json=channel_config.program_format.to_json(),
                channel_id_str=channel_id,
            ),
            timeout=timeout_s,
        )
    if not response.success:
        raise RuntimeError(f"StartBlockPlanSession failed: {response.message}")
    logging.getLogger(__name__).info(
        "Core→AIR BlockPlan startup: channel_id=%s join_utc_ms=%d block_a=%s "
        "start_utc_ms=%d end_utc_ms=%d block_b=%s start_utc_ms=%d end_utc_ms=%d",
        channel_id,
        join_utc_ms,
        current_block.block_id,
        int(current_block.start_utc_ms),
        int(current_block.end_utc_ms),
        next_block.block_id,
        int(next_block.start_utc_ms),
        int(next_block.end_utc_ms),
    )
    return True


def feed_blockplan(
    grpc_addr: str,
    *,
    channel_id_int: int,
    block: ScheduledBlock,
    timeout_s: int = 30,
) -> bool:
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    block_proto = _scheduled_block_to_proto(playout_pb2, channel_id_int, block)

    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        response = stub.FeedBlockPlan(
            playout_pb2.FeedBlockPlanRequest(
                channel_id=channel_id_int,
                block=block_proto,
            ),
            timeout=timeout_s,
        )
    if not response.success:
        raise RuntimeError(f"FeedBlockPlan failed: {response.message}")
    return True


def iter_blockplan_events(
    grpc_addr: str,
    *,
    channel_id_int: int,
    timeout_s: int = 3600,
) -> Iterator[Any]:
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    channel = grpc.insecure_channel(grpc_addr)
    try:
        stub = playout_pb2_grpc.PlayoutControlStub(channel)
        stream = stub.SubscribeBlockEvents(
            playout_pb2.SubscribeBlockEventsRequest(channel_id=channel_id_int),
            timeout=timeout_s,
        )
        for event in stream:
            yield event
    finally:
        channel.close()


def air_load_preview(
    grpc_addr: str,
    channel_id_int: int,
    asset_path: str,
    start_frame: int,
    frame_count: int,
    fps_numerator: int,
    fps_denominator: int,
    timeout_s: int = 90,
) -> bool:
    """Call Air LoadPreview RPC with frame-indexed execution (INV-FRAME-001/002/003).

    Args:
        grpc_addr: gRPC address of Air engine (e.g. "127.0.0.1:50051")
        channel_id_int: Channel ID as integer
        asset_path: Fully-qualified path to media file
        start_frame: First frame index within asset (0-based, INV-FRAME-001)
        frame_count: Exact number of frames to play (INV-FRAME-002)
        fps_numerator: Frame rate numerator (e.g. 30000 for 29.97fps, INV-FRAME-003)
        fps_denominator: Frame rate denominator (e.g. 1001 for 29.97fps, INV-FRAME-003)
        timeout_s: RPC timeout in seconds

    Returns:
        True if preview loaded successfully, False otherwise.

    Raises:
        grpc.RpcError on connection/RPC error.

    Phase 8: If result_code is REJECTED_BUSY, logs at INFO level (expected when
    switch is armed) rather than WARNING.
    """
    import grpc
    import logging
    logger = logging.getLogger(__name__)

    # INV-FRAME-003: Fail fast if fps not provided
    if fps_denominator <= 0:
        logger.error("INV-FRAME-003 violation: fps_denominator must be > 0 (got %d)", fps_denominator)
        return False
    if frame_count < 0:
        logger.error(
            "INV-AIR-NO-ADHOC-SWITCHING-001 violation: frame_count must be explicit (got %d)",
            frame_count,
        )
        return False

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.LoadPreview(
            playout_pb2.LoadPreviewRequest(
                channel_id=channel_id_int,
                asset_path=asset_path,
                start_frame=start_frame,
                frame_count=frame_count,
                fps_numerator=fps_numerator,
                fps_denominator=fps_denominator,
            ),
            timeout=timeout_s,
        )

    # Phase 8: Treat REJECTED_BUSY as expected (switch is armed, LoadPreview forbidden)
    if not r.success:
        result_code = getattr(r, 'result_code', RESULT_CODE_UNSPECIFIED)
        if result_code == RESULT_CODE_REJECTED_BUSY:
            logger.info("LoadPreview rejected (switch armed): %s", r.message)
        else:
            logger.warning("LoadPreview failed: %s (result_code=%d)", r.message, result_code)

    return r.success


# P11E-001: Single source for MIN_PREFEED_LEAD_TIME_MS (env RETROVUE_MIN_PREFEED_LEAD_TIME_MS).
from retrovue.runtime.constants import MIN_PREFEED_LEAD_TIME_MS
from retrovue.runtime.clock import AuthoritativeClock


def air_switch_to_live(
    grpc_addr: str,
    channel_id_int: int,
    *,
    clock: AuthoritativeClock,
    timeout_s: int = 30,
    target_boundary_time_ms: int = 0,
) -> tuple[bool, int, str]:
    """Call Air SwitchToLive RPC. Returns (success, result_code, violation_reason). Raises on failure.

    P11D-005: INV-CONTROL-NO-POLL-001 — no retry. PROTOCOL_VIOLATION → SwitchTimingError;
    NOT_READY → SwitchProtocolError (deprecated in deadline-authoritative mode).
    P11C-001: target_boundary_time_ms is the scheduled grid boundary (wall-clock ms). 0 = legacy/immediate.
    """
    import grpc

    # P11D-012: INV-LEADTIME-MEASUREMENT-001 — issued_at_time_ms for lead-time evaluation
    issued_at_time_ms = clock.now_utc_ms()

    if target_boundary_time_ms > 0:
        lead_time_ms = target_boundary_time_ms - issued_at_time_ms
        logging.getLogger(__name__).info(
            "[SwitchToLive] Core issuing: issued_at_ms=%d target_boundary_ms=%d lead_time_ms=%d MIN_PREFEED_LEAD_TIME_MS=%d",
            issued_at_time_ms,
            target_boundary_time_ms,
            lead_time_ms,
            MIN_PREFEED_LEAD_TIME_MS,
        )

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.SwitchToLive(
            playout_pb2.SwitchToLiveRequest(
                channel_id=channel_id_int,
                target_boundary_time_ms=target_boundary_time_ms,
                issued_at_time_ms=issued_at_time_ms,
            ),
            timeout=timeout_s,
        )
    result_code = getattr(r, 'result_code', RESULT_CODE_UNSPECIFIED)
    violation_reason = getattr(r, 'violation_reason', '') or ''
    if r.success:
        # AUDIT: TP - Producer switch completed
        _AUDIT_TP = clock.monotonic_ns()
        logging.getLogger(__name__).info(
            "[AUDIT-TP] SwitchToLive completed at %d ns for channel_id=%d",
            _AUDIT_TP, channel_id_int
        )
        return (True, result_code, violation_reason)
    # P11D-005: Treat PROTOCOL_VIOLATION and NOT_READY as fatal (no retry)
    if result_code == RESULT_CODE_PROTOCOL_VIOLATION:
        raise SwitchTimingError(violation_reason or "Insufficient prefeed lead time")
    if result_code == RESULT_CODE_NOT_READY:
        raise SwitchProtocolError("Unexpected NOT_READY in deadline-authoritative mode")
    raise RuntimeError(r.message)


def _launch_air_binary(
    *,
    air_bin: Path,
    socket_path: Path,
    channel_id: str,
    channel_config: ChannelConfig,
    join_utc_ms: int,
    current_block: ScheduledBlock,
    next_block: ScheduledBlock,
    evidence_endpoint: str = "",
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    reader_socket_queue: queue.Queue[Any] | None = None,
) -> tuple[ProcessHandle, Path, queue.Queue[Any], str]:
    """Start retrovue_air and bootstrap a BlockPlan session.

    INV-EARLY-DRAIN: caller may supply its own ``reader_socket_queue`` so a
    pre-wired ChannelStream's upstream reader can already be polling that
    exact queue before AIR connects.  When the accept thread lands AIR's
    socket in the queue, the pre-wired reader picks it up instantly — the
    AttachStream→StartBlockPlanSession window no longer leaves the UDS
    orphaned.
    """
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()

    if reader_socket_queue is None:
        reader_socket_queue = queue.Queue()

    if socket_path.exists():
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    def accept_once() -> None:
        conn, _ = server.accept()
        reader_socket_queue.put(conn)
        try:
            server.close()  # Only Air should connect; viewers use HTTP (e.g. http://localhost:PORT/channel/ID.ts)
        except Exception:
            pass

    threading.Thread(target=accept_once, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        grpc_port = s.getsockname()[1]

    # Redirect Air stdout/stderr to channel-specific log (truncated each run)
    air_log = _open_air_log(channel_id)

    # Build AIR command line
    air_cmd = [str(air_bin), "--port", str(grpc_port)]

    # Forensic TS dump: if RETROVUE_FORENSIC_DUMP_DIR is set, enable forensic dump
    forensic_dir = os.environ.get("RETROVUE_FORENSIC_DUMP_DIR", "")
    if forensic_dir:
        air_cmd.extend(["--forensic-dump-dir", forensic_dir])

    try:
        proc = subprocess.Popen(
            air_cmd,
            cwd=str(air_bin.parent),
            stdout=air_log,
            stderr=air_log,
            stdin=subprocess.DEVNULL,
        )
    finally:
        air_log.close()

    # Timeouts: Air can be slow on first start (decode init, file open). Override via env if needed.
    def _timeout_s(name: str, default: int) -> int:
        key = f"RETROVUE_AIR_TIMEOUT_{name}"
        val = os.environ.get(key, "")
        return int(val) if val.isdigit() else default

    _GRPC_READY_WAIT_S = _timeout_s("GRPC_READY_WAIT", 45)
    _GRPC_READY_POLL_S = _timeout_s("GRPC_READY_POLL", 5)
    _RPC_CONTROL_S = _timeout_s("RPC_CONTROL", 30)
    _RPC_BLOCKPLAN_S = _timeout_s("RPC_BLOCKPLAN", 90)
    _UDS_ACCEPT_S = _timeout_s("UDS_ACCEPT", 20)

    def _rpc(step: str, fn, timeout: int):
        try:
            return fn(timeout=timeout)
        except grpc.RpcError as e:
            d = getattr(e, "details", None)
            detail = d() if callable(d) else (d if isinstance(d, str) else str(e))
            raise RuntimeError(
                f"Air gRPC {step} timed out or failed (timeout={timeout}s): {detail}. "
                f"Check Air logs; increase timeout with RETROVUE_AIR_TIMEOUT_* env if needed."
            ) from e

    grpc_addr = f"127.0.0.1:{grpc_port}"
    for _ in range(max(1, int(_GRPC_READY_WAIT_S / 0.2))):
        try:
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=_GRPC_READY_POLL_S)
            break
        except grpc.RpcError:
            if proc.poll() is not None:
                raise RuntimeError(f"Air process exited with code {proc.returncode} before gRPC ready")
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait(timeout=3)
        raise RuntimeError("Air gRPC server did not become ready")

    channel_id_int = channel_config.channel_id_int
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = _rpc(
            "StartChannel",
            lambda timeout: stub.StartChannel(
                playout_pb2.StartChannelRequest(
                    channel_id=channel_id_int,
                    plan_handle=current_block.block_id,
                    port=0,
                    program_format_json=channel_config.program_format.to_json(),
                ),
                timeout=timeout,
            ),
            _RPC_CONTROL_S,
        )
        if not r.success:
            raise RuntimeError(f"StartChannel failed: {r.message}")
        # AttachStream before StartBlockPlanSession: AIR must have the UDS fd in
        # stream_writers_ so continuous output can begin immediately.
        r = _rpc(
            "AttachStream",
            lambda timeout: stub.AttachStream(
                playout_pb2.AttachStreamRequest(
                    channel_id=channel_id_int,
                    transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                    endpoint=str(socket_path),
                    replace_existing=True,
                ),
                timeout=timeout,
            ),
            _RPC_CONTROL_S,
        )
        if not r.success:
            raise RuntimeError(f"AttachStream failed: {r.message}")
        r = _rpc(
            "StartBlockPlanSession",
            lambda timeout: stub.StartBlockPlanSession(
                playout_pb2.StartBlockPlanSessionRequest(
                    channel_id=channel_id_int,
                    block_a=_scheduled_block_to_proto(playout_pb2, channel_id_int, current_block),
                    block_b=_scheduled_block_to_proto(playout_pb2, channel_id_int, next_block),
                    join_utc_ms=int(join_utc_ms),
                    program_format_json=channel_config.program_format.to_json(),
                    evidence_endpoint=evidence_endpoint,
                    channel_id_str=channel_id,
                ),
                timeout=timeout,
            ),
            _RPC_BLOCKPLAN_S,
        )
        if not r.success:
            raise RuntimeError(f"StartBlockPlanSession failed: {r.message}")

    try:
        conn = reader_socket_queue.get(timeout=_UDS_ACCEPT_S)
    except queue.Empty:
        proc.terminate()
        proc.wait(timeout=3)
        raise RuntimeError(f"Air did not connect to UDS within {_UDS_ACCEPT_S}s")
    reader_socket_queue.put(conn)
    return proc, socket_path, reader_socket_queue, grpc_addr


def launch_air(
    *,
    playout_request: dict[str, Any],
    channel_config: ChannelConfig | None = None,
    stdin: Any = subprocess.PIPE,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    ts_socket_path: str | Path | None = None,
    reader_socket_queue: queue.Queue[Any] | None = None,
) -> tuple[ProcessHandle, Path, queue.Queue[Any], str]:
    """
    Launch AIR and start a deterministic BlockPlan session for a channel.

    Air is the only playout engine. There is no ffmpeg fallback. If Air cannot be
    found, started, or attached, this function raises and the caller must return
    HTTP 503 (e.g. "Air playout engine unavailable").

    Args:
        reader_socket_queue: optional caller-supplied queue that will receive
            the accepted AIR UDS socket.  Callers that pre-wire a consumer
            (INV-EARLY-DRAIN) pass the same ``queue.Queue`` the consumer is
            polling so that AIR's first bytes are drained the instant
            AttachStream lands the socket — closing the AttachStream→
            StartBlockPlanSession backpressure window.

    Returns:
        (process, socket_path, reader_socket_queue, grpc_addr). The reader_socket_queue
        receives the one accepted UDS connection from Air after AttachStream; the caller
        passes it to ChannelStream. grpc_addr (e.g. "127.0.0.1:port") is for later
        FeedBlockPlan / SubscribeBlockEvents RPCs.

    Raises:
        RuntimeError: If Air binary not found, not executable, gRPC connect fails,
            or StartChannel/AttachStream/StartBlockPlanSession times out or fails.
    """
    channel_id = playout_request.get("channel_id", "unknown")
    join_utc_ms = int(playout_request.get("join_utc_ms", 0) or 0)
    current_block = playout_request.get("current_block")
    next_block = playout_request.get("next_block")
    evidence_endpoint = str(playout_request.get("evidence_endpoint", "") or "")

    if not isinstance(current_block, ScheduledBlock) or not isinstance(next_block, ScheduledBlock):
        raise RuntimeError(
            "Core→AIR BlockPlan contract: launch_air requires current_block and next_block"
        )
    if join_utc_ms <= 0:
        raise RuntimeError(
            "Core→AIR BlockPlan contract: launch_air requires join_utc_ms"
        )

    # Use provided config or fall back to mock config for backwards compatibility
    config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG

    if ts_socket_path is None:
        socket_path = get_uds_socket_path(channel_id)
    else:
        socket_path = Path(ts_socket_path)

    ensure_socket_dir_exists(socket_path)

    air_bin = _find_air_binary()
    if air_bin is None:
        raise RuntimeError(
            "Air playout engine unavailable: retrovue_air binary not found. "
            "Build runtime (retrovue_air target) or set RETROVUE_AIR_EXE."
        )

    proc, socket_path, reader_socket_queue, grpc_addr = _launch_air_binary(
        air_bin=air_bin,
        socket_path=socket_path,
        channel_id=channel_id,
        channel_config=config,
        join_utc_ms=join_utc_ms,
        current_block=current_block,
        next_block=next_block,
        evidence_endpoint=evidence_endpoint,
        reader_socket_queue=reader_socket_queue,
        stdout=stdout,
        stderr=stderr,
    )
    return proc, socket_path, reader_socket_queue, grpc_addr


def _launch_ffmpeg_fallback(
    asset_path: str,
    start_pts_ms: int,
    socket_path: Path,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> tuple[ProcessHandle, Path]:
    """FFmpeg fallback removed. Air is the only playout engine. Fail fast instead."""
    raise RuntimeError(
        "ffmpeg fallback removed. Air is the only playout engine. "
        "Build retrovue_air (runtime) or set RETROVUE_AIR_EXE. Do not use RETROVUE_USE_FFMPEG."
    )


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
    "air_load_preview",
    "air_switch_to_live",
    "terminate_air",
    "SwitchTimingError",
    "SwitchProtocolError",
    "ProcessHandle",
    "get_uds_socket_path",
    "ensure_socket_dir_exists",
]
