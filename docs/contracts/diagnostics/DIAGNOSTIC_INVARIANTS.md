# Layer 3 - Diagnostic Invariants

**Status:** Canonical
**Scope:** Logging requirements, drop policies, enforcement rails
**Authority:** Observability requirements that do not override runtime behavior

---

## Diagnostic Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P8-WRITE-BARRIER-DIAG** | CONTRACT | FileProducer | P8 | No | Yes |
| **INV-P8-AUDIO-PRIME-STALL** | CONTRACT | MpegTSOutputSink | P8 | No | Yes |
| **INV-P10-FRAME-DROP-POLICY** | CONTRACT | ProgramOutput | P10 | No | Yes |
| **INV-P10-PAD-REASON** | CONTRACT | ProgramOutput | P10 | No | Yes |
| **INV-NO-PAD-WHILE-DEPTH-HIGH** | CONTRACT | ProgramOutput | P10 | No | Yes |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: drop frame, log INV-P8-WRITE-BARRIER |
| INV-P8-AUDIO-PRIME-STALL | Log if video dropped too long waiting for audio prime |
| INV-P10-FRAME-DROP-POLICY | Frame drops forbidden except explicit conditions; must log with reason |
| INV-P10-PAD-REASON | Every pad frame classified by root cause (BUFFER_TRULY_EMPTY, etc.) |
| INV-NO-PAD-WHILE-DEPTH-HIGH | Pad emission with depth >= 10 is a violation; must log |

---

## Detailed Definitions

### INV-P8-WRITE-BARRIER-DIAG

**When `writes_disabled_` is set on a producer, frame drops must be logged with the INV-P8-WRITE-BARRIER tag.**

Log format:
```
[FileProducer] INV-P8-WRITE-BARRIER: Frame dropped (writes_disabled=true, segment_id=N)
```

This diagnostic helps trace:
- Write barrier timing relative to switch
- Frames dropped between barrier and segment closure
- Potential race conditions in barrier application

---

### INV-P8-AUDIO-PRIME-STALL

**Log if video frames are dropped for too long while waiting for audio prime.**

The audio prime sequence requires the first audio frame before video encoding can begin. If this takes too long, video frames accumulate and may be dropped.

Log format:
```
[MpegTSOutputSink] INV-P8-AUDIO-PRIME-STALL: Video dropped for Xms waiting for audio prime
```

Threshold: Log if waiting > 500ms without audio.

---

### INV-P10-FRAME-DROP-POLICY

**Frame drops are forbidden except under explicit conditions.**

**Drops FORBIDDEN when:**
- Buffer has capacity (not full)
- Consumer is keeping up with realtime
- No seek or switch in progress
- No external resource starvation

**Drops ALLOWED when:**
- Buffer is full AND consumer is behind realtime
- Explicit seek/discontinuity requested
- Switch is in progress (Phase 9 takes over)
- System overload detected (CPU > threshold)

**When drops occur, MUST log:**
```
INV-P10-FRAME-DROP: reason=<reason>, dropped=<count>, buffer_depth=<n>
```

**Counters:**
- `retrovue_frames_dropped_total` (by reason)

---

### INV-P10-PAD-REASON

**Every pad frame emitted by ProgramOutput must be classified by root cause.**

| PadReason | Meaning |
|-----------|---------|
| BUFFER_TRULY_EMPTY | Buffer depth is 0, producer is starved |
| PRODUCER_GATED | Producer is blocked at flow control gate |
| CT_SLOT_SKIPPED | Frame exists but CT is in the future |
| FRAME_CT_MISMATCH | Frame CT doesn't match expected output CT |
| UNKNOWN | Fallback for unclassified cases |

**Log format:**
```
[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #N at PTS=Xus reason=<PadReason>
```

**Counters:**
- `pads_buffer_empty_` - Pads emitted due to BUFFER_TRULY_EMPTY
- `pads_producer_gated_` - Pads emitted due to PRODUCER_GATED
- `pads_ct_skipped_` - Pads emitted due to CT_SLOT_SKIPPED
- `pads_ct_mismatch_` - Pads emitted due to FRAME_CT_MISMATCH

---

### INV-NO-PAD-WHILE-DEPTH-HIGH

**Pad emission is a violation if buffer depth >= 10.**

If a pad frame is emitted while video buffer depth is >= 10 frames, this indicates a bug in flow control or CT tracking logic - the buffer has frames but they're not being consumed.

**Log format:**
```
INV-NO-PAD-WHILE-DEPTH-HIGH VIOLATION: Pad emitted while depth=X >= 10
```

**Counter:**
- `pad_while_depth_high_` - Count of violations

---

## Log Coverage Requirements

All Layer 3 invariants MUST emit logs. This table summarizes log patterns:

| Invariant | Log Pattern | Level |
|-----------|-------------|-------|
| INV-P8-WRITE-BARRIER-DIAG | `INV-P8-WRITE-BARRIER: Frame dropped` | INFO |
| INV-P8-AUDIO-PRIME-STALL | `INV-P8-AUDIO-PRIME-STALL: Video dropped` | WARNING |
| INV-P10-FRAME-DROP-POLICY | `INV-P10-FRAME-DROP: reason=...` | WARNING |
| INV-P10-PAD-REASON | `INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad` | DEBUG |
| INV-NO-PAD-WHILE-DEPTH-HIGH | `INV-NO-PAD-WHILE-DEPTH-HIGH VIOLATION` | ERROR |

---

## Proposed Diagnostic Invariants (Pending Promotion)

These invariants are drafted from RULE_HARVEST analysis and await promotion:

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-TIMING-DESYNC-LOG-001 | Log when audio-video timing diverges beyond threshold |
| INV-NETWORK-BACKPRESSURE-DROP-001 | Network layer drops (not blocks) under congestion |
| INV-STARVATION-FAILSAFE-001 | Operationalizes LAW-OUTPUT-LIVENESS with bounded time for pad emission |

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - LAW-OBS-001 through LAW-OBS-005
- [PHASE10_FLOW_CONTROL.md](../coordination/PHASE10_FLOW_CONTROL.md) - Flow control context
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
