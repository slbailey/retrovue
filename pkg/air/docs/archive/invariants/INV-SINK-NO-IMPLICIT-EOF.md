# INV-SINK-NO-IMPLICIT-EOF

**Classification**: INVARIANT (Runtime Contract)
**Owner**: MpegTSOutputSink / MuxLoop
**Enforcement Phase**: P10 (Steady-State)

## Definition

After `AttachStream` succeeds, the output sink MUST continue emitting TS packets until one of the following explicit termination conditions occurs:

1. **StopChannel RPC** — Core explicitly stops the channel
2. **DetachStream RPC** — Core explicitly detaches the stream
3. **Slow-consumer detach** — SocketSink buffer overflow (kDetached status)
4. **Fatal socket error** — EPIPE, ECONNRESET, or equivalent I/O failure

## Forbidden Termination Causes

The following events MUST NOT cause sink termination or TS emission cessation:

- **Producer EOF** — FileProducer reaching end of content
- **Empty video queue** — Transient starvation of MuxLoop input
- **Empty audio queue** — Transient starvation of audio frames
- **Decode errors** — Upstream decode failures
- **Segment boundaries** — Transitions between content segments
- **Content deficit** — Gap between EOF and scheduled boundary

## Rationale

Broadcast semantics require continuous transport emission. In real broadcast:
- When source fails, viewers see bars/slate/black — the carrier continues
- The transport layer operates independently of content availability
- Starvation is masked by pad/hold frames, not by stopping emission

VLC and other clients interpret EOF (zero bytes read) as "stream ended" and show
logo/reconnect behavior. This invariant guarantees that EOF only occurs on explicit
operator action.

## Enforcement Mechanism

### Primary: ProgramOutput Pad Frame Generation
When `content_deficit_active_` is set and the frame buffer is empty, ProgramOutput
emits pad frames (black video + silence) at the target frame rate.

### Safety Rail: MuxLoop Starvation Pad
When MuxLoop has no video frame available for > 100ms after steady-state entry,
it generates and encodes a starvation pad frame directly. This is a SAFETY RAIL
that should not normally activate if ProgramOutput is functioning correctly.

### Violation Logging
If MuxLoop exits without explicit stop/detach, it logs:
```
INV-SINK-NO-IMPLICIT-EOF VIOLATION: mux loop exiting without explicit stop (reason=...)
```

If the starvation safety rail activates, it logs:
```
INV-SINK-NO-IMPLICIT-EOF SAFETY RAIL: Mux starvation detected, emitting pad frame
```

## Allowed Termination Paths

| Condition | Allowed | Log Pattern |
|-----------|---------|-------------|
| StopChannel RPC | Yes | `MuxLoop exiting...` |
| DetachStream RPC | Yes | `MuxLoop exiting...` |
| Slow-consumer detach | Yes | `SLOW CONSUMER DETACH` |
| Fatal socket error | Yes | `send() error: ...` |
| Producer EOF | **NO** | VIOLATION if exits |
| Empty queue starvation | **NO** | VIOLATION if exits |
| Decode error | **NO** | VIOLATION if exits |

## Required Tests

- `pkg/air/tests/contracts/test_inv_sink_no_implicit_eof.py` — Python integration test
- `pkg/air/tests/contracts/InvSinkNoImplicitEofTests.cpp` — C++ unit test (future)

## Related Contracts

- `LAW-OUTPUT-LIVENESS` — TS packets must flow continuously; stalls >500ms indicate failure
- `INV-PACING-ENFORCEMENT-002` — Wall-clock pacing and freeze-then-pad behavior
- `INV-P10-SINK-GATE` — Frame consumption gated on sink attachment
- `INV-TRANSPORT-CONTINUOUS` — No timing reset on queue underflow

## Changelog

- 2025-01: Initial definition
