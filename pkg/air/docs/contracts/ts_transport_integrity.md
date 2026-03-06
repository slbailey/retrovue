# TS Transport Integrity Contract

**Status:** Active
**Scope:** MPEG-TS output bytes observable by any viewer
**Owner:** AIR (EncoderPipeline muxer path)

## Purpose

This contract defines the observable correctness properties of MPEG-TS output.
Every invariant is testable against raw TS bytes — no internal state inspection required.

These properties are mandatory for:
- Decoder compatibility (any standards-compliant MPEG-TS demuxer)
- Mid-stream joinability (viewer tunes in at arbitrary time)
- Continuous playback without glitches or decoder resets

## Invariants

### INV-TS-SYNC
Every TS packet starts with sync byte `0x47`.

**Rationale:** ISO 13818-1 §2.4.3.2. Without sync bytes, no demuxer can find packet boundaries.

### INV-TS-CONTINUITY
Per-PID continuity counter increments by 1 (mod 16) between consecutive packets carrying payload.
Duplicate CC values are permitted for adaptation-only packets and retransmissions.

**Rationale:** ISO 13818-1 §2.4.3.3. CC discontinuities cause decoders to drop data or reset.

### INV-PCR-MONOTONIC
PCR values on any given PID never decrease.

**Rationale:** ISO 13818-1 §2.4.2.2. Non-monotonic PCR causes decoder clock recovery to fail.

### INV-PCR-INTERVAL
PCR packets repeat at intervals ≤ 100ms (tolerance: 133ms for bitrate bursts).

**Rationale:** ISO 13818-1 §2.7.2 specifies ≤ 100ms between PCRs. A receiver that loses lock
requires frequent PCR updates to resynchronize. The 133ms test tolerance accounts for
bitrate-dependent packet spacing in low-bitrate streams.

### INV-PAT-REPETITION
PAT (PID 0x0000) sections repeat at intervals ≤ 500ms.

**Rationale:** ISO 13818-1 §2.4.4.3. A joining client needs PAT to discover program structure.
Without PAT, no PMT PID is known and no elementary streams can be identified.

### INV-PMT-REPETITION
PMT sections repeat at intervals ≤ 500ms.

**Rationale:** ISO 13818-1 §2.4.4.8. After discovering PMT PID from PAT, the client needs
PMT to identify elementary stream PIDs and codec parameters.

### INV-TS-JOINABLE
A client connecting at any point in the stream can decode without waiting for future
parameter sets or timing recovery. This requires PAT and PMT to be periodically present
(covered by INV-PAT-REPETITION and INV-PMT-REPETITION) and PCR to be available for
clock recovery (covered by INV-PCR-INTERVAL).

**Rationale:** Composite invariant. A broadcast stream must be self-describing at all times.

### INV-PCR-CLOCK-REFERENCE
PCR progression matches the playout timeline without accumulating drift.
Over a known encoding duration, the total PCR range must be within ±2% of the
expected wall-clock duration.

**Rationale:** PCR is the decoder's clock reference. If PCR drifts from the media timeline,
A/V sync degrades and buffer management fails.

## Test Strategy

All tests operate on captured raw TS bytes from EncoderPipeline output.
No FFmpeg demuxer is used for TS-layer inspection — packets are parsed directly
from the 188-byte transport stream packet structure.

See: `tests/contracts/ts_transport_contract_tests.cpp`
