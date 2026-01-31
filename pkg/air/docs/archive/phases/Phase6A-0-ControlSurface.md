<!-- ⚠️ Historical document. Superseded by: [PlayoutEngineContract](../../contracts/architecture/PlayoutEngineContract.md) -->

# Phase 6A.0 — Air Control Surface

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md)_

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

Shared invariants (no schedule/plan in Air, segment-based control, clock authority, hard stop authoritative) are defined in the [Overview](Phase6A-Overview.md). **Authoritative definition of clock and other broadcast-grade laws lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../../contracts/PlayoutInvariants-BroadcastGradeGuarantees.md).**

## Purpose

Prove the Air gRPC server **compiles**, **implements the proto**, and **accepts** the four core RPCs. No media, no producers, no frames.

## Contract

**Air (or a minimal server binary):**

- Must compile and link against the generated code from `protos/playout.proto`.
- Must expose **PlayoutControl** with:
  - `StartChannel(StartChannelRequest) → StartChannelResponse`
  - `LoadPreview(LoadPreviewRequest) → LoadPreviewResponse`
  - `SwitchToLive(SwitchToLiveRequest) → SwitchToLiveResponse`
  - `StopChannel(StopChannelRequest) → StopChannelResponse`
- `GetVersion` may be included; `UpdatePlan` is optional for 6A.0.
- Request/response types must match the proto; field semantics (e.g. `channel_id`, `asset_path`, `start_offset_ms`, `hard_stop_time_ms`) are as defined in the proto and Phase 4.
- **Plan handle:** Air must **not** interpret `plan_handle` in 6A.0; it is accepted only to satisfy the proto and for future compatibility.

**Ordering:**

- **StartChannel** initializes channel state but does **not** imply media playback. Media execution begins only after **LoadPreview** + **SwitchToLive**.

**Success vs error semantics (6A.0):** Lock these so the Python side (or future CM) can rely on them:

- **StartChannel** on an already-started channel → **idempotent success** (same result as first start).
- **LoadPreview** before **StartChannel** for that channel → **error** (`success=false`).
- **SwitchToLive** with no preview loaded → **error** (`success=false`).
- **StopChannel** on unknown or already-stopped channel → **idempotent success** (broadcast systems favor safe, idempotent stop).

**Behavior (6A.0):**

- Each RPC must be **accepted** and return a valid response (e.g. `success=true` or a defined error). No requirement to actually start decode or output; stub implementations are sufficient.
- Server must bind and listen; a client (test or ChannelManager) must be able to call all four RPCs and assert on response shape/success.

## Execution

- Build Air (or a minimal gRPC server) with the playout proto; run server; drive it via gRPC client (e.g. C++ or Python test). No media files, no ffmpeg, no frame buffers.

## Tests

- Server starts and accepts connections.
- `StartChannel(channel_id, plan_handle, port)` → response with `success` set.
- `LoadPreview(channel_id, asset_path, start_offset_ms, hard_stop_time_ms)` → response with `success` (and optional `shadow_decode_started`); no actual decode required.
- `SwitchToLive(channel_id)` → response with `success` (and optional `pts_contiguous`).
- `StopChannel(channel_id)` → response with `success`.

## Out of scope (6A.0)

- No real media or file I/O.
- No producer implementation.
- No frames, no TS, no metrics (optional for 6A.0).

## Exit criteria

- gRPC server compiles and implements the proto.
- All four RPCs (StartChannel, LoadPreview, SwitchToLive, StopChannel) accept requests and return valid responses.
- Automated test(s) pass without human involvement.
