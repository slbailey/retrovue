# Phase 4 — PlayoutPipeline Contract

## Purpose

Translate **conceptual intent** (active ScheduleItem + grid timing) into an **executable instruction**: a **PlayoutSegment** (and thus a PlayoutRequest for a channel). Pure logic; no execution, no Air.

## PlayoutSegment (explicit)

Even if implemented inline, the contract defines a **PlayoutSegment** so broadcast semantics and future optimizations stay clear:

| Field | Meaning |
|-------|---------|
| **asset_path** | Fully-qualified path (or stable id) of the asset to play. |
| **start_offset_ms** | Start position within the asset. **Milliseconds (int64) only.** Media-relative only, never wall-clock. Join-in-progress. Air seeks by offset. |
| **end_offset_ms** or **hard_stop_time_ms** | End of the segment: optional media-relative end offset (ms), or wall-clock time when this segment must stop (next grid boundary). |

**Units:** All offsets are **milliseconds (int64)**. Matches proto `*_ms`; avoids float drift; keeps tests exact; keeps Air simpler. You can display seconds elsewhere if needed.

**end_offset is optional and advisory.** If both **hard_stop_time** and **end_offset** are present, **hard_stop_time is authoritative**; end_offset is advisory only and may be ignored by Air. This protects against later additions of end_offset "for convenience" without changing stopping behaviour.

**Precedence (stopping):** If **hard_stop_time** (or wire: `hard_stop_time_ms`) is present, it is **authoritative**. End_offset / duration is derived and **never overrides** wall-clock time. Grid alignment must always win; duration math can drift. Air has a single stopping rule: stop at or before the hard stop. This keeps behaviour deterministic.

**Offset vs time:** **start_offset_ms** is **media-relative only, never wall-clock-relative**. That keeps segment semantics clean and avoids "start at wall-clock T" creeping into Air. Asymmetry is intentional: Air **seeks by offset**, **stops by time**.

**Air stopping rule (contractual):** Air may stop **at or before** hard_stop_time_ms, but **must never play past it**. This matters for encoder latency, PTS rounding, and real hardware. Broadcast systems allow "≤ boundary", never "> boundary".

ChannelManager (and gRPC) use this shape so that: the mock channel stays simple, broadcast semantics (switch at boundary) stay correct, and future optimizations (e.g. preload windows, trim ranges) don't break the contract.

## Contract

**PlayoutPipeline**:

- Is invoked by ChannelManager (when the full stack runs).
- Is **pure logic**: same inputs → same output.
- Produces a **PlayoutSegment** per invocation (and channel id is applied at request level).

**Inputs**:

- ScheduleItem (conceptual: samplecontent or filler)
- `grid_start`
- `elapsed_in_grid`

**Outputs** (PlayoutSegment; PlayoutRequest = segment + channel id). All offsets in **milliseconds (int64)**:

- **asset_path** — asset reference (path or id)
- **start_offset_ms** — media-relative start offset only; never wall-clock
- **end_offset_ms** (optional, advisory) or **hard_stop_time_ms** — end of segment (hard_stop_time authoritative when present; see precedence above)

At request level: **channel_id**. **PlayoutRequest** is a ChannelManager-local envelope (segment + channel_id) and **is not a wire type**; do not serialize it. ChannelManager maps it to gRPC messages (LoadPreview, etc.).

### PlayoutRequest ↔ gRPC mapping

**PlayoutRequest is a logical construct inside ChannelManager.** It is **not** a 1:1 wire message. ChannelManager realizes each intent over gRPC (see `protos/playout.proto`) as one or more control calls:

| PlayoutRequest intent   | gRPC calls      |
|-------------------------|-----------------|
| Start channel           | `StartChannel`  |
| Prefeed next segment    | `LoadPreview` (payload = PlayoutSegment: asset_path, start_offset_ms, hard_stop_time_ms) |
| Seamless switch at boundary | `SwitchToLive` (unchanged; no segment payload) |
| Mid-stream plan change  | `UpdatePlan`    |

This avoids the misconception that PlayoutRequest is a single RPC payload; the same logical request may drive multiple gRPC calls (e.g. LoadPreview then SwitchToLive).

## Execution (this phase)

- **No process required.** PlayoutPipeline is a function or small service: (ScheduleItem, grid_start, elapsed_in_grid, channel_id) → PlayoutRequest. No Producer or Air is started.
- **Dependency**: Phase 3 resolver produces the active item; Phase 1 provides grid timing. ChannelManager will call this in later phases.

## Test scaffolding

- **Unit tests**: Call the pipeline with fixed inputs and assert exact **PlayoutSegment** (and channel_id) fields. Offsets in ms (int64).
  - Example: at 10:07 (7 min into grid), active item samplecontent → asset_path, start_offset_ms = 420_000 (7 min), hard_stop_time = 10:30, channel_id as given.
  - Example: at 10:26 (26 min into grid), active item filler → asset_path, **start_offset_ms = elapsed_in_grid − sample_duration** (e.g. 26 min − 24:59 = 1:01 → 61_000 ms), hard_stop_time = 10:30.
  - Example: at 10:30 (boundary) → samplecontent, start_offset_ms = 0, hard_stop_time = 11:00.
- Every invocation creates a **new** segment/request; no mutating shared state.

## Tests

- 10:07 → samplecontent @ start_offset_ms = 420_000 (7 min), hard stop 10:30
- 10:26 → filler @ start_offset_ms = elapsed_in_grid − sample_duration (e.g. 61_000 ms), hard stop 10:30
- 10:30 → samplecontent @ start_offset_ms = 0, hard stop 11:00
- Every invocation creates a new instance (no reuse/mutation).

## Out of scope

- ❌ No looping
- ❌ No execution (no spawning Air/ffmpeg)
- ❌ No Air

## Exit criteria

- Requests are deterministic and disposable.
- Automated tests pass without human involvement.
- ✅ Exit criteria: requests are deterministic and disposable; tests pass automatically.
