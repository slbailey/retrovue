"""
Core-side gRPC server for the ExecutionEvidence stream.

Contract: docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md
Contract: docs/contracts/artifacts/AsRunLogArtifactContract.md (v0.2)
Contract: docs/contracts/core/ExecutionEvidenceToAsRunMappingContract_v0.1.md

Accepts bidirectional evidence streams from AIR.
For each message:
  - Maps evidence to .asrun + .asrun.jsonl via EvidenceToAsRunMapper
  - Writes and flushes both files
  - THEN sends ACK (ACK implies durability — contract §7)
  - Deduplicates on event_uuid (GRPC-EVID-003)

Maintains durable ack store per (channel_id, playout_session_id).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from concurrent import futures
from datetime import datetime, timezone
from pathlib import Path

import grpc

# Proto stubs live in pkg/core/core/proto/retrovue/; add to path for import.
_CORE_ROOT = Path(__file__).resolve().parents[3]  # pkg/core
_PROTO_DIR = str(_CORE_ROOT / "core" / "proto" / "retrovue")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import execution_evidence_v1_pb2 as pb2  # noqa: E402
import execution_evidence_v1_pb2_grpc as pb2_grpc  # noqa: E402

logger = logging.getLogger(__name__)

# Default as-run log directory (per AsRunLogArtifactContract v0.2 §2).
DEFAULT_ASRUN_DIR = "/opt/retrovue/data/logs/asrun"
# Default ack store directory.
DEFAULT_ACK_DIR = "/opt/retrovue/data/logs/evidence_ack"

# Fixed-width column widths for .asrun body (per AsRunLogArtifactContract v0.2 §3).
AW_ACTUAL, AW_DUR, AW_STATUS, AW_TYPE, AW_EVENT_ID = 8, 8, 10, 8, 32


def _ms_to_hhmmss(ms: int) -> str:
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _iso_to_display_time(iso_utc: str) -> str:
    if not iso_utc:
        return "00:00:00"
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.strftime("%H:%M:%S")


def _epoch_ms_to_display_time(epoch_ms: int) -> str:
    """Convert epoch ms to HH:MM:SS display time (UTC)."""
    if epoch_ms <= 0:
        return "00:00:00"
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%H:%M:%S")


def _epoch_ms_to_iso8601(epoch_ms: int) -> str:
    """Convert epoch ms to ISO8601 UTC string. Core is the single format authority."""
    if epoch_ms <= 0:
        return ""
    dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{epoch_ms % 1000:03d}Z"


def _format_asrun_line(
    actual: str, dur: str, status: str, type_: str, event_id: str, notes: str
) -> str:
    """Format a single .asrun body line per the fixed-width spec."""
    return (
        actual.ljust(AW_ACTUAL) + " "
        + dur.ljust(AW_DUR) + " "
        + status.ljust(AW_STATUS) + " "
        + type_.ljust(AW_TYPE) + " "
        + event_id.ljust(AW_EVENT_ID) + " "
        + notes
    )




# ---------------------------------------------------------------------------
# DB-backed segment lookup (replaces SegmentLookup singleton)
# Contract: docs/contracts/runtime/AsRunEnrichmentContract.md
# INV-ASRUN-ENRICH-SOURCE-001
# ---------------------------------------------------------------------------

# In-memory cache: block_id -> list of segment dicts
# Cleared on block completion (INV-ASRUN-ENRICH-CACHE-001).
_block_segment_cache: dict = {}
_block_segment_cache_lock = __import__("threading").Lock()
_BLOCK_SEGMENT_CACHE_MAX = 10


def _lookup_segment_from_db(block_id: str, segment_index: int) -> object | None:
    """Look up segment metadata from transmission_log.

    Returns a simple namespace with .title, .segment_type, .asset_uri,
    .segment_duration_ms, .asset_start_offset_ms attributes, or None if not found.

    Gracefully degrades (returns None) on any error (DB unavailable, missing row, etc.)
    INV-ASRUN-ENRICH-DEGRADE-001: Never raises; always degrades to None.
    """
    import types as _types

    # Check in-memory cache first (INV-ASRUN-ENRICH-CACHE-001)
    with _block_segment_cache_lock:
        segments = _block_segment_cache.get(block_id)

    if segments is None:
        try:
            from retrovue.infra.uow import session as db_session_factory
            from retrovue.domain.entities import TransmissionLog
            with db_session_factory() as db:
                row = db.query(TransmissionLog).filter(
                    TransmissionLog.block_id == block_id
                ).first()
                if row is None:
                    return None
                segments = row.segments or []

            # Cache the result (evict oldest if over limit)
            with _block_segment_cache_lock:
                if len(_block_segment_cache) >= _BLOCK_SEGMENT_CACHE_MAX:
                    oldest = next(iter(_block_segment_cache))
                    del _block_segment_cache[oldest]
                _block_segment_cache[block_id] = segments

        except Exception as e:
            logger.warning(
                "TXLOG: Segment lookup failed block_id=%s seg_idx=%d: %s",
                block_id, segment_index, e,
            )
            return None

    if segments is None:
        return None

    # Find segment by index
    seg_data = None
    for s in segments:
        if isinstance(s, dict) and s.get("segment_index") == segment_index:
            seg_data = s
            break

    if seg_data is None:
        return None

    # Return as a simple namespace so callers can use attribute access
    info = _types.SimpleNamespace(
        segment_index=seg_data.get("segment_index", segment_index),
        segment_type=seg_data.get("segment_type", "content"),
        asset_uri=seg_data.get("asset_uri", ""),
        asset_start_offset_ms=seg_data.get("asset_start_offset_ms", 0),
        segment_duration_ms=seg_data.get("segment_duration_ms", 0),
        title=seg_data.get("title", ""),
    )
    return info



def prepopulate_block_segment_cache(block_id: str, segments: list) -> None:
    """Pre-populate segment cache with JIP-renumbered segments from the fed block.

    INV-ASRUN-JIP-ENRICH-001: When a block is fed to AIR after JIP renumbering,
    the segment_index values in the fed block may differ from the original
    TransmissionLog. Pre-populating ensures evidence_server uses the correct
    (renumbered) segment metadata for AsRun attribution.

    Called from BlockPlanProducer._try_feed_block() after successful feed.
    """
    with _block_segment_cache_lock:
        if len(_block_segment_cache) >= _BLOCK_SEGMENT_CACHE_MAX:
            oldest = next(iter(_block_segment_cache))
            del _block_segment_cache[oldest]
        _block_segment_cache[block_id] = segments

def _clear_block_segment_cache(block_id: str) -> None:
    """Clear cached segments for a completed block.

    INV-ASRUN-ENRICH-CACHE-001: Prevents stale data after block completion.
    """
    with _block_segment_cache_lock:
        _block_segment_cache.pop(block_id, None)

class DurableAckStore:
    """Thread-safe, per-session durable ack tracking.

    Stores highest acked_sequence in memory and persists to disk.
    """

    def __init__(self, ack_dir: str = DEFAULT_ACK_DIR):
        self._ack_dir = ack_dir
        self._lock = threading.Lock()
        # (channel_id, playout_session_id) → acked_sequence
        self._acks: dict[tuple[str, str], int] = {}

    def get(self, channel_id: str, session_id: str) -> int:
        key = (channel_id, session_id)
        with self._lock:
            if key not in self._acks:
                self._acks[key] = self._load_from_disk(channel_id, session_id)
            return self._acks[key]

    def update(self, channel_id: str, session_id: str, seq: int) -> None:
        key = (channel_id, session_id)
        with self._lock:
            current = self._acks.get(key, 0)
            if seq <= current:
                return
            self._acks[key] = seq
            self._persist_to_disk(channel_id, session_id, seq)

    def _ack_path(self, channel_id: str, session_id: str) -> Path:
        return Path(self._ack_dir) / channel_id / f"{session_id}.ack"

    def _load_from_disk(self, channel_id: str, session_id: str) -> int:
        path = self._ack_path(channel_id, session_id)
        if not path.exists():
            return 0
        try:
            text = path.read_text().strip()
            for line in text.splitlines():
                if line.startswith("acked_sequence="):
                    return int(line.split("=", 1)[1])
        except (ValueError, OSError):
            pass
        return 0

    def _persist_to_disk(self, channel_id: str, session_id: str, seq: int) -> None:
        path = self._ack_path(channel_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        content = f"acked_sequence={seq}\nupdated_utc={now_utc}\n"
        tmp = path.with_suffix(".ack.tmp")
        tmp.write_text(content)
        tmp.replace(path)


class AsRunWriter:
    """Writes .asrun and .asrun.jsonl files per session.

    Thread-safe: only called from the servicer which processes one stream
    sequentially.
    """

    def __init__(self, channel_id: str, asrun_dir: str = DEFAULT_ASRUN_DIR):
        self._channel_id = channel_id
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Broadcast-day start (midnight UTC) for display-time computation.
        # ACTUAL times are computed relative to this epoch; hours MAY exceed
        # 23 when execution crosses midnight (v0.2 §3).
        self._day_start_epoch_ms = int(
            datetime.strptime(today, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp() * 1000
        )
        base_dir = Path(asrun_dir) / channel_id
        base_dir.mkdir(parents=True, exist_ok=True)

        self._asrun_path = base_dir / f"{today}.asrun"
        self._jsonl_path = base_dir / f"{today}.asrun.jsonl"

        # Write header if file is new.
        if not self._asrun_path.exists() or self._asrun_path.stat().st_size == 0:
            now_utc = datetime.now(timezone.utc).isoformat() + "Z"
            header = (
                "# RETROVUE AS-RUN LOG\n"
                f"# CHANNEL: {channel_id}\n"
                f"# DATE: {today}\n"
                f"# OPENED_UTC: {now_utc}\n"
                f"# ASRUN_LOG_ID: {channel_id}-{today}\n"
                "# VERSION: 2\n"
            )
            with open(self._asrun_path, "w") as f:
                f.write(header)
                f.flush()
                os.fsync(f.fileno())

        self._asrun_fh = open(self._asrun_path, "a")
        self._jsonl_fh = open(self._jsonl_path, "a")

    def close(self) -> None:
        self._asrun_fh.close()
        self._jsonl_fh.close()

    def display_time(self, epoch_ms: int) -> str:
        """Convert epoch ms to broadcast-day-relative HH:MM:SS.

        Hours MAY exceed 23 for events crossing midnight (v0.2 §3).
        """
        if epoch_ms <= 0:
            return "00:00:00"
        offset_s = (epoch_ms - self._day_start_epoch_ms) // 1000
        if offset_s < 0:
            dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
            return dt.strftime("%H:%M:%S")
        h, rem = divmod(offset_s, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def write_and_flush(self, asrun_line: str, jsonl_record: dict) -> None:
        """Write one line to each file and flush both to disk."""
        self._asrun_fh.write(asrun_line + "\n")
        self._asrun_fh.flush()
        os.fsync(self._asrun_fh.fileno())

        self._jsonl_fh.write(json.dumps(jsonl_record, separators=(",", ":")) + "\n")
        self._jsonl_fh.flush()
        os.fsync(self._jsonl_fh.fileno())


class EvidenceServicer(pb2_grpc.ExecutionEvidenceServiceServicer):
    """Evidence stream handler with durable ACK semantics.

    For each evidence message:
    1. Map to .asrun + .asrun.jsonl entries
    2. Write + flush to disk
    3. THEN ACK (ACK implies durability)
    """

    def __init__(
        self,
        ack_store: DurableAckStore | None = None,
        asrun_dir: str = DEFAULT_ASRUN_DIR,
    ):
        self._ack_store = ack_store or DurableAckStore()
        self._asrun_dir = asrun_dir

    def EvidenceStream(self, request_iterator, context):
        """Bidirectional stream: receive evidence, write as-run, yield ACKs."""
        peer = context.peer()
        logger.debug("EvidenceStream opened from %s", peer)

        writer: AsRunWriter | None = None
        seen_uuids: set[str] = set()
        # AR-ART-008: track event_ids that already received a terminal status
        # to prevent duplicate terminal emission within a stream.
        emitted_terminals: set[tuple[str, int]] = set()
        # Track most recent segment_index from SEG_START so AIRED can echo it.
        last_segment_index: list[int] = [-1]
        # INV-AIR-SEGMENT-ID-001: Track segment_uuid for segment_end correlation
        last_segment_uuid: list[str] = [""]
        # Block start UTC ms for current block (set on block_start; used for SegmentStart warning).
        last_block_start_utc_ms: list[int | None] = [None]
        # Contiguity invariant: last asset_end_frame per block; join_in_progress per event_id.
        last_asset_end_frame_by_block: dict[str, int] = {}
        join_in_progress_by_event: dict[str, bool] = {}
        # Load the durable ack high-water mark so we can skip already-committed
        # events on replay (GRPC-EVID-003 cross-stream dedup).
        durable_ack_seq: int = 0

        try:
            for msg in request_iterator:
                payload_name = msg.WhichOneof("payload") or "unknown"

                logger.debug(
                    "Evidence seq=%d uuid=%s channel=%s session=%s type=%s",
                    msg.sequence,
                    msg.event_uuid,
                    msg.channel_id,
                    msg.playout_session_id,
                    payload_name,
                )

                # Initialize writer on first real message.
                if writer is None and msg.channel_id:
                    writer = AsRunWriter(msg.channel_id, self._asrun_dir)
                    # Load durable ack for this session to skip already-committed.
                    durable_ack_seq = self._ack_store.get(
                        msg.channel_id, msg.playout_session_id
                    )

                # GRPC-EVID-003: deduplicate on event_uuid (intra-stream)
                # and on durable ack high-water mark (cross-stream).
                is_duplicate = False
                if msg.event_uuid != "hello":
                    if msg.event_uuid in seen_uuids:
                        is_duplicate = True
                    elif msg.sequence > 0 and msg.sequence <= durable_ack_seq:
                        # Already durably committed in a prior stream.
                        is_duplicate = True
                    else:
                        seen_uuids.add(msg.event_uuid)

                if is_duplicate:
                    # Duplicate: ACK but don't write again.
                    yield pb2.EvidenceAckFromCore(
                        channel_id=msg.channel_id,
                        playout_session_id=msg.playout_session_id,
                        acked_sequence=msg.sequence,
                    )
                    continue

                # Map evidence to as-run artifacts and write durably.
                if writer is not None and payload_name != "hello":
                    self._process_evidence(
                        writer, msg, payload_name, emitted_terminals,
                        last_segment_index, last_block_start_utc_ms,
                        last_asset_end_frame_by_block, join_in_progress_by_event,
                        last_segment_uuid,
                    )

                # Persist ack durably, then ACK the client.
                self._ack_store.update(
                    msg.channel_id, msg.playout_session_id, msg.sequence
                )

                yield pb2.EvidenceAckFromCore(
                    channel_id=msg.channel_id,
                    playout_session_id=msg.playout_session_id,
                    acked_sequence=msg.sequence,
                )

        finally:
            if writer is not None:
                writer.close()
            logger.debug("EvidenceStream closed from %s", peer)

    def _process_evidence(
        self,
        writer: AsRunWriter,
        msg: pb2.EvidenceFromAir,
        payload_name: str,
        emitted_terminals: set[tuple[str, int]],
        last_segment_index: list[int],
        last_block_start_utc_ms: list[int | None],
        last_asset_end_frame_by_block: dict[str, int],
        join_in_progress_by_event: dict[str, bool],
        last_segment_uuid: list[str] | None = None,
    ) -> None:
        """Map a single evidence message to .asrun + .jsonl and write durably.

        Guards (AsRunLogArtifactContract v0.2):
        - AR-ART-008: No duplicate terminal events per EVENT_ID.
        - AR-ART-008: No zero-frame AIRED/TRUNCATED.
        - AR-ART-003: swap_tick == fence_tick (normalized if mismatched).
        """
        channel_id = msg.channel_id
        session_id = msg.playout_session_id

        if payload_name == "block_start":
            bs = msg.block_start
            last_block_start_utc_ms[0] = bs.actual_start_utc_ms
            actual = writer.display_time(bs.actual_start_utc_ms)
            notes = (
                f"(block open) swap_tick={bs.swap_tick} fence_tick={bs.fence_tick}"
            )
            asrun_line = _format_asrun_line(
                actual, "00:00:00", "START", "BLOCK", bs.block_id, notes
            )
            jsonl_rec = {
                "event_id": bs.block_id,
                "block_id": bs.block_id,
                "actual_start_utc": _epoch_ms_to_iso8601(bs.actual_start_utc_ms),
                "actual_start_utc_ms": bs.actual_start_utc_ms,
                "actual_duration_ms": 0,
                "status": "START",
                "reason": None,
                "swap_tick": bs.swap_tick,
                "fence_tick": bs.fence_tick,
            }
            writer.write_and_flush(asrun_line, jsonl_rec)

        elif payload_name == "segment_start":
            ss = msg.segment_start
            last_segment_index[0] = ss.segment_index
            # INV-AIR-SEGMENT-ID-001: Track segment_uuid for segment_end correlation
            last_segment_uuid[0] = ss.segment_uuid or ""
            if (
                ss.segment_index == 0
                and ss.asset_start_frame == 0
                and last_block_start_utc_ms[0] is not None
                and abs(ss.actual_start_utc_ms - last_block_start_utc_ms[0]) > 100
            ):
                logger.warning(
                    "SegmentStart asset_start_frame=0 but actual_start_utc_ms=%d "
                    "is not at block start %d (event_id=%s block_id=%s); "
                    "AIR may not have computed frame index",
                    ss.actual_start_utc_ms,
                    last_block_start_utc_ms[0],
                    ss.event_id or ss.block_id,
                    ss.block_id,
                )
            actual = writer.display_time(ss.actual_start_utc_ms)

            # INV-AIR-SEGMENT-ID-001/003: Use AIR-authoritative identity fields
            # from proto. Do NOT fall back to _lookup_segment_from_db for runtime
            # reporting. Segment metadata is carried in the evidence event itself.
            seg_type_name = ss.segment_type_name or ""
            seg_title = ss.segment_title or ""
            seg_asset_uri = ss.asset_uri or ""
            seg_uuid = ss.segment_uuid or ""
            seg_asset_uuid = ss.asset_uuid or ""

            # Derive title from asset_uri when title is empty
            if not seg_title and seg_asset_uri:
                import os as _os
                seg_title = _os.path.splitext(_os.path.basename(seg_asset_uri))[0]
            if not seg_title and seg_type_name == "pad":
                seg_title = "BLACK"

            # Map segment_type to human-readable as-run type label
            _type_labels = {
                "content": "PROGRAM",
                "episode": "PROGRAM",
                "commercial": "COMMERCL",
                "promo": "PROMO",
                "station_id": "IDENT",
                "stinger": "STINGER",
                "bumper": "BUMPER",
                "filler": "FILLER",
                "psa": "PSA",
                "pad": "PAD",
            }
            seg_type_label = _type_labels.get(seg_type_name, "PROGRAM")

            notes = f"segment_index={ss.segment_index} asset_start_frame={ss.asset_start_frame}"
            if seg_uuid:
                notes += f" segment_uuid={seg_uuid}"
            if seg_title:
                notes += f" [{seg_title}]"
            if ss.join_in_progress:
                notes += " join_in_progress=Y"
            asrun_line = _format_asrun_line(
                actual, "00:00:00", "SEG_START", seg_type_label,
                ss.event_id or ss.block_id, notes
            )
            jsonl_rec = {
                "event_id": ss.event_id or ss.block_id,
                "block_id": ss.block_id,
                "actual_start_utc": _epoch_ms_to_iso8601(ss.actual_start_utc_ms),
                "actual_start_utc_ms": ss.actual_start_utc_ms,
                "actual_duration_ms": 0,
                "status": "SEG_START",
                "segment_index": ss.segment_index,
                "asset_start_frame": ss.asset_start_frame,
                "scheduled_duration_ms": ss.scheduled_duration_ms,
                # INV-AIR-SEGMENT-ID-001/002: UUID-based identity
                "segment_uuid": seg_uuid,
                "asset_uuid": seg_asset_uuid,
                "segment_type": seg_type_name,
                "asset_uri": seg_asset_uri,
                "segment_title": seg_title,
            }
            if ss.join_in_progress:
                jsonl_rec["join_in_progress"] = True
                join_in_progress_by_event[ss.event_id or ss.block_id] = True
            writer.write_and_flush(asrun_line, jsonl_rec)

        elif payload_name == "segment_end":
            se = msg.segment_end
            event_id = se.event_id_ref or se.block_id
            status = se.status or "AIRED"
            frames = se.computed_duration_frames

            # AR-ART-008 + INV-AIR-SEGMENT-ID-001: Suppress duplicate terminal
            # event for same (EVENT_ID, segment_uuid). Using segment_uuid instead
            # of segment_index for identity-stable dedup across JIP renumbering.
            seg_uuid = ""
            if hasattr(se, "segment_uuid") and se.segment_uuid:
                seg_uuid = se.segment_uuid
            elif last_segment_uuid is not None:
                seg_uuid = last_segment_uuid[0]
            # INV-AIR-SEGMENT-ID-003/002: Extract identity fields from proto
            seg_type_name = getattr(se, "segment_type_name", "") or ""
            seg_asset_uuid = getattr(se, "asset_uuid", "") or ""
            dedup_key = (event_id, seg_uuid or last_segment_index[0])
            if dedup_key in emitted_terminals:
                logger.warning(
                    "AR-ART-008 guard: suppressing duplicate terminal %s "
                    "for EVENT_ID %s segment_index=%d",
                    status, event_id, last_segment_index[0],
                )
                return

            # AR-ART-008: Reject zero-frame AIRED/TRUNCATED.
            if status in ("AIRED", "TRUNCATED") and frames <= 0:
                logger.warning(
                    "AR-ART-008 guard: suppressing %s with frames=%d "
                    "for EVENT_ID %s (zero-frame terminal forbidden)",
                    status, frames, event_id,
                )
                return

            # Use end time for AIRED display so .asrun reads chronologically.
            # Previous: actual_start_utc_ms caused out-of-order timestamps
            # when segment_end arrived after the next segment_start.
            actual = writer.display_time(se.actual_end_utc_ms)
            dur = _ms_to_hhmmss(se.computed_duration_ms)
            seg_idx = last_segment_index[0]
            notes = (
                f"segment_index={seg_idx} "
                f"ontime=Y fallback={se.fallback_frames_used} "
                f"asset_start={se.asset_start_frame} asset_end={se.asset_end_frame} frames={frames}"
            )
            if seg_uuid:
                notes += f" segment_uuid={seg_uuid}"
            if se.reason:
                notes += f" reason={se.reason}"
            asrun_line = _format_asrun_line(
                actual, dur, status, "PROGRAM", event_id, notes
            )
            jsonl_rec = {
                "event_id": event_id,
                "block_id": se.block_id,
                "actual_start_utc": _epoch_ms_to_iso8601(se.actual_start_utc_ms),
                "actual_start_utc_ms": se.actual_start_utc_ms,
                "actual_end_utc_ms": se.actual_end_utc_ms,
                "actual_duration_ms": se.computed_duration_ms,
                "computed_duration_frames": frames,
                "asset_start_frame": se.asset_start_frame,
                "asset_end_frame": se.asset_end_frame,
                "status": status,
                "reason": se.reason or None,
                "fallback_frames_used": se.fallback_frames_used,
                # INV-AIR-SEGMENT-ID-001/002/003: UUID-based identity in evidence trail
                "segment_uuid": seg_uuid,
                "segment_type_name": seg_type_name,
                "asset_uuid": seg_asset_uuid,
            }
            # Contiguity invariant: within the SAME segment_index, consecutive
            # SEGMENT_END events should have contiguous asset frames. Across
            # segment boundaries each segment is a separate asset starting at
            # frame 0, so contiguity does not apply.
            prev_end = last_asset_end_frame_by_block.get(se.block_id)
            if (
                prev_end is not None
                and seg_idx == 0
                and status in ("AIRED", "TRUNCATED")
            ):
                jip = join_in_progress_by_event.pop(event_id, False)
                if not jip and prev_end + 1 != se.asset_start_frame:
                    logger.warning(
                        "Segment contiguity: prev_asset_end_frame(%d) + 1 != "
                        "asset_start_frame(%d) for event_id=%s block_id=%s",
                        prev_end, se.asset_start_frame, event_id, se.block_id,
                    )
            last_asset_end_frame_by_block[se.block_id] = se.asset_end_frame

            writer.write_and_flush(asrun_line, jsonl_rec)
            emitted_terminals.add(dedup_key)

        elif payload_name == "block_fence":
            bf = msg.block_fence
            actual = writer.display_time(bf.actual_end_utc_ms)

            # AR-ART-003 v0.2: swap_tick MUST equal fence_tick.
            # Normalize to fence_tick if mismatched (fence_tick is authoritative).
            swap_tick = bf.swap_tick
            fence_tick = bf.fence_tick
            if swap_tick != fence_tick:
                logger.warning(
                    "AR-ART-003 guard: swap_tick (%d) != fence_tick (%d) "
                    "for block %s; normalizing to fence_tick",
                    swap_tick, fence_tick, bf.block_id,
                )
                swap_tick = fence_tick

            tick_parts = []
            if swap_tick > 0:
                tick_parts.append(f"swap_tick={swap_tick}")
            if fence_tick > 0:
                tick_parts.append(f"fence_tick={fence_tick}")
            notes = (
                (" ".join(tick_parts) + " " if tick_parts else "")
                + f"frames_emitted={bf.total_frames_emitted} "
                f"frame_budget_remaining=0 "
                f"reason=FENCE "
                f"primed_success={'Y' if bf.primed_success else 'N'} "
                f"truncated_by_fence={'Y' if bf.truncated_by_fence else 'N'} "
                f"early_exhaustion={'Y' if bf.early_exhaustion else 'N'}"
            )
            fence_id = f"{bf.block_id}-FENCE"
            asrun_line = _format_asrun_line(
                actual, "00:00:00", "FENCE", "BLOCK", fence_id, notes
            )
            last_asset_end_frame_by_block.pop(bf.block_id, None)  # Prevent unbounded growth

            jsonl_rec = {
                "event_id": fence_id,
                "block_id": bf.block_id,
                "actual_start_utc": _epoch_ms_to_iso8601(bf.actual_end_utc_ms),
                "actual_end_utc_ms": bf.actual_end_utc_ms,
                "actual_duration_ms": 0,
                "status": "FENCE",
                "reason": None,
                "swap_tick": swap_tick,
                "fence_tick": fence_tick,
                "frames_emitted": bf.total_frames_emitted,
                "frame_budget_remaining": 0,
            }
            writer.write_and_flush(asrun_line, jsonl_rec)

        elif payload_name == "channel_terminated":
            ct = msg.channel_terminated
            actual = writer.display_time(ct.termination_utc_ms)
            notes = f"reason={ct.reason} detail={ct.detail}"
            asrun_line = _format_asrun_line(
                actual, "00:00:00", "TERMINATED", "CHANNEL", session_id, notes
            )
            jsonl_rec = {
                "event_id": session_id,
                "block_id": "",
                "actual_start_utc": _epoch_ms_to_iso8601(ct.termination_utc_ms),
                "termination_utc_ms": ct.termination_utc_ms,
                "actual_duration_ms": 0,
                "status": "TERMINATED",
                "reason": ct.reason,
                "swap_tick": None,
                "fence_tick": None,
            }
            writer.write_and_flush(asrun_line, jsonl_rec)


def serve(
    port: int = 50052,
    block: bool = True,
    ack_store: DurableAckStore | None = None,
    asrun_dir: str = DEFAULT_ASRUN_DIR,
) -> grpc.Server:
    """Start the evidence gRPC server on the given port."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    servicer = EvidenceServicer(ack_store=ack_store, asrun_dir=asrun_dir)
    pb2_grpc.add_ExecutionEvidenceServiceServicer_to_server(servicer, server)
    address = f"[::]:{port}"
    server.add_insecure_port(address)
    server.start()
    logger.info("Evidence gRPC server listening on %s", address)

    if block:
        server.wait_for_termination()

    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    serve()
