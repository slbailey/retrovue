# Playout Authority Contract

**Status**: Active
**Effective**: 2025-02
**Enforced by**: `PLAYOUT_AUTHORITY` constant in `channel_manager.py`

---

## Authority

The **BlockPlan playout path** is the sole authoritative path for live
channel playout in RetroVue.

```
PLAYOUT_AUTHORITY = "blockplan"
```

When this constant is set, no other playout path may be invoked for live
channels.  Attempts to do so will raise a `RuntimeError` with a
descriptive message referencing `INV-PLAYOUT-AUTHORITY`.

---

## Ownership Boundaries

| Concern | Owner | Must NOT cross to |
|---------|-------|-------------------|
| Scheduling, lifecycle, viewer management | Core | AIR |
| Timing, cadence, frame pacing | AIR | Core |
| Encoding, muxing, TS output | AIR | Core |
| Block generation, feeding | Core | AIR (no mid-block) |
| Block execution, fence detection | AIR | Core |

---

## Invariants

### INV-PLAYOUT-AUTHORITY
Only `BlockPlanProducer` may be constructed for live channels.  The
legacy `Phase8AirProducer` (LoadPreview/SwitchToLive) is retained for
reference but blocked from execution.

### INV-ONE-ENCODER-PER-SESSION
AIR creates exactly one `EncoderPipeline` per playout session.  The
encoder is opened at session start and closed at session end.  Block
boundaries do not reset, flush, or reinitialize the encoder.

### INV-ONE-PLAYOUT-PATH-PER-CHANNEL
A channel has exactly one active `Producer` at any time.  There is no
fallback or automatic mode switching between BlockPlan and legacy paths.

### INV-NO-MID-BLOCK-CONTROL
Core does not send RPCs to AIR during block execution.  The only
control-plane events at block boundaries are:
- `BlockCompleted` (AIR → Core): block reached its fence
- `SessionEnded` (AIR → Core): session terminated
- `FeedBlockPlan` (Core → AIR): next block supplied

### INV-SERIAL-BLOCK-EXECUTION
Blocks execute sequentially.  Block N must complete before Block N+1
begins.  There is no overlapping execution.

---

## Telemetry

Each session emits a one-time architectural telemetry log on both sides:

**Core** (Python, at session start):
```
INV-PLAYOUT-AUTHORITY: Channel <id> session started |
  playout_path=blockplan |
  encoder_scope=session |
  execution_model=serial_block |
  block_duration_ms=<ms> |
  authority=blockplan
```

**AIR** (C++, at encoder open):
```
[INV-PLAYOUT-AUTHORITY] channel_id=<id> |
  playout_path=blockplan |
  encoder_scope=session |
  execution_model=serial_block |
  format=<W>x<H>@<fps>
```

---

## Legacy Path Status

| Component | Status | Guardrail |
|-----------|--------|-----------|
| `Phase8AirProducer` | Retained, blocked | `start()` raises `RuntimeError` |
| `LoadPreview` / `SwitchToLive` | Retained in gRPC | Not invoked by BlockPlan path |
| `NormalProducer` | Stub, unused | No guardrail needed |
| `EmergencyProducer` | Stub, unused | No guardrail needed |
| `GuideProducer` | Stub, unused | No guardrail needed |

Legacy code is not deleted.  It is frozen and guarded to prevent
accidental invocation.  Future cleanup may remove it once the BlockPlan
path has sufficient operational history.
