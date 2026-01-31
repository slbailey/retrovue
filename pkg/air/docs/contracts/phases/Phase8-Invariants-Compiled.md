# Phase 8 Invariants — Compiled Reference

Compiled from: Core `ScheduleManagerPhase8Contract.md`, AIR `Phase8-3-PreviewSwitchToLive.md`, and code comments. For full statements see source docs.

## 1. Timeline (Core — ScheduleManagerPhase8Contract)

| ID | Name |
|----|------|
| INV-P8-001 | Single Timeline Writer — only Timeline Controller assigns CT |
| INV-P8-002 | Monotonic Advancement — CT strictly increasing |
| INV-P8-003 | Contiguous Coverage — no CT gaps |
| INV-P8-004 | Wall-Clock Correspondence — W = epoch + CT steady-state |
| INV-P8-005 | Epoch Immutability — epoch unchanged until session end |
| INV-P8-006 | Producer Time Blindness — producers do not read/compute CT |
| INV-P8-007 | Write Barrier Finality — post-barrier writes = 0 |
| INV-P8-008 | Frame Provenance — one producer, one MT, one CT per frame |
| INV-P8-009 | Atomic Buffer Authority — one active buffer, instant switch |
| INV-P8-010 | No Cross-Producer Dependency — new CT from TC state only |
| INV-P8-011 | Backpressure Isolation — consumer slowness does not slow CT |
| INV-P8-012 | Deterministic Replay — same inputs → same CT sequence |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness — explicit flush, bounded delivery |

## 2. Behavioral (Core §15.3a)

| ID | Name |
|----|------|
| INV-P8-TIME-BLINDNESS | When TC active and not shadow: producer must not drop on MT vs target, delay for alignment, gate audio on video PTS; all admission via TimelineController |

## 3. Segment mapping / switch (AIR — Phase8-3)

| ID | Name |
|----|------|
| INV-P8-SWITCH-001 | Mapping must be pending BEFORE preview fills; BeginSegment before disable shadow; write barrier on live before new segment |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both (type-safe API) |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode |
| INV-P8-AUDIO-GATE | Audio gated only while shadow (and in code: while mapping pending) |
| INV-P8-SEGMENT-COMMIT | First frame admitted → segment commits, owns CT; old segment ForceStop |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection |

## 4. Code-referenced (AIR / Core)

| ID | Name |
|----|------|
| INV-P8-SWITCH-ARMED | No LoadPreview while switch armed; FATAL if reset code reached while armed |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live MUST wait until preview shadow decode ready; prevents timeline starvation deadlock |
| INV-P8-EOF-SWITCH | Live producer EOF → switch completes immediately (do not block on buffer depth) |
| INV-P8-PREVIEW-EOF | Preview EOF with frames → complete with lower thresholds (e.g. ≥1 video, ≥1 audio) |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately |
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: drop frame, log INV-P8-WRITE-BARRIER |
| INV-P8-AUDIO-GATE Fix #2 | mapping_locked_this_iteration_ so audio same iteration ungate after video locks |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) |
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written |
| INV-P8-AUDIO-PRIME-STALL | Diagnostic: log if video dropped too long waiting for audio prime |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS path |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame |
| P8-IO-001 | Forward progress: output timing off during prebuffer, flush_packets=1, periodic flush, skip gating during prebuffer |
| INV-P8-SWITCH-TIMING | Core: switch at boundary; log if pending after boundary; violation log if complete after boundary |

## 5. Source locations

- **Core:** `pkg/core/docs/contracts/runtime/ScheduleManagerPhase8Contract.md` (§8, §14–15, Appendix A)
- **AIR 8.3:** `pkg/air/docs/contracts/phases/Phase8-3-PreviewSwitchToLive.md`
- **Code:** PlayoutEngine.cpp, FileProducer.cpp, TimelineController.cpp, EncoderPipeline.cpp, MpegTSOutputSink.cpp, channel_manager.py

Canonical contract documents take precedence over this compiled list.
