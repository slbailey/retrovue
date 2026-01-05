_Related: [Architecture](../overview/architecture.md) • [Contracts](../contracts/resources/README.md) • [Channel](Channel.md) • [Runtime: Schedule service](../runtime/schedule_service.md)_

# Domain — MasterClock

## Purpose

Provide a single source of station time — a monotonic timeline shared by all runtime components — so scheduling, playout, and logging operate against the same notion of “now”.

## Core model / scope

- MasterClock returns station time as a monotonically increasing number of seconds.
- Station time is independent of wall clock time; it never jumps backwards and can run faster or slower than real time.
- All runtime code MUST use MasterClock instead of `time.time()`, `datetime.now()`, or `datetime.utcnow()`.
- Converting station time to wall clock timestamps is a higher-level concern handled where persistence or operator-facing output is generated.

## Station time vs. wall clock

- **Station time** is monotonic and deterministic. It drives playout math, offsets, and sequencing.
- **Wall clock time** (UTC or local timezone) is what operators see on EPGs or logs.
- Runtime components consume station time; translation to wall clock happens in adapters that need to render timestamps.
- This separation prevents leap seconds, DST shifts, or system clock corrections from causing playout regressions.

## Contract / interface

MasterClock exposes a single method:

- **`now() -> float`** — Returns the current station time in seconds. The value is monotonically increasing and represents the authoritative clock for runtime decisions.

No additional helpers (UTC/local conversions, `seconds_since`, etc.) are provided at this layer. Downstream code wraps station time with domain-specific helpers as needed.

## Implementations

### RealTimeMasterClock

- Wraps a monotonic timer (default: `time.perf_counter()`).
- Applies an optional scale factor so station time can run faster or slower than wall clock (e.g., rate = 2.0 doubles elapsed time).
- Ensures forward-only progression even if the underlying monotonic source misbehaves.
- Used in production runners and simulations that need to track real elapsed time.

### SteppedMasterClock

- Deterministic clock for tests.
- Station time advances only when `advance(seconds)` is called.
- Thread-safe enough for test environments; callers typically run in a single thread but locking guards accidental contention.
- Ideal for asserting playout math without waiting on real time.

## Validation & invariants

- **MC-001**: `now()` never decreases during process lifetime.
- **MC-002**: Scaling is multiplicative; `rate = 2.0` doubles elapsed time compared to the monotonic source.
- **MC-003**: No direct calls to system time APIs in runtime packages.
- **MC-004**: Stepped clocks only move forward when explicitly advanced.
- **MC-005**: MasterClock is read-only; it emits time but never drives callbacks or scheduling loops.

## Integration guidelines

- Inject a `MasterClock` into runtime services (ScheduleService, ChannelManager, ProgramDirector, AsRunLogger).
- Use station time for offsets and sequencing, then translate to wall clock times at the boundary where data is persisted or shown to operators.
- When tests require deterministic timing, use `SteppedMasterClock` and advance it explicitly.
- Operators and CLI surfaces continue to rely on contract docs for timestamp formatting — MasterClock does not dictate presentation.

## Testing

- Unit tests cover monotonicity, scale factors, and deterministic stepping.
- Contract tests enforce that CLI surfaces still display correct timestamps by using the injected clock during scenarios.
- Regression tests ensure no component reintroduces direct `datetime.utcnow()` or `time.time()` calls within runtime packages.

## See also

- [MasterClock Contract](../contracts/resources/MasterClockContract.md) — Runtime contract and validation rules
- [ScheduleService](../runtime/schedule_service.md) — Consumes MasterClock for horizon advancement
- [ChannelManager](../runtime/ChannelManager.md) — Uses MasterClock for playout offsets
- [ProgramDirector](../runtime/program_director.md) — Coordinates runtime operations using station time
- [AsRunLogger](../runtime/AsRunLogging.md) — Converts station time to operator-visible timestamps

