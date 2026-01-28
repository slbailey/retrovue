# Phase 8.6 — Real MPEG-TS E2E (no fake mux, VLC-playable)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-0 Transport](Phase8-0-Transport.md) · [Phase8-1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [Phase8-4 Persistent MPEG-TS Mux](Phase8-4-PersistentMpegTsMux.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md)_

**Principle:** Remove the fake/dummy byte source (e.g. HELLO or stub TS). The attached stream carries **only** real MPEG-TS bytes produced by Air’s persistent mux (EncoderPipeline) so that end-to-end playback with VLC works.

## Purpose

- **No FakeTSMux / no dummy bytes:** The stream FD MUST NOT receive non–MPEG-TS data (e.g. `HELLO\n`) in the normal operating path. The only bytes written to the stream are valid MPEG-TS from the persistent mux after content is live.
- **E2E with VLC:** Full path Air → UDS → Python → HTTP `GET /channels/{id}.ts` → VLC can open the URL and play video/audio.
- **Same transport and fan-out:** Transport (UDS), AttachStream/DetachStream, and Python fan-out/teardown (8.5) are unchanged; only the **source** of bytes on the FD changes from fake to real TS.

## Contract

### Air

- **AttachStream:** Connects to the stream endpoint (e.g. UDS) and retains the FD. It MUST NOT start a thread that writes dummy bytes (e.g. HELLO) to the FD. The stream may be silent until **SwitchToLive** (or equivalent) starts the real TS mux.
- **After SwitchToLive:** The only writer to the stream FD is the persistent MPEG-TS mux (EncoderPipeline, or equivalent). All bytes written are valid MPEG-TS (sync 0x47, 188-byte packets, PAT/PMT and PES as in 8.4).
- **Stub / test modes:** For Phase 8.0 transport-only contract tests, a separate mode (e.g. `--control-surface-only`) may still write a known test payload (e.g. HELLO) so that tests need not run full decode/mux. That mode is explicitly **not** the normal path for 8.6; in normal operation no such payload is used.
- **Blocking before live:** Until SwitchToLive, reads on the stream FD may block or return zero bytes; this is expected and MUST NOT be treated as an error. (Browsers, curl, and VLC behave differently; implementers must not add placeholder bytes to “fix” this.)

### FakeTSMux status

FakeTSMux (or any dummy byte source, e.g. HELLO) may remain **only**:

- in transport-only unit tests (Phase 8.0), or
- behind an explicit test flag (e.g. `--control-surface-only`).

FakeTSMux MUST NOT be reachable from the normal runtime path used by `retrovue start`. This prevents accidental resurrection of placeholder bytes on the stream.

### Python

- **Unchanged.** Still serves `GET /channels/{id}.ts` as opaque bytes; no TS parsing. Content-Type remains `video/mp2t`.

### E2E acceptance

- **Sequence:** StartChannel → LoadPreview(asset_path, …) → AttachStream(transport, endpoint) → SwitchToLive.
- **Then:** Open `http://<host>:<port>/channels/<channel_id>.ts` in VLC (or equivalent).
- **Criterion:** VLC plays video and audio; no dummy text or invalid TS.

## Execution

- AttachStream: store FD, do **not** start a HELLO (or any dummy) writer thread.
- SwitchToLive: as today, start the TS mux writer thread (FfmpegLoop / EncoderPipeline) that reads frames from the live producer and writes MPEG-TS to the stored FD.
- Until SwitchToLive, the stream may have no data; clients (e.g. browser or VLC) may block on read until the first TS bytes. This is acceptable.

## Tests

- **Unit / contract:** With real mux enabled, assert that no HELLO (or other non-TS) bytes are written to the stream FD after SwitchToLive; optionally sample first N bytes and assert MPEG-TS structure (0x47, 188-byte packets).
- **E2E:** Start channel, LoadPreview, AttachStream, SwitchToLive; GET the stream URL; assert HTTP 200, Content-Type video/mp2t, and that the body starts with valid TS (sync byte, packet size). Manual: open same URL in VLC and confirm playback.

## Exit criteria

- **No fake mux on the normal path:** Stream FD receives only real MPEG-TS from Air after SwitchToLive.
- **VLC E2E:** Opening the stream URL in VLC after the above sequence results in playable video/audio.

## Manual VLC verification

1. Start the full stack (e.g. `retrovue start` or ProgramDirector + Air with a channel running; ensure Air is **not** started with `--control-surface-only`).
2. Run the sequence: StartChannel → LoadPreview(asset_path, …) → AttachStream(UDS) → SwitchToLive.
3. **Launch VLC** (or another player that accepts MPEG-TS over HTTP).
4. In VLC: **Media → Open Network Stream** (or Ctrl+N) and enter:
   - `http://<host>:<port>/channels/<channel_id>.ts`
   - Replace `<host>` with the machine where the HTTP server runs (e.g. `localhost`), `<port>` with the ProgramDirector HTTP port (e.g. `8000`), and `<channel_id>` with the channel id (e.g. `mock` or `test-1`).
5. Press Play. You should see and hear the decoded video/audio with no HELLO or placeholder content.
