# Rational FPS: Lossy Conversion Boundaries

Authoritative timing in blockplan hot paths is integer/rational (`RationalFps`, integer ceil/floor arithmetic).

Remaining intentional floating-point boundaries:

1. **External/API input adapters**
   - `DeriveRationalFPS(double)` in `BlockPlanSessionTypes.hpp`
   - Purpose: convert inbound decimal FPS values from config/tests/proto edges into canonical rationals.
   - Boundary: lossy by definition at API ingress; once converted, internal timing must stay rational.

2. **Frame metadata duration field**
   - `buffer::Frame::metadata.duration` is a `double` (seconds).
   - TickProducer sets this from rational `den/num` as a final representation step.
   - This is representational only; pacing/fence/ct arithmetic remains integer/rational.

3. **Human-readable logging / telemetry formatting**
   - `ToDouble()` usage in debug logs (e.g., FPS ratio text).
   - Not used for fence/deadline/ct authority.

Guardrail:
- `pkg/air/scripts/check_rationalfps_hotpath.sh` enforces no `1.0/fps` or `1000.0/fps` regressions in blockplan hot path + relevant contracts, and forbids `DeriveRationalFPS(30.0|29.97|59.94|23.976)` in targeted tests.
