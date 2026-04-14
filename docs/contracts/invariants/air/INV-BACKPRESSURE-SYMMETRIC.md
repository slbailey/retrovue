# INV-BACKPRESSURE-SYMMETRIC

## Behavioral Guarantee

**Slot-capacity backpressure** is **symmetric** between audio and video: when the **decode gate** denies admission because **either** stream’s bounded buffer has **no free slot**, **neither** stream reads the next compressed packet from the demuxer. When admission is granted, both streams may progress subject to other invariants.

**Fill-domain A/V lead at the Push site** (decoded audio **not yet** in `AudioLookaheadBuffer`, or depth above high-water) is **not** governed by the **one-frame** rule in this document; it is governed by **INV-FILL-AV-LEAD-CLAMP-001** with **`av_phase_tolerance_ms`** (default **120 ms**). **Bootstrap clock handoff** additionally requires **INV-BOOTSTRAP-AV-PHASE-001** using the **gate** estimator.

## Authority Model

A **single decode admission decision** in **`VideoLookaheadBuffer::FillLoop`** applies to **both** streams for **INV-DECODE-GATE** (capacity) semantics. **`INV-FILL-AV-LEAD-CLAMP-001`** applies an **additional** gate on **whether decoded audio may Push** at that site, without splitting the demuxer into independent readers.

## Boundary / Constraint

### A — Steady-state slot gate (unchanged core)

When using **only** **INV-DECODE-GATE** capacity semantics: decode of the next interleaved packet pair **MUST NOT** proceed unless **at least one slot** is free in **both** `VideoLookaheadBuffer` and `AudioLookaheadBuffer` (per **INV-DECODE-GATE**). When one side is blocked by **capacity**, the other **MUST** also not advance demux.

**Removed claim:** The steady-state guarantee **MUST NOT** be phrased as “A/V delta ≤ one output frame duration at all times.” That statement was **incorrect** for bootstrap and is **superseded** for lead bounds by **`av_phase_tolerance_ms`** (see **INV-BOOTSTRAP-AV-PHASE-001** / **INV-FILL-AV-LEAD-CLAMP-001**).

### B — Audio under slot backpressure

`AudioLookaheadBuffer::Push` **MUST** block (not discard) when at **capacity** — **queue backpressure**. That is **not** “suppression” under **INV-FILL-AV-LEAD-CLAMP-001**.

### C — Video under pressure

**Video** frames **MAY** be dropped or not enqueued to the deque under documented liveness / full-buffer rules **without** advancing audio past **INV-FILL-AV-LEAD-CLAMP-001** and **INV-AUDIO-CONTINUITY-NO-DROP** carve-outs.

## Violation

- Demux read or decode of one stream while the other is denied by **capacity** gate incorrectly.
- Treating **`av_phase_tolerance_ms`** lead as a violation of **this** invariant’s slot-gate section (it is not — see **INV-FILL-AV-LEAD-CLAMP-001**).

## Required Tests

- `runtime/tests/contracts/Phase10PipelineFlowControlTests.cpp` (`TEST_INV_P10_BACKPRESSURE_SYMMETRIC_NoAudioDrops`)
- `runtime/tests/contracts/Phase9SymmetricBackpressureTests.cpp`

## Enforcement Evidence

- **Symmetric capacity gate:** `VideoLookaheadBuffer` fill thread checks **both** buffers before `av_read_frame` per **INV-DECODE-GATE**.
- **A/V lead at Push:** **INV-FILL-AV-LEAD-CLAMP-001** — fill thread suppresses **Push** when high-water or positive fill delta exceeds policy.
- Contract tests above prove **capacity** symmetry; clamp tests are listed under **INV-FILL-AV-LEAD-CLAMP-001**.

TODO
