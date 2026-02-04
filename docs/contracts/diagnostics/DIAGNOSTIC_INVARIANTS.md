# Layer 3 - Diagnostic Invariants

**Status:** Canonical
**Scope:** Logging requirements, violation classification, enforcement rails
**Authority:** Observability requirements that do not override runtime behavior

---

## Layer 3 Doctrine (Constitutional Guard)

> **Layer 3 may never introduce "allowed" behavior that Layer 0/1 forbids. It may only classify, measure, and surface violations.**

This is the constitutional constraint on all diagnostic invariants. If a lower layer forbids an action (e.g., "no drops"), Layer 3 cannot legalize that action by calling it a "policy." Layer 3 exists to observe and report, not to grant exceptions.

---

## Diagnostic Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P8-WRITE-BARRIER-DIAG** | CONTRACT | FileProducer | P8 | No | Yes |
| **INV-P9-AUDIO-GATE-VIOLATION** | CONTRACT | MpegTSOutputSink | P9 | No | Yes |
| **INV-P10-FRAME-DROP-FORBIDDEN** | CONTRACT | ProgramOutput | P10 | No | Yes |
| **INV-P10-PAD-REASON** | CONTRACT | ProgramOutput | P10 | No | Yes |
| **INV-NO-PAD-WHILE-DEPTH-HIGH** | CONTRACT | ProgramOutput | P10 | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: discard frame (intentional barrier enforcement), log with reason=WRITE_BARRIER_ACTIVE |
| INV-P9-AUDIO-GATE-VIOLATION | Log if video output is blocked/delayed/drops frames due to waiting for real audio after TS header write; this is a Phase 9 violation |
| INV-P10-FRAME-DROP-FORBIDDEN | Frame drops are violations (not recovery); must classify and log violation category |
| INV-P10-PAD-REASON | Every pad frame classified by root cause (BUFFER_TRULY_EMPTY, etc.) |
| INV-NO-PAD-WHILE-DEPTH-HIGH | Pad emission with depth >= 10 is a violation; must log |

---

## Detailed Definitions

### INV-P8-WRITE-BARRIER-DIAG

**When `writes_disabled_` is set on a producer, frame discards must be logged as intentional barrier enforcement.**

**Terminology:** This is a "discard" not a "drop." Barrier enforcement discard is intentional and correct — it prevents writes to a segment after commit. This is NOT a "frame drop incident" and must not be counted as such.

Log format:
```
[FileProducer] INV-P8-WRITE-BARRIER: Frame discarded, reason=WRITE_BARRIER_ACTIVE, segment_id=N
```

This diagnostic helps trace:
- Write barrier timing relative to switch
- Frames discarded between barrier and segment closure
- Potential race conditions in barrier application

**Counter (separate from drop violations):**
- `retrovue_barrier_discards_total` (intentional, not violations)

---

### INV-P9-AUDIO-GATE-VIOLATION

**Log if video output is blocked, delayed, or drops frames due to waiting for real audio after TS header write.**

This is a Phase 9 violation. Phase 9 mandates:
- INV-P9-BOOT-LIVENESS: Decodable TS emits even if audio not yet available
- INV-P9-AUDIO-LIVENESS: Inject silence so video is not delayed/gated waiting for audio
- INV-P9-PCR-AUDIO-MASTER: Injected silence is authoritative if real audio isn't ready

**Trigger conditions (any of these after TS header written):**
- `injecting_silence=false` AND output loop stalls because `real_audio_ready=false`
- Video frames discarded/dropped while waiting for audio when silence injection should be active
- Header write deferred waiting for real audio (violates INV-P9-BOOT-LIVENESS)

**Required log payload:**
```
[MpegTSOutputSink] INV-P9-AUDIO-GATE-VIOLATION:
  ts_header_written=<true|false>,
  injecting_silence=<true|false>,
  real_audio_ready=<true|false>,
  blocked_ms=<N>,
  video_depth=<N>,
  audio_depth=<N>,
  reason=<gated_on_audio|header_deferred|pcr_not_initialized|unknown>
```

**Threshold:** Any blocking > 0ms after header write is a violation. Log immediately.

---

### INV-P10-FRAME-DROP-FORBIDDEN

**Frame drops are violations, not approved recovery mechanisms.**

Per INV-PACING-ENFORCEMENT-002: "No-drop, freeze-then-pad." Drops are never an approved recovery path. If drops occur, they indicate a violation that must be classified and logged.

**Constitutional constraint:** The approved recovery for timing issues is freeze-then-pad, never drop. This diagnostic classifies violations for debugging, not to legitimize drops.

**Violation categories (for classification, not approval):**
- `BUFFER_OVERFLOW_VIOLATION` — Buffer full, consumer behind (should have throttled producer)
- `SEEK_DISCONTINUITY` — Explicit seek/discontinuity (frames from old position, not a bug)
- `SWITCH_BARRIER_DISCARD` — Write barrier active during switch (see INV-P8-WRITE-BARRIER-DIAG)
- `SYSTEM_OVERLOAD_VIOLATION` — CPU starvation (indicates capacity planning failure)

**When drops occur, MUST log as violation:**
```
INV-P10-FRAME-DROP-FORBIDDEN VIOLATION: category=<category>, dropped=<count>, buffer_depth=<n>
```

**Counters:**
- `retrovue_frames_dropped_total` (by violation category)

---

### INV-P10-PAD-REASON

**Every pad frame emitted by ProgramOutput must be classified by root cause.**

| PadReason | Meaning |
|-----------|---------|
| BUFFER_TRULY_EMPTY | Buffer depth is 0, producer is starved |
| PRODUCER_GATED | Producer is blocked at flow control gate |
| CT_SLOT_SKIPPED | Frame exists but CT is in the future |
| FRAME_CT_MISMATCH | Frame CT doesn't match expected output CT |
| CONTENT_DEFICIT_FILL | EOF-to-boundary fill (normal, not a violation) |
| UNKNOWN | Fallback for unclassified cases |

**Logging policy:** Logging MUST be aggregated or rate-limited; per-frame logs are forbidden in steady-state. Log "first occurrence" per reason per segment, then aggregate counts.

**Log format (rate-limited, not per-frame):**
```
[ProgramOutput] INV-P10-PAD-REASON: pad_count=N, reason=<PadReason>, segment_id=M, duration_ms=X
```

**First-occurrence log (once per reason per segment):**
```
[ProgramOutput] INV-P10-PAD-REASON: First pad, reason=<PadReason>, expected_ct=X, buffer_depth=N
```

**Counters (always tracked, even when logs suppressed):**
- `pads_buffer_empty_` - Pads emitted due to BUFFER_TRULY_EMPTY
- `pads_producer_gated_` - Pads emitted due to PRODUCER_GATED
- `pads_ct_skipped_` - Pads emitted due to CT_SLOT_SKIPPED
- `pads_ct_mismatch_` - Pads emitted due to FRAME_CT_MISMATCH
- `pads_content_deficit_` - Pads emitted due to CONTENT_DEFICIT_FILL (normal EOF fill)

---

### INV-NO-PAD-WHILE-DEPTH-HIGH

**Pad emission is a violation if buffer depth >= 10.**

If a pad frame is emitted while video buffer depth is >= 10 frames, this indicates a bug in flow control or CT tracking logic - the buffer has frames but they're not being consumed.

**Required log fields (for actionable debugging):**
- `expected_ct` — The CT slot being filled with pad
- `next_frame_ct` — The CT of the next available frame in buffer
- `pad_reason` — Classification from INV-P10-PAD-REASON
- `buffer_depth` — Current depth (must be >= 10 to trigger)

**Log format:**
```
INV-NO-PAD-WHILE-DEPTH-HIGH VIOLATION: depth=X, expected_ct=Y, next_frame_ct=Z, reason=<PadReason>
```

This format tells you:
- If `next_frame_ct > expected_ct` → CT slot skipped (frame arrived late or CT mismatch)
- If `next_frame_ct < expected_ct` → Frames exist but are stale (dequeue logic bug)
- If `reason=PRODUCER_GATED` with high depth → Flow control inversion

**Counter:**
- `pad_while_depth_high_` - Count of violations

---

## Log Coverage Requirements

All Layer 3 invariants MUST emit logs. This table summarizes log patterns:

| Invariant | Log Pattern | Level | Rate Limit |
|-----------|-------------|-------|------------|
| INV-P8-WRITE-BARRIER-DIAG | `INV-P8-WRITE-BARRIER: Frame discarded` | INFO | Per occurrence |
| INV-P9-AUDIO-GATE-VIOLATION | `INV-P9-AUDIO-GATE-VIOLATION: ...` | ERROR | Per occurrence |
| INV-P10-FRAME-DROP-FORBIDDEN | `INV-P10-FRAME-DROP-FORBIDDEN VIOLATION` | ERROR | Per occurrence |
| INV-P10-PAD-REASON | `INV-P10-PAD-REASON: ...` | DEBUG | Aggregated (1/sec or first-per-reason) |
| INV-NO-PAD-WHILE-DEPTH-HIGH | `INV-NO-PAD-WHILE-DEPTH-HIGH VIOLATION` | ERROR | Per occurrence |

**Logging doctrine:** Per-frame logging is forbidden in steady-state for high-frequency events (pad emission). Use counters + aggregated logs. Per-occurrence logging is allowed for violations and rare events.

---

## Pending Invariants (Awaiting Promotion)

These invariants are drafted from RULE_HARVEST analysis. They are NOT diagnostic invariants — they require promotion to appropriate layers.

### True Diagnostics (Layer 3 candidates)

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-TIMING-DESYNC-LOG-001 | Log when audio-video timing diverges beyond threshold |

### Candidate Layer 1 Semantics (NOT diagnostics)

| Rule ID | One-Line Definition | Target Layer |
|---------|---------------------|--------------|
| INV-STARVATION-FAILSAFE-001 | Operationalizes LAW-OUTPUT-LIVENESS with bounded time for pad emission | Layer 1 (Semantics) |

### Candidate System/Lifecycle Policy (NOT diagnostics)

| Rule ID | One-Line Definition | Target Location |
|---------|---------------------|-----------------|
| INV-NETWORK-BACKPRESSURE-DROP-001 | Network layer drops (not blocks) under congestion | Core/System policy (not AIR) |

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - LAW-OBS-001 through LAW-OBS-005
- [PHASE10_FLOW_CONTROL.md](../coordination/PHASE10_FLOW_CONTROL.md) - Flow control context
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
