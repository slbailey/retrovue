# INV-FPS-RATIONAL-001: Rational FPS as Single Authoritative Timebase

## Status

**Broadcast-grade invariant.** Single authoritative representation of frame rate in the playout pipeline.

---

## 1. Purpose

RationalFps is the single authoritative representation of frame rate in the playout pipeline.

Floating-point arithmetic is forbidden in any timing or scheduling path. No timing-relevant intermediate value may be represented as float or double.

Any time-derived quantity must originate from `(fps_num, fps_den)`.

---

## 2. Scope

**In scope:** PipelineManager; TickProducer; ProducerPreloader; OutputClock; fence computation; frame budget derivation; cadence gate / decode accumulator; frame scheduling; frame duration math; input FPS from decoder; output channel FPS configuration.

**Excluded:** Logging; debug UI formatting; telemetry display.

---

## 3. Hard Rules

### R1 — Canonical Rational Representation

- All FPS values must be stored as irreducible `(num, den)` pairs.
- All constructors must normalize using GCD.
- Normalization MUST be performed on every construction boundary (decoder ingest, config parse, serialization).
- `den > 0` invariant; `num > 0` invariant (fps must be positive). Invalid inputs are rejected.
- Structural equality only; no tolerance-based comparison.

### R2 — No Floating-Point Timing Arithmetic

Floating-point must not be used in: DROP detection; ratio comparison; cadence setup; frame duration calculation; fence tick computation; frame index → time conversion; OutputClock deadline math; budget math.

No use of `float`, `double`, or floating literals (e.g. `1000.0`, `1e6`) is permitted in any function that influences: fence, budget, cadence, tick scheduling, OutputClock deadlines, or frame index ↔ time conversions.

The only permitted conversion to double is for: logging; human-readable display.

`ToDouble()` MAY exist, but MAY ONLY be used in logging/telemetry/UI paths; it MUST NOT be referenced from blockplan/pipeline hot-path compilation units.

### R2.1 — Canonical timebase helpers (single-source rounding)

- All frame period and conversion math MUST go through a single canonical helper API; duplicate formulas are forbidden.
- Required canonical APIs (names may vary, but behavior must exist in one place only): `FrameDurationUs()` (or ns); `DurationFromFrames(N)`; `FramesFromDurationCeil(delta_us)` and `FramesFromDurationFloor(delta_us)` (explicit rounding policy).
- All call sites MUST use the helper; no ad-hoc `den*num` conversions in-line.
- Rounding policy is explicit at the call site (ceil vs floor), never implicit.

### R3 — Integer Arithmetic Requirement

All FPS-related arithmetic must use: 64-bit integers minimum; `__int128` for cross-multiplication operations.

In particular: `lhs = in.num * out.den`, `rhs = in.den * out.num`. No 64-bit overflow-prone math allowed in ratio detection.

Fence computations MUST use `__int128` for `delta_ms * fps_num` before division. Any multiplication of (ticks/frames) by fps numerator/denominator MUST use `__int128` unless proven safe by bounds.

### R3.1 — Tick and budget type widths

- `session_frame_index`, `fence_tick`, `block_start_tick`, and all budgets/counters derived from them MUST be signed 64-bit integers minimum.
- Use of 32-bit types for any tick/budget value is forbidden in blockplan/pipeline code.

### R4 — Output FPS Is Rational

Channel output FPS must be: stored as RationalFps; persisted as rational; parsed from config as rational. Never represented internally as double. No CLI or config path may produce double fps. Output FPS MUST be stored and transported as rational end-to-end; no transient `double` representation is allowed even for config parsing.

### R5 — Cadence Accumulator Must Be Integer-Based

Cadence decode/repeat patterns must be derived from rational ratio arithmetic. No floating accumulators permitted. Decode gate must produce deterministic patterns independent of runtime duration. Cadence gate state MUST be representable as integers (or rationals) and MUST NOT accumulate floating error. Cadence decisions MUST be derived from rational ratios; ToDouble() is forbidden here.

### R6 — Tick Grid Authority

The session tick grid must derive from RationalFps. All "frame N presentation time" math must use: `epoch + N * (fps_den * time_unit / fps_num)`. Integer arithmetic only.

Decoder PTS time_base and AVRational MUST NOT influence the session tick grid or fence/budget math. Decoder time_base is allowed only for media-time/PTS reporting; scheduling grid math uses ONLY the session output RationalFps.

---

## 4. Forbidden Patterns

- `double fps` / `float fps`
- `1.0 / fps`
- `ceil(delta_ms / FrameDurationMs())` (use canonical FramesFromDurationCeil helper)
- Tolerance comparisons (e.g. `abs(a - b) < 0.001`)
- Using `ToDouble()` inside blockplan or pipeline directories
- Any floating literal in hot-path directories: `*.0`, `1e`, `1E`, `1.0f`, `1000.0`, `1000000.0`
- Any `std::chrono::duration<double>` or similar in hot paths
- Any call to `ToDouble()` from blockplan/pipeline code (allow only in logging modules outside hot path)

---

## 5. Required Tests

**File:** `pkg/air/tests/contracts/test_rational_timebase_integrity.cpp`

Must verify:

- 59.94 → 29.97 DROP step = 2 exactly
- 23.976 → 30 produces stable cadence pattern
- 10-minute simulation produces zero accumulated drift
- Fence tick and budget convergence hold over 100k frames
- All RationalFps constructed are normalized
- Structural equality works after normalization
- FrameIndex↔Time round-trip identity over ≥ 1,000,000 frames (no drift, no off-by-one)
- Hot-path source scan: no float/double usage, no floating literals, no `ToDouble()` usage in prohibited directories

---

## 6. Enforcement

CI must fail if any floating-point arithmetic or floating literals appear in timing/scheduling hot-path code, regardless of variable names.

CI must fail if any tick/budget types are 32-bit in those directories.

Static analysis rule required.

---

## 7. Relationship

| Contract | Role |
|----------|------|
| INV-BLOCK-WALLCLOCK-FENCE-001 | Fence = timing authority |
| INV-FRAME-BUDGET-AUTHORITY | Budget = counting authority |
| INV-BLOCK-LOOKAHEAD-PRIMING | Priming coordination |

RationalFps = timebase authority. Fence and budget derive from the same rational timebase; this invariant does not alter their definitions.

---

## 8. Non-Goals

This invariant does not: define scheduling policy; define cadence selection policy; alter media-time tracking logic; modify FFmpeg decoder internals beyond representation.
