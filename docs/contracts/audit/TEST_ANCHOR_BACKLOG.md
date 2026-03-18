# Test Anchor Backlog

**Produced by:** Canonicalization subagent (Phase G)
**Date:** 2025-07-14
**Source:** Canonicalization audit (see CANONICALIZATION_HISTORY.md)
**Note:** This file documents test gaps only. No tests are written or modified here. This is a planning artifact.

---

## P1 — Missing Harness Blockers

These tests cannot be written until the listed infrastructure work is completed.

### P1-01: Log Capture Harness (Blocks LAW-OBS-001 through LAW-OBS-005)

**Rule(s):** LAW-OBS-001, LAW-OBS-002, LAW-OBS-003, LAW-OBS-004, LAW-OBS-005 (all five observability laws)

**Blocked tests (all 10 entries in CONTRACT_TEST_LOG_MATRIX.md §5):**
- AIR-STARTCHANNEL-RECEIVED event (and required fields)
- AIR-LOADPREVIEW-ACCEPTED / AIR-LOADPREVIEW-REJECTED events
- AIR-SWITCH-COMMITTED / AIR-SWITCH-FAILED events
- AIR-CHANNEL-STOPPED event
- Correlation ID propagation across all events

**Harness work required (implementation, not doc):**
1. `Logger::SetErrorSink`-style callback for log capture in test context (C++).
2. Correlation ID injection in test gRPC calls.
3. Log line parser for structured event format.

**Status:** All 10 observability test entries are MISSING in CONTRACT_TEST_LOG_MATRIX.md.

---

### P1-02: LAW-002 Skipped Test

**Rule:** LAW-002 (Hard Stop Authoritative)

**Test:** `Phase6A2_HardStopEnforced` — currently SKIPPED per Phase 8.6.

**RESOLVED:** LAW-002 rewritten under BlockPlan semantics. `pkg/air/tests/contracts/BlockPlan/Law002HardStopContractTests.cpp` is canonical enforcement. Legacy Phase6A2 test RETIRED.

---

## P2 — Existing Contract but Missing Explicit Tests

These contracts are canonically located but the specific test assertions do not exist.

| Test ID (proposed) | Rule | Contract | Gap |
|--------------------|------|----------|-----|
| `test_shadow_decode_started_field` | OBS-001 / AIR-005 | PlayoutEngineContract | `shadow_decode_started` field asserted only partially; SHOULD not MUST |
| `test_pts_contiguous_field` | OBS-001 / AIR-005 | PlayoutEngineContract | `pts_contiguous` field not asserted |
| `test_stop_channel_no_orphan_processes` | AIR-007 | PlayoutEngineContract | Orphan ffmpeg processes after StopChannel — not tested |
| `test_core_prefeed_before_boundary` | AIR-010 | ScheduleManagerContract | Prefeed issued before segment boundary — no explicit test |
| `test_channel_manager_segment_immutability` | CORE-002 | ChannelManagerContract | Segment immutability — no test |
| `test_channel_manager_prefeed_deadline` | CORE-003 | ChannelManagerContract | Prefeed deadline — no test |
| `test_channel_manager_switch_at_boundary` | CORE-003 | ChannelManagerContract | Switch at boundary — no test |
| `test_channel_manager_no_duplicate_loadpreview` | CORE-003 | ChannelManagerContract | No duplicate prefeed — no test |

---

## P3 — Needs New Test Matrix

These rules exist in contract files but have no test matrix document at all.

### P3-01: Sink Contracts Test Matrix

**Create:** `TEST-MATRIX-SINK-CONTRACTS.md`

**Must cover:**
- `INV-PCR-PACED-MUX` — PCR pacing within [20, 100] ms range
- `INV-SINK-NO-DEADLOCK` — Sink never deadlocks under backpressure
- `INV-TS-EMISSION-LIVENESS` — TS emission continues without gaps
- `AIR-012` — Sink lifecycle: start/stop idempotent; packet format; H.264 validity
- `AIR-015` — Late frames counted; backpressure graceful; disconnect handled; fault state persisted

---

### P3-02: Shared Contracts Test Matrix

**Create:** `TEST-MATRIX-SHARED-CONTRACTS.md`

**Must cover:**
- `INV-AUDIO-CONTINUITY-NO-DROP` — Audio frames not dropped during content switches
- `INV-CONTENT-DEFICIT-FILL` — Content deficit filled with deterministic pad (black + silence)
- `INV-LOUDNESS-NORMALIZED-001` — Loudness normalization applied
- `INV-TIME-AUTHORITY-SINGLE-SOURCE` — All time queries flow through MasterClock (no datetime.now() / time.time() calls)

---

### P3-03: Cadence Source Sync Test Matrix

**Create:** `TEST-MATRIX-AIR-CADENCE-SYNC.md` (or add section to TEST-MATRIX-AIR-MEDIA-TIME.md)

**Must cover:**
- `INV-CADENCE-SOURCE-SYNC-001` — Cadence source locked before first frame
- `INV-CADENCE-SOURCE-SYNC-002` — Cadence source does not change mid-block
- `INV-CADENCE-SOURCE-SYNC-003` — Cadence source restored after seam swap
- `INV-CADENCE-SOURCE-SYNC-004` — Cadence source mismatch triggers recovery, not crash

---

### P3-04: Expand TEST-MATRIX-AIR-FRAME-AUTHORITY.md

**Add entries for:**
- `INV-SEAM-BOUNDARY-COUNT-MATCH-001`
- `INV-PRODUCER-DEMAND-DRIVEN-001`
- `INV-SEAM-CONTINUITY-GUARANTEED-001`
- `INV-SEAM-TAKEOVER-COMMITMENT-001`
- `INV-TIME-MODE-EQUIVALENCE-001`

---

### P3-05: LAW-007 Drift Test

**Rule:** LAW-007 (No Drift Over Time)

**Required infrastructure:** E2E harness with `FakeAdvancingClock.advance_ms()` that can simulate N × 30-minute boundaries without wall-clock delay.

**Test concept:** After N boundaries (e.g., 48 × 30-min = 24h equivalent), assert that playout PTS has not drifted from MasterClock by more than the defined tolerance.

**Status:** No harness mechanism exists. This is a P3 gap, not P1, because a fast-clock simulation harness could be implemented without a full soak infrastructure.

---

## P4 — Weak Wording Before Testing

Rules where the contract text is too weak (SHOULD vs MUST) or too vague to write a passing test without first tightening the wording.

| Rule | Problem | Wording Fix Required First |
|------|---------|---------------------------|
| OBS-001 / AIR-005 | `shadow_decode_started` and `pts_contiguous` are SHOULD | Change to MUST in PlayoutEngineContract.md; then test |
| AIR-011 | "MUST NOT inspect MPEG-TS bytes" with no enforcement path | Either add CI lint/grep (non-doc work), or convert to SHOULD and add a doc-only rationale note |
| INV-SWITCH-BOUNDARY-TIMING | No Derived From law; enforcement mechanism unclear | Add derivation from LAW-SWITCHING, or deprecate. Then test |
| CORE-004 | "Mock SchedulePlan MUST" — test fixture vs production scope unclear | Scope clarification first (see CORE-004 placeholder). Then test accordingly |
| LAW-OBS-001–005 | Laws well-defined but Part 2.5 event names and fields are in a different doc | Consolidate event names + fields into the laws themselves, or add explicit cross-reference anchors. Then test (after P1 harness) |
| INV-PACING-001 | "ProgramOutput MUST emit frames at the display clock rate" — display clock rate not defined numerically | Define tolerance bounds; then test |
| INV-PACING-ENFORCEMENT-002 | Similar — enforcement mechanism not specified | Tighten; then test |
| INV-DECODE-RATE-001 | "FileProducer MUST decode at clock rate" — no numeric bound | Define tolerance; then test |
| INV-SEGMENT-CONTENT-001 | "Segment content MUST match the PlayoutSegment spec" — too abstract | Enumerate specific checks; then test |

---

## Summary

| Priority | Count | Infrastructure Needed | Human Decision Needed |
|----------|-------|----------------------|----------------------|
| P1 (blockers) | 2 groups | Log capture harness (C++) | CON-04 (LAW-002 test) |
| P2 (missing tests) | 8 tests | None | None |
| P3 (new matrices) | 5 matrices | FakeAdvancingClock for LAW-007 | None |
| P4 (wording first) | 9 rules | None | CON-01, CON-02 affect some |
