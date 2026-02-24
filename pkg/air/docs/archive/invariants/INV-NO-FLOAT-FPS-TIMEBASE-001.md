# INV-NO-FLOAT-FPS-TIMEBASE-001 — No Floating FPS Timebase in Runtime

**Status:** Active  
**Owner:** All runtime code under `pkg/air/src` and `pkg/air/include`  
**Enforcement:** Contract test `test_inv_no_float_fps_timebase_001` (scans src/include for forbidden patterns)  
**Related:** INV-FPS-RESAMPLE, INV-FPS-TICK-PTS, DRIFT-REGRESSION-AUDIT-FINDINGS.md, AUTHORITY-SWEEP-FPS-AUDIT.md

---

## Statement

Output timing math MUST use RationalFps (fps_num / fps_den). Runtime code MUST NOT compute frame or tick durations via float-derived formulas such as `1'000'000.0 / fps`, `round(1e6 / fps)`, or equivalent. Exceptions are allowed only in tests or helpers that are explicitly labeled as such (e.g. test-only synthetic frame construction).

---

## Rules

1. **Output timing authority**
   - All frame/tick durations, PTS steps, and deadline intervals used for output scheduling, PTS advancement, or fence/seam math MUST be derived from `RationalFps` (e.g. `RationalFps::FrameDurationUs()`, `DurationFromFramesUs()`, or integer formulas `(n * 1'000'000 * den) / num`).
   - Conversion from double FPS (e.g. config) MUST go through `DeriveRationalFPS()` or equivalent; the result must drive duration math, not a raw `1e6/fps` expression.

2. **Forbidden patterns in runtime code**
   - `1'000'000.0 / fps`, `1'000'000 / fps`, `1000000 / fps`, or `1e6 / fps` (and equivalent with different spacing) when used to compute a frame/tick duration or interval.
   - `round(1e6 / fps)`, `round(1'000'000 / fps)`, or similar when used to compute a frame/tick duration or interval.
   - Any expression that computes a duration (µs or ms) by dividing a million (or 1000 for ms) by a floating-point or unrationalized FPS value.

3. **Exceptions**
   - Code under `pkg/air/tests` or explicitly documented as test-only / diagnostic-only may use float FPS timebase math for synthetic data or telemetry display, provided it is not used to drive output scheduling or PTS in production paths.
   - Comments and documentation that reference forbidden patterns for the purpose of stating they are outlawed are not violations.

---

## Allowed

- `RationalFps::FrameDurationUs()`, `FrameDurationNs()`, `FrameDurationMs()` (integer division from num/den).
- `(n * 1'000'000 * fps_den) / fps_num` and equivalent integer formulas.
- `DeriveRationalFPS(double_fps)` then `fps.FrameDurationUs()`.
- Using `1'000'000` or `1000000` as a constant for unit conversion (e.g. PTS 90k ↔ µs) when not dividing by an FPS to get a duration.

---

## Contract test

`test_inv_no_float_fps_timebase_001.cpp` scans all source files under `pkg/air/src` and `pkg/air/include` and fails if any line (excluding comments) matches the forbidden patterns. A small allowlist can be used for known-safe occurrences; default is none.
