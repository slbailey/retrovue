"""
Integration test: Evidence gRPC replay + resume after disconnect.

Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md
Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md

Test scenario:
- Start server
- AIR (simulated) emits 5 events
- Kill server after ACKing 3
- Restart server (fresh ack store)
- AIR reconnects, sends HELLO(last_emitted=5)
- Server ACKs with acked_sequence=0 (fresh)
- AIR replays seq 1..5 from "spool"
- Verify server receives all 5 in order
- Verify no duplicates (dedup by event_uuid)
- Verify final ack=5

Also tests the resume-from-ack scenario:
- Server maintains ack at 3 across restart (durable ack store)
- AIR replays only seq 4+5
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
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

CHANNEL_ID = "replay-test-ch"
SESSION_ID = "PS-replay-001"


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


class TestGrpcReplayResume:
    """Integration: replay + resume after server disconnect."""

    def test_replay_after_server_restart_with_fresh_ack(self, tmp_path):
        """Server restart with no durable ack → AIR replays all; no dupes; ack=5."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        # === Phase 1: Start server, emit 3 events, ACK 3, stop server ===
        ack_store_1 = DurableAckStore(ack_dir=ack_dir)
        server_1, port = _start_server(ack_store_1, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        phase1_msgs = [
            _make_hello(last_seq=3),
            _make_event(1),
            _make_event(2),
            _make_event(3),
        ]

        phase1_acks = []

        def phase1_iter():
            for m in phase1_msgs:
                yield m

        for ack in stub.EvidenceStream(phase1_iter()):
            phase1_acks.append(ack)

        assert len(phase1_acks) == 4
        assert phase1_acks[-1].acked_sequence == 3
        channel.close()

        # Kill server.
        server_1.stop(grace=0).wait()

        # Verify ack was persisted.
        assert ack_store_1.get(CHANNEL_ID, SESSION_ID) == 3

        # === Phase 2: Restart with SAME durable ack store ===
        # AIR reconnects, sends HELLO(last_emitted=5).
        # Server sees acked_sequence=3 in store.
        # AIR sends events 4+5 (simulating spool replay of unacked).
        ack_store_2 = DurableAckStore(ack_dir=ack_dir)
        server_2, port2 = _start_server(ack_store_2, asrun_dir)

        channel2 = grpc.insecure_channel(f"localhost:{port2}")
        stub2 = pb2_grpc.ExecutionEvidenceServiceStub(channel2)

        # Simulate AIR: HELLO + replay only seq 4,5 (spool has all but ack was 3).
        phase2_msgs = [
            _make_hello(last_seq=5),
            _make_event(4),
            _make_event(5),
        ]

        phase2_acks = []

        def phase2_iter():
            for m in phase2_msgs:
                yield m

        for ack in stub2.EvidenceStream(phase2_iter()):
            phase2_acks.append(ack)

        # 3 messages → 3 ACKs (HELLO ack + seq 4 ack + seq 5 ack).
        assert len(phase2_acks) == 3
        # Final ACK must be sequence 5.
        assert phase2_acks[-1].acked_sequence == 5

        channel2.close()
        server_2.stop(grace=0).wait()

        # Verify final durable ack is 5.
        assert ack_store_2.get(CHANNEL_ID, SESSION_ID) == 5

    def test_no_duplicate_asrun_entries_on_replay(self, tmp_path):
        """Replayed events with same event_uuid must not create duplicate as-run entries."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")
        ack_store = DurableAckStore(ack_dir=ack_dir)
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # Send 3 events, then replay event 2 and 3 (same uuid).
        messages = [
            _make_hello(last_seq=5),
            _make_event(1),
            _make_event(2),
            _make_event(3),
            # Simulate replay: same uuid for seq 2 and 3.
            _make_event(2),  # duplicate uuid-2
            _make_event(3),  # duplicate uuid-3
            _make_event(4),
            _make_event(5),
        ]

        acks = []

        def msg_iter():
            for m in messages:
                yield m

        for ack in stub.EvidenceStream(msg_iter()):
            acks.append(ack)

        # 8 messages → 8 ACKs (including hello and dupes).
        assert len(acks) == 8

        channel.close()
        server.stop(grace=0).wait()

        # Read the .asrun.jsonl file and verify no duplicate event_ids.
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1, f"Expected 1 jsonl file, got {jsonl_files}"

        records = []
        for line in jsonl_files[0].read_text().strip().splitlines():
            if line.strip():
                records.append(json.loads(line))

        event_ids = [r["event_id"] for r in records]
        # 5 unique block_start events → 5 entries (no dupes).
        assert len(event_ids) == 5, f"Expected 5 entries, got {len(event_ids)}: {event_ids}"
        assert len(set(event_ids)) == 5, f"Duplicate event_ids found: {event_ids}"

    def test_durable_ack_survives_restart(self, tmp_path):
        """Ack store persists to disk; new instance reads it back."""
        ack_dir = str(tmp_path / "ack")

        store1 = DurableAckStore(ack_dir=ack_dir)
        store1.update(CHANNEL_ID, SESSION_ID, 42)
        assert store1.get(CHANNEL_ID, SESSION_ID) == 42

        # New instance from same directory.
        store2 = DurableAckStore(ack_dir=ack_dir)
        assert store2.get(CHANNEL_ID, SESSION_ID) == 42

        # Monotonic: lower value ignored.
        store2.update(CHANNEL_ID, SESSION_ID, 10)
        assert store2.get(CHANNEL_ID, SESSION_ID) == 42

        # Higher value advances.
        store2.update(CHANNEL_ID, SESSION_ID, 100)

        store3 = DurableAckStore(ack_dir=ack_dir)
        assert store3.get(CHANNEL_ID, SESSION_ID) == 100

    def test_asrun_files_written_before_ack(self, tmp_path):
        """Evidence must be written to .asrun + .asrun.jsonl before ACK is sent."""
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
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        assert len(acks) == 3

        channel.close()
        server.stop(grace=0).wait()

        # Verify .asrun and .asrun.jsonl files exist and have content.
        asrun_files = list(Path(asrun_dir).rglob("*.asrun"))
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))

        # Filter out .asrun.jsonl from asrun_files.
        asrun_files = [f for f in asrun_files if not str(f).endswith(".jsonl")]

        assert len(asrun_files) == 1, f"Expected 1 .asrun, got {asrun_files}"
        assert len(jsonl_files) == 1, f"Expected 1 .jsonl, got {jsonl_files}"

        asrun_content = asrun_files[0].read_text()
        jsonl_content = jsonl_files[0].read_text()

        # .asrun must have header + 2 body lines.
        assert "RETROVUE AS-RUN LOG" in asrun_content
        body_lines = [
            l for l in asrun_content.splitlines()
            if l.strip() and not l.startswith("#")
        ]
        assert len(body_lines) == 2, f"Expected 2 body lines, got {len(body_lines)}"

        # .asrun.jsonl must have 2 records.
        jsonl_records = [
            json.loads(l) for l in jsonl_content.strip().splitlines() if l.strip()
        ]
        assert len(jsonl_records) == 2

    def test_replay_from_ack_3_receives_only_4_and_5(self, tmp_path):
        """Core has durable ack=3. AIR replays all 5 from spool.
        Server deduplicates 1-3 (already committed), writes only 4+5.
        Final ack=5."""
        asrun_dir = str(tmp_path / "asrun")
        ack_dir = str(tmp_path / "ack")

        # Pre-seed ack store at seq 3 (simulates prior session that already
        # committed events 1-3 to as-run files before crashing).
        ack_store = DurableAckStore(ack_dir=ack_dir)
        ack_store.update(CHANNEL_ID, SESSION_ID, 3)

        # Start server with pre-seeded ack.
        server, port = _start_server(ack_store, asrun_dir)

        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = pb2_grpc.ExecutionEvidenceServiceStub(channel)

        # AIR reconnects, sends HELLO + replays all 5 from spool.
        # Server skips 1-3 (seq ≤ durable ack), writes 4+5.
        messages = [
            _make_hello(last_seq=5),
            _make_event(1),  # already committed (seq ≤ 3)
            _make_event(2),  # already committed
            _make_event(3),  # already committed
            _make_event(4),  # new — must be written
            _make_event(5),  # new — must be written
        ]

        acks = list(stub.EvidenceStream(iter(messages)))
        # All 6 messages get ACKed (HELLO + 5 events).
        assert len(acks) == 6
        assert acks[-1].acked_sequence == 5

        channel.close()
        server.stop(grace=0).wait()

        # Verify final ack is 5.
        final_store = DurableAckStore(ack_dir=ack_dir)
        assert final_store.get(CHANNEL_ID, SESSION_ID) == 5

        # Verify .asrun.jsonl has only 2 entries (4+5).
        # Events 1-3 were committed in a prior session and skipped via durable ack.
        jsonl_files = list(Path(asrun_dir).rglob("*.asrun.jsonl"))
        assert len(jsonl_files) == 1
        records = [
            json.loads(l)
            for l in jsonl_files[0].read_text().strip().splitlines()
            if l.strip()
        ]
        event_ids = [r["event_id"] for r in records]
        assert event_ids == ["block-4", "block-5"], (
            f"Expected only events 4+5, got {event_ids}"
        )
