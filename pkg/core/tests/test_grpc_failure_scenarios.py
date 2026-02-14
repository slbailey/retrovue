"""
Failure-scenario integration tests: broadcast-grade resilience.

Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md
Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md

Scenarios:
1. Core crash mid-block — emit 4 events, kill Core before ACK on 4th,
   restart Core, AIR replays from spool, verify no loss.
2. AIR crash mid-block — emit 4 events, kill AIR (simulated), restart
   with same playout_session_id, replay from spool, verify no event loss.
3. Duplicate replay — force replay of already-acked events, verify Core
   deduplicates via event_uuid and durable ack high-water mark.
"""
from __future__ import annotations

import json
import logging
import os
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

CHANNEL_ID = "failure-test-ch"
SESSION_ID = "PS-failure-001"


def _make_hello(last_seq: int) -> pb2.EvidenceFromAir:
    msg = pb2.EvidenceFromAir(
        schema_version=1,
        channel_id=CHANNEL_ID,
        playout_session_id=SESSION_ID,
        sequence=0,
        event_uuid="hello",
        emitted_utc="",
    )
    msg.hello.CopyFrom(
        pb2.Hello(first_sequence_available=1, last_sequence_emitted=last_seq)
    )
    return msg


def _make_event(seq: int) -> pb2.EvidenceFromAir:
    msg = pb2.EvidenceFromAir(
        schema_version=1,
        channel_id=CHANNEL_ID,
        playout_session_id=SESSION_ID,
        sequence=seq,
        event_uuid=f"uuid-{seq}",
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


class TestCoreCrashMidBlock:
    """Core crash mid-block: emit 4 events, kill Core after ACK 2,
    restart, AIR replays from last durable ACK, verify no event loss."""

    def test_core_crash_replays_from_last_durable_ack(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        # === Phase 1: Start Core, send HELLO + 4 events, ack all, then kill ===
        ack_store_1 = DurableAckStore(ack_dir=ack_dir)
        server_1, port = _start_server(ack_store_1, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        phase1_msgs = [
            _make_hello(last_seq=4),
            _make_event(1),
            _make_event(2),
        ]

        phase1_acks = list(stub.EvidenceStream(iter(phase1_msgs)))
        # HELLO ACK + 2 event ACKs.
        assert len(phase1_acks) == 3
        assert phase1_acks[-1].acked_sequence == 2

        channel.close()

        # Verify durable ack is at 2.
        assert ack_store_1.get(CHANNEL_ID, SESSION_ID) == 2

        # Kill Core (simulate crash).
        server_1.stop(grace=0).wait()

        # === Phase 2: Restart Core with same durable ack store ===
        # AIR reconnects with HELLO(last_emitted=4), replays 3+4 from spool.
        ack_store_2 = DurableAckStore(ack_dir=ack_dir)
        # Verify the store loaded durable ack = 2 from disk.
        assert ack_store_2.get(CHANNEL_ID, SESSION_ID) == 2

        server_2, port2 = _start_server(ack_store_2, asrun_dir)
        channel2 = grpc.insecure_channel(f"localhost:{port2}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        phase2_msgs = [
            _make_hello(last_seq=4),
            _make_event(3),  # unacked — must be written
            _make_event(4),  # unacked — must be written
        ]

        phase2_acks = list(stub2.EvidenceStream(iter(phase2_msgs)))
        assert len(phase2_acks) == 3  # HELLO ack + 2 event acks
        assert phase2_acks[-1].acked_sequence == 4

        channel2.close()
        server_2.stop(grace=0).wait()

        # === Verify: durable ack advanced to 4 ===
        final_store = DurableAckStore(ack_dir=ack_dir)
        assert final_store.get(CHANNEL_ID, SESSION_ID) == 4

        # === Verify: .asrun.jsonl has all 4 events, no duplicates ===
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1
        records = [
            json.loads(l)
            for l in jsonl_files[0].read_text().strip().splitlines()
            if l.strip()
        ]
        event_ids = [r["event_id"] for r in records]
        assert event_ids == ["block-1", "block-2", "block-3", "block-4"], (
            f"Expected all 4 events across restarts, got {event_ids}"
        )
        assert len(set(event_ids)) == 4, f"Duplicate events: {event_ids}"


class TestAirCrashMidBlock:
    """AIR crash mid-block: emit 4 events via stream, AIR disconnects
    after seq 2, reconnects with same session, replays from spool,
    Core sees all 4 with no loss."""

    def test_air_crash_replays_from_spool(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        # === Phase 1: AIR sends HELLO + events 1,2 then disconnects ===
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        phase1_msgs = [
            _make_hello(last_seq=4),
            _make_event(1),
            _make_event(2),
        ]

        phase1_acks = list(stub.EvidenceStream(iter(phase1_msgs)))
        assert len(phase1_acks) == 3
        assert phase1_acks[-1].acked_sequence == 2
        channel.close()

        # Core durable ack is at 2.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 2

        # === Phase 2: AIR "restarts" (same session_id), replays from spool ===
        # AIR's spool has events 1-4 locally. Core acked up to 2.
        # AIR sends HELLO(last_emitted=4), Core replies with ack=2.
        # AIR replays 3+4 (seq > acked).
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        # Simulate AIR spool replay: send events 1-4 (spool replays all).
        # Core deduplicates 1,2 (seq <= durable ack) and writes only 3,4.
        phase2_msgs = [
            _make_hello(last_seq=4),
            _make_event(1),  # already committed (seq <= 2)
            _make_event(2),  # already committed
            _make_event(3),  # new
            _make_event(4),  # new
        ]

        phase2_acks = list(stub2.EvidenceStream(iter(phase2_msgs)))
        assert len(phase2_acks) == 5  # HELLO + 4 events
        assert phase2_acks[-1].acked_sequence == 4
        channel2.close()

        server.stop(grace=0).wait()

        # === Verify: all 4 unique events written, no duplicates ===
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1
        records = [
            json.loads(l)
            for l in jsonl_files[0].read_text().strip().splitlines()
            if l.strip()
        ]
        event_ids = [r["event_id"] for r in records]
        assert event_ids == ["block-1", "block-2", "block-3", "block-4"], (
            f"Expected all 4 unique events, got {event_ids}"
        )
        assert len(set(event_ids)) == 4, f"Duplicate events found: {event_ids}"

        # Final ack is 4.
        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 4


class TestDuplicateReplay:
    """Force replay of already-acked events.
    Verify Core deduplicates via durable ack high-water mark + event_uuid."""

    def test_duplicate_events_deduplicated(self, tmp_path):
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Send 5 events normally.
        messages = [
            _make_hello(last_seq=5),
            _make_event(1),
            _make_event(2),
            _make_event(3),
            _make_event(4),
            _make_event(5),
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        assert len(acks) == 6
        assert acks[-1].acked_sequence == 5
        channel.close()

        assert ack_store.get(CHANNEL_ID, SESSION_ID) == 5

        # === Phase 2: Force full replay of all 5 (simulates AIR replaying
        # entire spool after reconnect, despite ack being 5) ===
        channel2 = grpc.insecure_channel(f"localhost:{port}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        replay_messages = [
            _make_hello(last_seq=5),
            _make_event(1),  # duplicate (seq <= 5)
            _make_event(2),  # duplicate
            _make_event(3),  # duplicate
            _make_event(4),  # duplicate
            _make_event(5),  # duplicate
        ]

        replay_acks = list(stub2.EvidenceStream(iter(replay_messages)))
        # All 6 messages still get ACKed (even duplicates are ACKed per contract).
        assert len(replay_acks) == 6
        # Final ack is still 5.
        assert replay_acks[-1].acked_sequence == 5
        channel2.close()

        server.stop(grace=0).wait()

        # === Verify: exactly 5 unique entries in .asrun.jsonl ===
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1
        records = [
            json.loads(l)
            for l in jsonl_files[0].read_text().strip().splitlines()
            if l.strip()
        ]
        event_ids = [r["event_id"] for r in records]
        assert len(event_ids) == 5, (
            f"Expected exactly 5 entries (no dupes), got {len(event_ids)}: {event_ids}"
        )
        assert event_ids == [
            "block-1", "block-2", "block-3", "block-4", "block-5"
        ], f"Wrong event_ids: {event_ids}"
        assert len(set(event_ids)) == 5, f"Duplicate event_ids: {event_ids}"

    def test_intra_stream_uuid_dedup(self, tmp_path):
        """Within a single stream, duplicate event_uuids are deduplicated."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Send 3 events, then repeat event 2 and 3 with same uuid in same stream.
        messages = [
            _make_hello(last_seq=3),
            _make_event(1),
            _make_event(2),
            _make_event(3),
            _make_event(2),  # intra-stream duplicate uuid-2
            _make_event(3),  # intra-stream duplicate uuid-3
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        # All 6 messages get ACKed (HELLO + 5 events/dupes).
        assert len(acks) == 6

        channel.close()
        server.stop(grace=0).wait()

        # Verify exactly 3 unique entries — duplicates were not written.
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1
        records = [
            json.loads(l)
            for l in jsonl_files[0].read_text().strip().splitlines()
            if l.strip()
        ]
        event_ids = [r["event_id"] for r in records]
        assert len(event_ids) == 3, (
            f"Expected 3 unique entries, got {len(event_ids)}: {event_ids}"
        )
        assert len(set(event_ids)) == 3, f"Duplicate event_ids: {event_ids}"
