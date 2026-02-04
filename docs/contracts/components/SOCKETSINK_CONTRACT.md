# SocketSink Contract

**Status:** Canonical
**Layer:** Transport (below OutputBus, outside broadcast semantics)
**Scope:** Non-blocking delivery of encoded bytes to a single socket
**Authority:** Mechanical delivery only; must never affect broadcast timing or selection

---

## 1. Purpose

SocketSink is a **non-blocking byte consumer** that writes encoded transport packets (e.g., MPEG-TS) to a socket.

It exists to:
1. **Accept** bytes from OutputBus without blocking
2. **Deliver** bytes to a socket best-effort
3. **Absorb** kernel/network backpressure without propagating upstream
4. **Fail locally** without affecting AIR runtime correctness

SocketSink is transport, not broadcast.

---

## 2. Authority Boundaries

### SocketSink Owns

| Concern | Ownership |
|---------|-----------|
| Socket write mechanics | Owns |
| Kernel backpressure handling | Owns |
| Local buffering policy | Owns |
| Drop/overwrite policy | Owns |
| Transport-level error handling | Owns |
| Per-sink telemetry | Owns |

### SocketSink Does NOT Own

| Concern | Correct Owner |
|---------|---------------|
| Frame selection | ProgramOutput |
| Timing / pacing | MasterClock / Mux |
| CT / PTS authority | Producers / Mux |
| Broadcast correctness | Laws + ProgramOutput |
| Sink attach/detach timing | Core |
| Viewer presence | Core |
| Retry semantics | **Forbidden** |

---

## 3. Core Invariants

### SS-001 — Non-Blocking Ingress (HARD LAW)

**`Consume()` MUST NOT block. Ever.**

- No waiting on socket readiness
- No waiting on kernel buffers
- No mutex contention in hot path
- No condition variables

If bytes cannot be accepted immediately, the sink MUST apply its local drop/overwrite policy.

**Violation of SS-001 is a violation of LAW-OUTPUT-LIVENESS.**

```cpp
// ✅ CORRECT: Non-blocking consume
bool SocketSink::TryConsumeBytes(const uint8_t* data, size_t len) {
    ssize_t written = send(fd_, data, len, MSG_DONTWAIT);
    if (written < 0) {
        drops_++;
        return false;
    }
    return true;
}

// ❌ FORBIDDEN: Blocking consume
bool SocketSink::TryConsumeBytes(const uint8_t* data, size_t len) {
    while (send(fd_, data, len, 0) < 0) {  // WRONG — blocks on EAGAIN
        usleep(1000);  // WRONG — sleeping
    }
    return true;
}
```

---

### SS-002 — Local Backpressure Absorption

Socket backpressure MUST be absorbed locally.

**Forbidden behaviors:**
- Blocking OutputBus
- Signaling "slow sink" upstream
- Asking ProgramOutput to slow down
- Dropping frames upstream

**Allowed behaviors:**
- Drop newest packets
- Drop oldest packets
- Overwrite a 1-slot buffer
- Disconnect socket

---

### SS-003 — Bounded Memory

SocketSink MUST use bounded memory.

**Examples:**
- Zero buffering (write or drop)
- Single-slot overwrite buffer
- Fixed-size ring buffer (small, e.g., <100ms)

**Unbounded queues are forbidden.**

---

### SS-004 — Best-Effort Delivery

SocketSink makes **no guarantee** that all bytes reach the client.

This is acceptable and correct because:
- Broadcast correctness is upstream
- Transport reliability is not guaranteed
- Clients may be slow or malicious

**No retries. No reordering. No repair.**

---

### SS-005 — Failure Is Local

On socket error:
1. Log (rate-limited)
2. Increment error counters
3. Optionally close socket
4. Continue accepting bytes (discarding if needed)

**Socket failure MUST NOT:**
- Detach itself from OutputBus
- Signal lifecycle changes
- Affect AIR runtime

Core decides if/when to detach.

---

### SS-006 — No Timing Authority

SocketSink MUST NOT:
- Sleep
- Pace output
- Delay writes
- Interpret CT/PTS
- Batch frames to "smooth" delivery

Timing belongs to mux and clock. SocketSink writes bytes when it can.

---

## 4. Required API Shape

### Mandatory Interface

```cpp
class SocketSink {
public:
    // MUST be non-blocking
    bool TryConsumeBytes(const uint8_t* data, size_t len);

    // Optional lifecycle
    void Close();   // idempotent
};
```

**Return value semantics:**
- `true` = bytes accepted
- `false` = bytes dropped (locally)

No exceptions. No retries.

---

## 5. Recommended Internal Models

### Model A (Simplest, Often Enough)

- Non-blocking socket (`O_NONBLOCK`)
- `send()` once
- If `EWOULDBLOCK` / `EAGAIN` → drop

This is totally acceptable.

### Model B (Safer for Bursty Encoders)

- One-slot overwrite buffer
- Writer thread drains slot to socket
- New writes overwrite old if slot occupied

Still bounded. Still non-blocking ingress.

---

## 6. Telemetry Requirements

SocketSink MUST expose counters:

| Metric | Meaning |
|--------|---------|
| `socket_bytes_written_total` | Successfully written bytes |
| `socket_bytes_dropped_total` | Dropped bytes |
| `socket_write_errors_total` | Write failures |
| `socket_disconnects_total` | Socket closed |

**No per-write logging.**

---

## 7. Explicit Non-Responsibilities

**SocketSink MUST NOT:**
- Know how many HTTP clients exist
- Track viewers
- Retry delivery
- Signal readiness upstream
- Trigger AIR shutdown
- Attach/detach itself
- Perform fan-out

HTTP fan-out happens above this sink.

---

## 8. Relationship to OutputBus

| Concern | Owner |
|---------|-------|
| When to attach | Core |
| Where bytes go | OutputBus |
| How bytes reach socket | SocketSink |
| What if socket is slow | SocketSink drops |
| What if no socket | OutputBus discards |

**OutputBus must be able to call SocketSink without fear.**

---

## 9. Test Obligations

| Test | Requirement |
|------|-------------|
| SS-T001 | `TryConsumeBytes` never blocks (time-bounded, e.g., <1ms) |
| SS-T002 | Socket backpressure does not block ingress |
| SS-T003 | Memory usage bounded under sustained load |
| SS-T004 | Errors do not propagate upstream |
| SS-T005 | Drop counters increment correctly |

---

## 10. Derivation Notes

| This Contract | Derives From | Relationship |
|---------------|--------------|--------------|
| SS-001 | LAW-OUTPUT-LIVENESS | **Supports** — non-blocking preserves liveness |
| SS-001 | OB-001 (OutputBus) | **Enables** — OutputBus requires non-blocking sink |
| SS-002 | OB-002 (OutputBus) | **Extends** — backpressure absorbed at each layer |
| SS-005 | OB-003 (OutputBus) | **Supports** — errors don't cause implicit detach |
| SS-006 | OB-005 (OutputBus) | **Extends** — no timing authority at any layer |

---

## Cross-References

- [OUTPUTBUS_CONTRACT.md](./OUTPUTBUS_CONTRACT.md) — Upstream: byte routing
- [PROGRAMOUTPUT_CONTRACT.md](./PROGRAMOUTPUT_CONTRACT.md) — Upstream: frame selection
- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) — LAW-OUTPUT-LIVENESS
- [PHASE10_FLOW_CONTROL.md](../coordination/PHASE10_FLOW_CONTROL.md) — Flow control context
