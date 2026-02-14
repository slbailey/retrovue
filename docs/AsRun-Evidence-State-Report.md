# As-Run / Evidence State Report (Repo-Grounded)

**Generated:** 2026-02-14. No speculation; citations to repo paths and symbols only.

---

## 1) Contracts that mention as-run / evidence

| Path | Section / intent | Quote (≤2 lines) | Interpretation |
|------|------------------|------------------|----------------|
| `pkg/air/docs/contracts/INVARIANTS-INDEX.md` | Observability Parity; As-Run Timeline Invariants | "Intent, correlation, result, timing, and boundary evidence (LAW-OBS-001 through LAW-OBS-005)." / "Persistent as-run log for auditable channel execution record." | LAW-OBS defines observability; INV-ASRUN-TIMELINE-001..007 assign AsRunWriter responsibility for block START/FENCE/segment lifecycle, append-only, fence notes. |
| `pkg/air/docs/contracts/AsRunTimelineContract_v0.1.md` | Purpose; Owner | "The AsRunWriter produces a deterministic, auditable as-run log file per channel per broadcast date, derived solely from playout timeline events." | Requires AIR's AsRunWriter to own timeline-derived as-run file; output conforms to AsRunLogArtifactContract v0.2. |
| `pkg/air/docs/contracts/AirExecutionEvidenceEmitterContract_v0.1.md` | Purpose; Emission Authority | "This contract is *authoritative* for how the AIR subsystem emits execution evidence during channel playout." / "Evidence emission is restricted to specific AIR runtime transitions … No other component may emit evidence events." | AIR is sole emitter of BLOCK_START, SEGMENT_START, SEGMENT_END, BLOCK_FENCE, CHANNEL_TERMINATED at defined lifecycle moments. |
| `docs/contracts/core/ExecutionEvidenceToAsRunMappingContract_v0.1.md` | Purpose; Boundary | "Transformation of execution evidence emitted by AIR into persisted As-Run log artifacts." / "AIR MUST NOT write `.asrun` files directly. … All As-Run entries MUST originate from explicit execution evidence emitted by AIR." | Core (ChannelManager) maps evidence → .asrun/.asrun.jsonl; AIR must not write .asrun; no inference. |
| `docs/contracts/coordination/AirExecutionEvidenceInterfaceContract_v0.1.md` | Purpose | "Wire-level interface by which AIR emits *authoritative execution evidence* to Core runtime (ChannelManager). ChannelManager persists As-Run artifacts from explicit evidence (no inference)." | Wire shape and separation: evidence stream dedicated, machine-parseable, ordered; Core persists from evidence only. |
| `docs/contracts/coordination/ExecutionEvidenceGrpcInterfaceContract_v0.1.md` | Purpose; Transport | "Authoritative gRPC streaming interface between AIR and Core for transmission of execution evidence." | Defines EvidenceStream(stream EvidenceFromAir) returns (stream EvidenceAckFromCore); ordering, sequence, idempotency, resume/ACK. |
| `docs/contracts/artifacts/AsRunLogArtifactContract.md` | Purpose; Storage | "As-Run Log is the authoritative, persisted record of what actually occurred during playout." / Storage: `/opt/retrovue/data/logs/asrun/{channel_id}/{YYYY-MM-DD}.asrun` and `.asrun.jsonl`. | File format (fixed-width .asrun + JSONL sidecar), header, columns, midnight handling. |
| `docs/ArchitecturalRoadmap.md` | As-Run Reconciliation; As-Run Log Integration | "AsRunLogger exists. As-run reconciliation: … reconciler; optional integration not yet wired." / "AsRunLogger … logs actual block/segment times." | Documents AsRunLogger and reconciler; integration (e.g. AsRunLogger exporting AsRunLog) optional, not wired. |
| `docs/contracts/PHASE1_TASKS.md`, `PHASE1_EXECUTION_PLAN.md` | Audit | "Formal audit (2026-02-01) identified broadcast-grade timing violations … Phase 11." | Audit mention only; no as-run/evidence API. |
| `pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md` | Purpose; Storage | "AIR _never loses execution evidence_ … Core always controls ACK … AIR never loses any evidence." / Spool: `/opt/retrovue/data/logs/evidence_spool/{channel_id}/{playout_session_id}.spool.jsonl`. | AIR persists evidence locally until Core ACK; replay/resume deterministic and idempotent. |

---

## 2) Tests that cover as-run / evidence

| Path | Test names (representative) | Assertions | Suite |
|------|-----------------------------|------------|-------|
| `pkg/air/tests/contracts/BlockPlan/AsRunWriterContractTests.cpp` | ASRUN_001 BlockStartDedup, ASRUN_002 FenceDedup, ASRUN_003 SegStartPrecedesTerminal, ASRUN_004 FrameRefsBlockRelative, ASRUN_005 AppendOnlyFlush, ASRUN_006 FenceNotesComplete, ASRUN_007 FixedWidthFormat, ASRUN_008 JsonlSidecar, ASRUN_009 MidnightRollover, ASRUN_010 MultiBlockSequence, ASRUN_011 RestartMidBlockNoCorruption, ASRUN_012 FenceWithoutSegmentStart, ASRUN_013 ProofArrivesAfterFenceIgnored | START/FENCE once per key; segment lifecycle; block-relative frames; flush count; fence notes; fixed-width; .air.asrun + .air.asrun.jsonl; midnight rollover; multi-block; restart; pad-only block; proof after fence ignored | **Air** |
| `pkg/air/tests/test_evidence_spool.cpp` | AppendAndReplayFrom, AckPersistence, CorruptTailIgnored, SequenceGapThrows, JsonRoundTrip, DiskCapEnforced, UnlimitedCapAllowsAll | Spool append/replay, ACK file, corruption handling, sequence monotonicity, JSON round-trip, disk cap | **Air** |
| `pkg/core/tests/contracts/test_execution_evidence_to_asrun_mapping_contract_v0_1.py` | test_map_evidence_to_asrun_matches_golden, test_map_truncated_segment_produces_truncated_entry | Synthetic evidence → .asrun/.asrun.jsonl lines match golden; TRUNCATED/FENCE_TERMINATION mapping | **Core** |
| `pkg/core/tests/contracts/test_asrun_log_artifact_contract_v0_1.py` | test_ar_art_007_bijection_asrun_to_jsonl, test_ar_art_007_bijection_jsonl_to_asrun, header/body parsing | Bijection .asrun ↔ .asrun.jsonl; header required | **Core** |
| `pkg/core/tests/contracts/artifacts/test_asrun_log_artifact_contract.py` | AR-ART-008 (zero frames), SEG_START/terminal, AR-ART-003 (swap_tick/fence_tick/frame_budget), AR-ART-004 (no scheduled_* in .asrun), FENCE zeros, AIRED segment_index, minutes/seconds range | Validator raises AsRunArtifactError for invalid rows/format | **Core** |
| `pkg/core/tests/contracts/test_asrun_reconciliation_contract.py` | INV-ASRUN-001..005 style tests via _transmission_log_to_asrun_log + reconcile_transmission_log | Plan vs actual comparison (TransmissionLog → AsRunLog), reconciler contract | **Core** |
| `pkg/core/tests/test_grpc_failure_scenarios.py` | EvidenceStream with duplicate event_id, replay, resume | EvidenceServicer; .asrun.jsonl content and no duplicate event_ids | **Core** |
| `pkg/core/tests/test_grpc_replay_resume.py` | EvidenceStream phase1/phase2, resume from ACK | Evidence written to .asrun + .asrun.jsonl before ACK; resume from acked sequence | **Core** |
| `pkg/core/tests/test_grpc_evidence_basic.py` | EvidenceStream request_iterator | Basic EvidenceStream RPC and ACKs | **Core** |
| `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` | BlockCompletedCallbackFires | BlockCompleted callback fires (continuous output contract) | **Air** |

---

## 3) Current writers / emitters (Core)

| Path : symbol | Writes | Destination | Authoritative vs debug |
|--------------|--------|--------------|-------------------------|
| `pkg/core/src/retrovue/runtime/evidence_server.py` : `EvidenceServicer.EvidenceStream` → `_process_evidence` | Maps gRPC `EvidenceFromAir` to fixed-width line + JSONL record | Via `AsRunWriter.write_and_flush`: `{asrun_dir}/{channel_id}/{YYYY-MM-DD}.asrun` and `.asrun.jsonl` (default asrun_dir `/opt/retrovue/data/logs/asrun`) | **Authoritative**: contract-driven (ExecutionEvidenceToAsRunMappingContract, AsRunLogArtifactContract); fsync after each write. |
| `pkg/core/src/retrovue/runtime/evidence_server.py` : `AsRunWriter.write_and_flush` | Single .asrun line + one JSONL record | Same file handles (append), then `flush()` and `os.fsync()`. | **Authoritative**: sole Core writer of .asrun from evidence. |
| `pkg/core/src/retrovue/runtime/asrun_logger.py` : `AsRunLogger.log_playout_start` / `log_playout_end` | `AsRunEvent` appended to `self.events` (in-memory list) | No file or DB write; only `self.events.append(event)`. | **Not authoritative for persistence**: in-memory only; no caller in playout path (ChannelManager comments say "future AsRunLogger integration"). |

**DB writes:** NOT FOUND. No SQLAlchemy/ORM/repo pattern writes as-run or playlog to a DB table in the searched codebase. No as_run/asrun entity in `entities` or equivalent.

---

## 4) Current writers / emitters (Air)

| Path : symbol | Writes | Destination | Authoritative vs debug |
|--------------|--------|--------------|-------------------------|
| `pkg/air/src/blockplan/AsRunWriter.cpp` : `OnBlockStarted`, `OnSegmentStart`, `OnPlaybackProof`, `OnBlockCompleted`, `WriteTextLine`, `WriteJsonLine` | Fixed-width .asrun lines and JSONL lines per AsRunLogArtifactContract | `{base_dir}/{channel_id}/{broadcast_date}.air.asrun` and `.air.asrun.jsonl` (base_dir default `/opt/retrovue/data/logs/asrun`) | **Authoritative**: timeline-derived; INV-ASRUN-TIMELINE-001..007; comment states "C++ writer is timeline-authoritative". |
| `pkg/air/src/evidence/EvidenceSpool.cpp` : `EvidenceSpool::Append` / `WriterLoop` | `EvidenceFromAir` as JSONL lines | `{spool_root}/{channel_id}/{playout_session_id}.spool.jsonl` (spool_root default `/opt/retrovue/data/logs/evidence_spool`) | **Authoritative**: durability until Core ACK; contract AirExecutionEvidenceSpoolContract_v0.1. |
| `pkg/air/src/evidence/EvidenceEmitter.cpp` : `EmitBlockStart`, `EmitSegmentStart`, `EmitSegmentEnd`, `EmitBlockFence`, `EmitChannelTerminated` | Builds `EvidenceFromAir` and calls `spool_->Append(msg)`; if client set, client sends to Core | Spool (above); gRPC to Core when `GrpcEvidenceClient` is used (see playout_service.cpp) | **Authoritative**: sole AIR emission path per AirExecutionEvidenceEmitterContract. |
| `pkg/air/src/evidence/GrpcEvidenceClient.cpp` : `Send`, `ConnectionLoop`, `RunOneSession` | Serializes to protobuf and streams to Core | gRPC `EvidenceStream` to Core evidence server (host:port from `evidence_endpoint`) | **Authoritative**: wire transport of evidence; Core persists to .asrun. |

---

## 5) gRPC APIs for execution evidence

| Proto path | Service / RPCs / messages | Key fields |
|------------|---------------------------|------------|
| `protos/execution_evidence_v1.proto` | **Service:** `ExecutionEvidenceService`. **RPC:** `EvidenceStream(stream EvidenceFromAir) returns (stream EvidenceAckFromCore)`. **Messages:** `EvidenceFromAir` (schema_version, channel_id, playout_session_id, sequence, event_uuid, emitted_utc, oneof payload: Hello, BlockStart, SegmentStart, SegmentEnd, BlockFence, ChannelTerminated); `EvidenceAckFromCore` (channel_id, playout_session_id, acked_sequence, error); `Hello`, `BlockStart`, `SegmentStart`, `SegmentEnd`, `BlockFence`, `ChannelTerminated` with actual_*_utc_ms, frames, status, etc. | Single RPC for evidence; bidirectional stream; payload types align with mapping contract. |
| `protos/playout.proto` | **Service:** `PlayoutControl` (lifecycle/BlockPlan). **Relevance:** `StartBlockPlanSessionRequest` has `string evidence_endpoint = 20` (host:port for evidence gRPC, empty = disabled) and `channel_id_str = 21` for evidence/as-run. No evidence RPCs in playout.proto. | Evidence *usage* only: Core passes evidence_endpoint when starting BlockPlan; AIR connects to Core's evidence gRPC server. |

**Server implementation:** `pkg/core/src/retrovue/runtime/evidence_server.py` — `EvidenceServicer` (implements `ExecutionEvidenceServiceServicer`), `EvidenceStream`; registered via `pb2_grpc.add_ExecutionEvidenceServiceServicer_to_server`.  
**Client implementation:** `pkg/air/src/evidence/GrpcEvidenceClient.cpp` — connects to `evidence_endpoint`, runs `EvidenceStream` (send EvidenceFromAir, read EvidenceAckFromCore).  
**Python stubs:** `pkg/core/core/proto/retrovue/execution_evidence_v1_pb2*.py` (and `pkg/core/core/proto/execution_evidence_v1_pb2_grpc.py`).

---

## 6) Findings (no speculation)

- **Core does write as-run today:** Only via the evidence gRPC path. `EvidenceServicer.EvidenceStream` → `_process_evidence` → `AsRunWriter.write_and_flush` writes to `{asrun_dir}/{channel_id}/{YYYY-MM-DD}.asrun` and `.asrun.jsonl`. No DB. Core’s `AsRunLogger` only appends to an in-memory list and is not wired into the playout path.
- **Air writes as-run today in two ways:**  
  1) **Local timeline file:** `blockplan::AsRunWriter` writes `{channel_id}/{date}.air.asrun` and `.air.asrun.jsonl` under `/opt/retrovue/data/logs/asrun`.  
  2) **Evidence to Core:** `EvidenceEmitter` + `EvidenceSpool` (local `.spool.jsonl`) + `GrpcEvidenceClient` send evidence to Core; Core then writes `{channel_id}/{date}.asrun` and `.asrun.jsonl` (no `.air.` prefix).
- **Two different as-run file sets:**  
  - **AIR-only:** `…/asrun/{channel_id}/{YYYY-MM-DD}.air.asrun` (+ .jsonl) — written by C++ AsRunWriter from timeline.  
  - **Core from evidence:** `…/asrun/{channel_id}/{YYYY-MM-DD}.asrun` (+ .jsonl) — written by Python EvidenceServicer from gRPC evidence. Same directory, different filenames to avoid collision (see AsRunWriter.cpp comment).
- **Duplication:** Same logical events are (1) written by AIR to `.air.asrun` and (2) emitted over gRPC and written by Core to `.asrun`. Content can differ in format/fields (e.g. AIR has timeline proof details; Core mapping follows ExecutionEvidenceToAsRunMappingContract).
- **Evidence path is optional:** Evidence pipeline (spool + gRPC client) is created only when `StartBlockPlanSessionRequest.evidence_endpoint()` is non-empty. AsRunWriter (`.air.asrun`) is always created when BlockPlan session runs.
- **No DB schema for as-run:** No as_run / playlog / execution table found in Core entities or migrations.

---

## Validation

**Commands / searches run:**

- `rg -i "asrun|as-run|as_run|evidence|execution log|playlog|BlockCompleted|ExecutionEvidence|audit|telemetry|observability parity|LAW-OBS|as-run log" --glob '*.md'` (repo root)
- `rg -i "AsRun|Asrun|evidence|ExecutionEvidence|playlog|PlayLog|Audit|Evidence"` in `*Test*` paths
- `rg "asrun|as_run|AsRun|playlog|evidence|ExecutionEvidence"` in `pkg/core` and `pkg/air`
- `rg "\.asrun|\.air\.asrun|write.*asrun|asrun.*write"` in `*.py`, `*.cpp`, `*.hpp`
- `rg "AsRunLogger|asrun_logger|log_playout_start|log_playout_end"` in `pkg/core` `*.py`
- `rg "EvidenceEmitter|EvidenceSpool|GrpcEvidenceClient|Append"` in `pkg/air/src/evidence`
- `rg "evidence_endpoint|evidence_spool|EvidenceSpool\("` in `pkg/air/src/playout_service.cpp`
- `rg "AsRunLog|as_run|asrun"` in `pkg/core` `*entities*`
- Read: `protos/execution_evidence_v1.proto`, `protos/playout.proto` (excerpts), `evidence_server.py`, `AsRunWriter.cpp`, `asrun_logger.py`, contract docs listed in §1.

**Limitations:**

- No DB schema/migration files were exhaustively listed; “NOT FOUND” applies to the entities and code paths searched.
- AsRunLogger is not invoked from ChannelManager/playout path; only comments and docs reference “future AsRunLogger integration.”
