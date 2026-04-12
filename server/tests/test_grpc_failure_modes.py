"""
Failure-mode integration tests: gRPC evidence stream edge cases.

RETA-48: E.2 — gRPC failure mode testing expansion.

Contract: runtime/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md
Contract: (pending) docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md

Scenarios covered:
1. AIR crash mid-block — Core detects gRPC stream termination, reconnect works
2. Stale session handling — reconnect with different session_id
3. Network partition simulation — gRPC deadline exceeded
4. Evidence spool replay under concurrent writes
5. Duplicate HELLO — AIR sends HELLO twice on same stream
6. Out-of-order sequence — AIR sends seq N+2 before N+1

NOTE: Some scenarios document observed behavior pending E.1 contract
finalization (RETA-50). Tests that validate newly-documented E.1
invariants will be added once that contract lands on disk.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from concurrent import futures
from pathlib import Path

import grpc
import pytest

# Proto stubs path.
_PROTO_DIR = str(Path(__file__).resolve().parents[1] / "core" / "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import execution_evidence_v1_pb2 as pb2  # noqa: E402
import execution_evidence_v1_pb2_grpc as pb2_grpc  # noqa: E402

# Server implementation.
_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from retrovue.runtime.evidence_server import (  # noqa: E402
    DurableAckStore,
    EvidenceServicer,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

CHANNEL_ID = "failure-mode-ch"
SESSION_ID = "PS-fmode-001"
SESSION_ID_ALT = "PS-fmode-002"


def _make_hello(
    last_seq: int,
    channel_id: str = CHANNEL_ID,
    session_id: str = SESSION_ID,
) -> pb2.EvidenceFromAir:
    msg = pb2.EvidenceFromAir(
        schema_version=1,
        channel_id=channel_id,
        playout_session_id=session_id,
        sequence=0,
        event_uuid="hello",
        emitted_utc="",
    )
    msg.hello.CopyFrom(
        pb2.Hello(first_sequence_available=1, last_sequence_emitted=last_seq)
    )
    return msg


def _make_event(
    seq: int,
    channel_id: str = CHANNEL_ID,
    session_id: str = SESSION_ID,
    uuid_prefix: str = "uuid",
) -> pb2.EvidenceFromAir:
    msg = pb2.EvidenceFromAir(
        schema_version=1,
        channel_id=channel_id,
        playout_session_id=session_id,
        sequence=seq,
        event_uuid=f"{uuid_prefix}-{seq}",
        emitted_utc="2026-02-13T12:00:00.000Z",
    )
    msg.block_start.CopyFrom(
        pb2.BlockStart(
            block_id=f"block-{seq}",
            swap_tick=100,
            fence_tick=200,
            actual_start_utc_ms=1739448000000,
            primed_success=True,
        )
    )
    return msg


def _start_server(
    ack_store: DurableAckStore, asrun_dir: str
) -> tuple[grpc.Server, int]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    servicer = EvidenceServicer(ack_store=ack_store, asrun_dir=asrun_dir)
    pb2_grpc.add_ExecutionEvidenceServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("[::]:0")
    server.start()
    return server, port


def _read_asrun_events(asrun_dir: str) -> list[dict]:
    """Read all .asrun.jsonl records from the asrun directory."""
    records = []
    for jsonl_file in Path(asrun_dir).rglob("*.asrun.jsonl"):
        for line in jsonl_file.read_text().strip().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Scenario 5: Duplicate HELLO on same stream
# ---------------------------------------------------------------------------
class TestDuplicateHello:
    """AIR sends HELLO twice on the same stream.

    Expected behavior: second HELLO is ACKed but has no side effect.
    The server does not re-initialize session state or lose events
    received between the two HELLOs.
    """

    def test_duplicate_hello_acked_no_side_effects(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        messages = [
            _make_hello(last_seq=3),
            _make_event(1),
            _make_event(2),
            # Second HELLO mid-stream.
            _make_hello(last_seq=3),
            _make_event(3),
        ]

        acks = list(stub.EvidenceStream(iter(messages)))

        # All 5 messages should produce ACKs (2 HELLOs + 3 events).
        assert len(acks) == 5, f"Expected 5 ACKs, got {len(acks)}"

        # Final event ACK should be for sequence 3.
        event_acks = [a for a in acks if a.acked_sequence > 0]
        assert event_acks[-1].acked_sequence == 3

        channel.close()
        server.stop(grace=0).wait()

        # All 3 events should be written — the second HELLO must not
        # disrupt the as-run writing pipeline.
        records = _read_asrun_events(asrun_dir)
        event_ids = [r["event_id"] for r in records]
        assert event_ids == ["block-1", "block-2", "block-3"], (
            f"Duplicate HELLO disrupted event writing: {event_ids}"
        )

    def test_hello_after_all_events_is_harmless(self, tmp_path):
        """HELLO sent after all events (e.g. AIR bug) is still ACKed."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        messages = [
            _make_hello(last_seq=2),
            _make_event(1),
            _make_event(2),
            # Trailing HELLO (unusual but must not crash).
            _make_hello(last_seq=2),
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        assert len(acks) == 4

        channel.close()
        server.stop(grace=0).wait()

        records = _read_asrun_events(asrun_dir)
        assert len(records) == 2
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 2


# ---------------------------------------------------------------------------
# Scenario 6: Out-of-order sequence
# ---------------------------------------------------------------------------
class TestOutOfOrderSequence:
    """AIR sends sequence N+2 before N+1.

    The evidence server processes events by event_uuid dedup and
    durable ack high-water mark. Within a single stream, out-of-order
    sequences should still result in all events being written (no data
    loss), though the ack store advances monotonically.
    """

    def test_out_of_order_sequence_no_data_loss(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Send seq 1, then 3 (skip 2), then 2.
        messages = [
            _make_hello(last_seq=3),
            _make_event(1),
            _make_event(3),  # out of order
            _make_event(2),  # arrives late
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        # HELLO + 3 events = 4 ACKs.
        assert len(acks) == 4

        channel.close()
        server.stop(grace=0).wait()

        # All 3 events must be written — no data loss.
        records = _read_asrun_events(asrun_dir)
        event_ids = sorted([r["event_id"] for r in records])
        assert event_ids == ["block-1", "block-2", "block-3"], (
            f"Out-of-order caused data loss: {event_ids}"
        )

    def test_out_of_order_ack_is_monotonic(self, tmp_path):
        """Durable ack store advances monotonically even with out-of-order."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        messages = [
            _make_hello(last_seq=4),
            _make_event(1),
            _make_event(4),  # jump ahead
            _make_event(2),  # late arrival
            _make_event(3),  # late arrival
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        assert len(acks) == 5

        channel.close()
        server.stop(grace=0).wait()

        # Durable ack must be at highest sequence seen (4), not the last
        # one received (3). DurableAckStore.update is monotonic.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 4


# ---------------------------------------------------------------------------
# Scenario 3: Network partition simulation (gRPC deadline exceeded)
# ---------------------------------------------------------------------------
class TestNetworkPartition:
    """gRPC deadline exceeded — both sides handle timeout.

    When a client sets a short deadline and the server is slow (or the
    network is partitioned), the client sees DEADLINE_EXCEEDED. The
    server's iterator terminates. Partial data must be durable.
    """

    def test_deadline_exceeded_partial_data_durable(self, tmp_path):
        """Events ACKed before deadline are durably committed."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Send 2 events normally, then the stream will be interrupted
        # by a very short deadline on a second call.
        msgs_phase1 = [
            _make_hello(last_seq=2),
            _make_event(1),
            _make_event(2),
        ]

        acks = list(stub.EvidenceStream(iter(msgs_phase1)))
        assert len(acks) == 3
        assert acks[-1].acked_sequence == 2
        channel.close()

        # Verify durability of events committed before any partition.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 2

        # Phase 2: Open new stream with extremely short deadline.
        # The server should handle the cancelled context gracefully.
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        def slow_iter():
            yield _make_hello(last_seq=5)
            yield _make_event(3)
            # Simulate network delay — exceed the deadline.
            time.sleep(2.0)
            yield _make_event(4)
            yield _make_event(5)

        # Set a very tight deadline (100ms) to simulate partition.
        try:
            list(stub2.EvidenceStream(slow_iter(), timeout=0.1))
        except grpc.RpcError as e:
            # DEADLINE_EXCEEDED or CANCELLED is expected.
            assert e.code() in (
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.CANCELLED,
            ), f"Unexpected gRPC error: {e.code()}"

        channel2.close()
        server.stop(grace=0).wait()

        # Phase 1 events remain durable despite phase 2 failure.
        final_store = DurableAckStore(ack_dir=ack_dir)
        assert final_store.get(CHANNEL_ID, SESSION_ID) >= 2

    def test_server_survives_client_disconnect(self, tmp_path):
        """Server continues operating after a client abruptly disconnects."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # Client 1: connect, send events, abruptly close.
        channel1 = grpc.insecure_channel(f"localhost:{port}")
        stub1 = pb2_grpc.ExecutionEvidenceServiceStub(channel1)

        msgs = [
            _make_hello(last_seq=2),
            _make_event(1),
            _make_event(2),
        ]
        acks = list(stub1.EvidenceStream(iter(msgs)))
        assert len(acks) == 3
        channel1.close()  # abrupt close

        # Client 2: connect to same server — must work fine.
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        # Different session to avoid cross-session dedup interference.
        msgs2 = [
            _make_hello(last_seq=1, session_id=SESSION_ID_ALT),
            _make_event(1, session_id=SESSION_ID_ALT, uuid_prefix="alt"),
        ]
        acks2 = list(stub2.EvidenceStream(iter(msgs2)))
        assert len(acks2) == 2
        assert acks2[-1].acked_sequence == 1

        channel2.close()
        server.stop(grace=0).wait()

        # Both sessions must have their data.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 2
        assert ack_store.get(CHANNEL_ID, SESSION_ID_ALT) == 1


# ---------------------------------------------------------------------------
# Scenario 2: Stale session handling
# ---------------------------------------------------------------------------
class TestStaleSession:
    """AIR reconnects with a different or expired session_id.

    Current behavior: the evidence server is session-agnostic — it
    accepts any session_id and tracks acks per (channel_id, session_id).
    A new session_id starts fresh (ack=0). This test documents that
    behavior. If E.1 adds session validation, these tests should be
    updated to verify rejection.
    """

    def test_new_session_id_starts_fresh_ack(self, tmp_path):
        """A different session_id on reconnect starts with ack=0."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # Session 1: send 3 events.
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)
        msgs = [
            _make_hello(last_seq=3, session_id=SESSION_ID),
            _make_event(1, session_id=SESSION_ID),
            _make_event(2, session_id=SESSION_ID),
            _make_event(3, session_id=SESSION_ID),
        ]
        acks = list(stub.EvidenceStream(iter(msgs)))
        assert acks[-1].acked_sequence == 3
        channel.close()

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 3

        # Session 2: different session_id — ack starts at 0.
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)
        msgs2 = [
            _make_hello(last_seq=2, session_id=SESSION_ID_ALT),
            _make_event(1, session_id=SESSION_ID_ALT, uuid_prefix="alt"),
            _make_event(2, session_id=SESSION_ID_ALT, uuid_prefix="alt"),
        ]
        acks2 = list(stub2.EvidenceStream(iter(msgs2)))
        assert len(acks2) == 3
        assert acks2[-1].acked_sequence == 2
        channel2.close()

        server.stop(grace=0).wait()

        # Both sessions have independent ack tracking.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 3
        assert ack_store.get(CHANNEL_ID, SESSION_ID_ALT) == 2

    def test_reuse_old_session_id_resumes_from_durable_ack(self, tmp_path):
        """Re-using a prior session_id resumes from its durable ack."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # Phase 1: Session sends 3 events.
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)
        msgs = [
            _make_hello(last_seq=3),
            _make_event(1),
            _make_event(2),
            _make_event(3),
        ]
        acks = list(stub.EvidenceStream(iter(msgs)))
        assert acks[-1].acked_sequence == 3
        channel.close()

        # Phase 2: Same session_id reconnects and replays all from spool.
        # Events 1-3 should be deduplicated (seq <= durable ack).
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)
        msgs2 = [
            _make_hello(last_seq=5),
            _make_event(1),  # duplicate (seq <= 3)
            _make_event(2),  # duplicate
            _make_event(3),  # duplicate
            _make_event(4),  # new
            _make_event(5),  # new
        ]
        acks2 = list(stub2.EvidenceStream(iter(msgs2)))
        assert len(acks2) == 6  # all ACKed
        assert acks2[-1].acked_sequence == 5
        channel2.close()

        server.stop(grace=0).wait()

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 5

        # Only events 4+5 should be new in as-run (1-3 deduplicated).
        records = _read_asrun_events(asrun_dir)
        event_ids = [r["event_id"] for r in records]
        # Phase 1 wrote 1-3, phase 2 wrote only 4-5.
        assert event_ids == [
            "block-1", "block-2", "block-3", "block-4", "block-5"
        ], f"Expected 5 unique events, got {event_ids}"


# ---------------------------------------------------------------------------
# Scenario 4: Evidence spool replay under concurrent writes
# ---------------------------------------------------------------------------
class TestConcurrentReplayAndEmit:
    """AIR continues emitting new events while replaying from spool.

    Simulated: a single stream sends replayed (already-acked) events
    interleaved with new events. Both classes must be handled correctly.
    """

    def test_interleaved_replay_and_new_events(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        # Pre-seed ack at 3 (simulate prior session committed 1-3).
        ack_store = DurableAckStore(ack_dir=ack_dir)
        ack_store.update(CHANNEL_ID, SESSION_ID, 3)

        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Interleave: replay seq 1 (dup), new seq 4, replay seq 2 (dup),
        # new seq 5, replay seq 3 (dup), new seq 6.
        messages = [
            _make_hello(last_seq=6),
            _make_event(1),  # dup (seq <= 3)
            _make_event(4),  # new
            _make_event(2),  # dup
            _make_event(5),  # new
            _make_event(3),  # dup
            _make_event(6),  # new
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        # HELLO + 6 events = 7 ACKs.
        assert len(acks) == 7

        channel.close()
        server.stop(grace=0).wait()

        # Only events 4, 5, 6 should be written (1-3 deduped).
        records = _read_asrun_events(asrun_dir)
        event_ids = [r["event_id"] for r in records]
        assert event_ids == ["block-4", "block-5", "block-6"], (
            f"Expected only new events, got {event_ids}"
        )

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 6

    def test_high_volume_replay_with_concurrent_new(self, tmp_path):
        """Higher volume: 50 replayed + 50 new, interleaved."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        ack_store.update(CHANNEL_ID, SESSION_ID, 50)

        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        messages = [_make_hello(last_seq=100)]
        # Interleave: replay 1..50 and new 51..100
        for i in range(1, 51):
            messages.append(_make_event(i))       # replay (seq <= 50)
            messages.append(_make_event(i + 50))   # new

        acks = list(stub.EvidenceStream(iter(messages)))
        # HELLO + 100 events = 101 ACKs
        assert len(acks) == 101

        channel.close()
        server.stop(grace=0).wait()

        # Only 50 new events should be written.
        records = _read_asrun_events(asrun_dir)
        assert len(records) == 50, (
            f"Expected 50 new events, got {len(records)}"
        )

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 100


# ---------------------------------------------------------------------------
# Scenario 1: AIR crash mid-block (stream termination detection)
# ---------------------------------------------------------------------------
class TestAirCrashStreamTermination:
    """AIR crashes mid-block: gRPC stream terminates abruptly.

    Core must:
    - Detect the stream termination (iterator ends or raises)
    - Persist all ACKed events durably
    - Accept a new stream from AIR on reconnect
    - Resume from durable ack on the new stream
    """

    def test_abrupt_stream_end_preserves_acked_data(self, tmp_path):
        """Stream ends after 2 events (simulating AIR crash).
        Events 1+2 are durable. New stream resumes from ack=2."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # Phase 1: AIR sends 2 events then "crashes" (stream ends).
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        phase1 = [
            _make_hello(last_seq=5),
            _make_event(1),
            _make_event(2),
            # stream ends here — AIR crash
        ]
        acks1 = list(stub.EvidenceStream(iter(phase1)))
        assert len(acks1) == 3
        assert acks1[-1].acked_sequence == 2
        channel.close()

        # Acked data is durable.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 2

        # Phase 2: AIR reconnects, replays from spool, sends remaining.
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        phase2 = [
            _make_hello(last_seq=5),
            _make_event(1),  # dup
            _make_event(2),  # dup
            _make_event(3),  # new
            _make_event(4),  # new
            _make_event(5),  # new
        ]
        acks2 = list(stub2.EvidenceStream(iter(phase2)))
        assert len(acks2) == 6
        assert acks2[-1].acked_sequence == 5
        channel2.close()

        server.stop(grace=0).wait()

        # All 5 events written, no duplicates.
        records = _read_asrun_events(asrun_dir)
        event_ids = [r["event_id"] for r in records]
        assert event_ids == [
            "block-1", "block-2", "block-3", "block-4", "block-5"
        ], f"Expected all 5 events, got {event_ids}"

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 5

    def test_crash_with_zero_events_is_safe(self, tmp_path):
        """AIR crashes immediately after HELLO — no events sent.
        No data loss, no corruption. Server stays healthy."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # Only HELLO, then crash.
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        msgs = [_make_hello(last_seq=0)]
        acks = list(stub.EvidenceStream(iter(msgs)))
        assert len(acks) == 1  # HELLO ACK
        channel.close()

        # Ack should still be 0.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 0

        # Server still accepts new connections.
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        msgs2 = [
            _make_hello(last_seq=1, session_id=SESSION_ID_ALT),
            _make_event(1, session_id=SESSION_ID_ALT, uuid_prefix="alt"),
        ]
        acks2 = list(stub2.EvidenceStream(iter(msgs2)))
        assert len(acks2) == 2
        channel2.close()

        server.stop(grace=0).wait()

        assert ack_store.get(CHANNEL_ID, SESSION_ID_ALT) == 1
