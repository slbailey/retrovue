# Phase 8.0 — Transport Contract

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [playout.proto](../../../protos/playout.proto)_

**Principle:** Python creates the byte sink; Air connects and writes. **Runtime is Air-only; ffmpeg fallback has been removed.** GET /channel/{id}.ts serves only real MPEG-TS from Air (sync byte 0x47). No HELLO/dummy bytes in production.

Shared invariants (Python does not run ffmpeg, one logical stream per channel, clean shutdown) are in the [Overview](Phase8-Overview.md).

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

Validate the **transport** path: Python creates the byte sink; Air connects and writes. No FD passing (avoids gRPC/platform issues). No media format assumptions anywhere.

## Proto (exact shape)

Two RPCs on **PlayoutControl**:

- **AttachStream(AttachStreamRequest) → AttachStreamResponse** — tell Air where to write bytes for a channel.
- **DetachStream(DetachStreamRequest) → DetachStreamResponse** — stop writing and disconnect (optional but useful).

### StreamTransport

```text
enum StreamTransport {
  STREAM_TRANSPORT_UNSPECIFIED = 0;
  STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET = 1;  // recommended on Linux
  STREAM_TRANSPORT_TCP_LOOPBACK = 2;        // optional fallback (127.0.0.1:port)
}
```

### AttachStreamRequest

- **channel_id** — target channel.
- **transport** — UDS or TCP loopback.
- **endpoint** — for UDS: path like `/tmp/retrovue/ch_1.sock`; for TCP: `127.0.0.1:15001`.
- **replace_existing** — if true, replacing an existing attachment is allowed; if false, attach when already attached is an error.

### AttachStreamResponse

- **success**, **message**.
- **negotiated_transport**, **negotiated_endpoint** (optional; what Air actually used).

### DetachStreamRequest

- **channel_id**.
- **force** — if true, stop writing immediately; otherwise detach at next safe boundary (optional policy).

### DetachStreamResponse

- **success**, **message**.

## Contract semantics (deterministic tests)

### Ordering rules

1. **StartChannel** must be called **before** AttachStream.
2. **AttachStream** must **succeed** before any bytes are expected on the stream.
3. **StopChannel** implies detach + cleanup (even if DetachStream is not called explicitly).

### Idempotency rules

**AttachStream:**

- If already attached and **replace_existing = false** → **success = false**.
- If already attached and **replace_existing = true** → swap endpoint, **success = true**.

**DetachStream:**

- If not attached → **success = true** (idempotent, no-op).

### Transport rule (Linux default)

Use **Unix Domain Sockets (UDS)** for Phase 8.

- **Python** creates a UDS **server** at a known path (e.g. `/tmp/retrovue/ch_mock.sock`).
- **Air** connects as **client** to that path.
- **Air** writes bytes to the socket.
- **Python** reads from the accepted connection and fans out to HTTP clients.

No FD passing; endpoint is a path string. Works in Cursor/CI with deterministic tests.

## Contract (behavioral)

### Python

- Creates a **UDS server** at a path (e.g. `/tmp/retrovue/ch_mock.sock`).
- After **StartChannel**, calls **AttachStream(channel_id, transport=UNIX_DOMAIN_SOCKET, endpoint=path)**.
- **Exposes GET /channels/{id}.ts** that returns **HTTP 200** and streams bytes from the UDS read side to the response body.
- On client disconnect or **StopChannel**, cleans up; **StopChannel** implies detach even if DetachStream not called.

### Air

- On **AttachStream**, connects as **client** to the given endpoint (UDS path or TCP).
- **Writes arbitrary bytes** to the socket (e.g. `"HELLO\n"` repeated for 8.0).
- **Stops writing** when **DetachStream** or **StopChannel** is called; closes the socket.

### Data (8.0 / current)

- **Production:** Real MPEG-TS only (first byte 0x47). No HELLO, no dummy bytes. Tests assert TS sync once live.
- **Legacy (removed):** HELLO-only mode and ffmpeg fallback are **forbidden**; Air is the only playout engine.

## How it maps to the Phase 8 ladder

### Phase 8.0 (transport + TS)

- **Python:** creates UDS server; exposes GET that streams bytes from the accepted Air connection.
- **Air:** StartChannel → LoadPreview → AttachStream(UDS) → SwitchToLive; writes **real MPEG-TS** (sync 0x47).
- **Test:** GET stream and assert first byte is 0x47 (TS sync). No HELLO; no ffmpeg.

### Phase 8.1 (Air owns MPEG-TS)

- Same transport.
- **Air** replaces `"HELLO\n"` with: ffmpeg (or internal mux) → mpegts bytes → socket.
- **Python** still just reads bytes and serves HTTP.

## Tests (automated)

1. Start ProgramDirector (or minimal HTTP server that serves the stream).
2. **StartChannel(channel_id)**.
3. **AttachStream(channel_id, transport=UNIX_DOMAIN_SOCKET, endpoint=path)** so Air connects and writes.
4. **GET /channels/mock.ts**.
5. **Assert:** HTTP 200; bytes arrive; first byte is 0x47 (MPEG-TS sync); no HELLO.
6. **Shut down:** StopChannel (or DetachStream) and close client; assert stream closes and no hang or leak.

## Explicitly out of scope (8.0)

- No ffmpeg.
- No TS.
- No VLC.
- No media format, codec, or frame semantics.

## Exit criteria

- Raw bytes written by Air are **readable via HTTP** (status 200, body matches written data).
- Stream **shuts down cleanly** (no leaked FDs, no orphan processes).
- **No media assumptions** anywhere in the transport path.
