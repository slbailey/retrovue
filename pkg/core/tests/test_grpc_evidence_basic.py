"""
Integration test: Evidence gRPC bidirectional stream.

Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md

Tests:
- Start Core evidence gRPC server
- Open bidirectional stream (simulating AIR client)
- Send HELLO + 3 evidence events
- Verify server receives in order
- Verify ack sequence increments correctly
"""
from __future__ import annotations

import logging
import sys
import threading
import time
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

from retrovue.runtime.evidence_server import EvidenceServicer  # noqa: E402

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.fixture()
def evidence_server():
    """Start evidence gRPC server on an ephemeral port, yield (server, port)."""
    from concurrent import futures

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb2_grpc.add_ExecutionEvidenceServiceServicer_to_server(
        EvidenceServicer(), server
    )
    port = server.add_insecure_port("[::]:0")
    server.start()
    yield server, port
    server.stop(grace=2)


def _make_hello(channel_id: str, session_id: str, last_seq: int) -> pb2.EvidenceFromAir:
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


def _make_block_start(
    channel_id: str, session_id: str, seq: int, block_id: str
) -> pb2.EvidenceFromAir:
    msg = pb2.EvidenceFromAir(
        schema_version=1,
        channel_id=channel_id,
        playout_session_id=session_id,
        sequence=seq,
        event_uuid=f"uuid-{seq}",
        emitted_utc="2026-02-13T12:00:00.000Z",
    )
    msg.block_start.CopyFrom(
        pb2.BlockStart(
            block_id=block_id,
            swap_tick=100,
            fence_tick=200,
            actual_start_utc_ms=1739448000000,
            primed_success=True,
        )
    )
    return msg


class TestGrpcEvidenceBasic:
    """Integration: server receives ordered evidence and ACKs correctly."""

    def test_hello_and_three_events_acked_in_order(self, evidence_server):
        server, port = evidence_server
        channel_id = "test-ch-1"
        session_id = "PS-test-001"

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Messages to send: HELLO + 3 evidence events.
        messages = [
            _make_hello(channel_id, session_id, last_seq=3),
            _make_block_start(channel_id, session_id, seq=1, block_id="block-1"),
            _make_block_start(channel_id, session_id, seq=2, block_id="block-2"),
            _make_block_start(channel_id, session_id, seq=3, block_id="block-3"),
        ]

        # Collect ACKs from the bidirectional stream.
        acks: list[pb2.EvidenceAckFromCore] = []
        send_complete = threading.Event()

        def request_iterator():
            for msg in messages:
                yield msg
            send_complete.set()

        responses = stub.EvidenceStream(request_iterator())

        for ack in responses:
            acks.append(ack)
            if len(acks) == 4:
                break

        # Verify: 4 ACKs (HELLO seq=0, then seq=1,2,3).
        assert len(acks) == 4, f"Expected 4 ACKs, got {len(acks)}"

        # HELLO ACK has acked_sequence=0.
        assert acks[0].acked_sequence == 0
        assert acks[0].channel_id == channel_id
        assert acks[0].playout_session_id == session_id

        # Evidence ACKs have strictly incrementing sequences.
        assert acks[1].acked_sequence == 1
        assert acks[2].acked_sequence == 2
        assert acks[3].acked_sequence == 3

        channel.close()

    def test_ack_contains_correct_identifiers(self, evidence_server):
        server, port = evidence_server
        channel_id = "id-check-ch"
        session_id = "PS-id-check"

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        messages = [
            _make_block_start(channel_id, session_id, seq=1, block_id="blk"),
        ]

        def request_iterator():
            for msg in messages:
                yield msg

        responses = stub.EvidenceStream(request_iterator())

        ack = next(responses)
        assert ack.channel_id == channel_id
        assert ack.playout_session_id == session_id
        assert ack.acked_sequence == 1
        assert ack.error == ""

        channel.close()

    def test_server_handles_multiple_streams(self, evidence_server):
        """Two independent streams should not interfere."""
        server, port = evidence_server

        results = {}

        def run_stream(ch_id: str, sess_id: str):
            ch = grpc.insecure_channel(f"localhost:{port}")
            stub = pb2_grpc.ExecutionEvidenceServiceStub(ch)

            messages = [
                _make_block_start(ch_id, sess_id, seq=1, block_id="b1"),
                _make_block_start(ch_id, sess_id, seq=2, block_id="b2"),
            ]

            def request_iter():
                for m in messages:
                    yield m

            acks = list(stub.EvidenceStream(request_iter()))
            results[ch_id] = acks
            ch.close()

        t1 = threading.Thread(target=run_stream, args=("ch-A", "PS-A"))
        t2 = threading.Thread(target=run_stream, args=("ch-B", "PS-B"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(results["ch-A"]) == 2
        assert len(results["ch-B"]) == 2
        assert results["ch-A"][0].channel_id == "ch-A"
        assert results["ch-B"][0].channel_id == "ch-B"
