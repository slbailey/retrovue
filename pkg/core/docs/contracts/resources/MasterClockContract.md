# MasterClock

Status: Enforced

## Purpose

Define the runtime contract for MasterClock — the single source of truth for time within RetroVue. Aligns with local-time methodology: inputs/outputs presented in local system time; storage and inter-component exchange in UTC.

---

## Scope

Applies to runtime components (ScheduleService, ChannelManager, ProgramDirector, AsRunLogger) and CLI test commands that validate MasterClock behavior.

---

## Interface (authoritative)

- `now_utc() -> datetime` (tz-aware UTC)
- `now_local() -> datetime` (tz-aware, system local timezone)
- `to_local(dt_utc: datetime) -> datetime` (UTC aware → local aware)
- `to_utc(dt_local: datetime) -> datetime` (local aware → UTC aware)
- `seconds_since(dt: datetime) -> float` (non-negative offset; clamps future to 0.0)

Notes:

- No per-channel timezone. "Local" means system local timezone.
- All datetimes are tz-aware; naive datetimes are rejected.

---

## Behavior Rules (MC-#)

- MC-001: All returned datetimes are tz-aware. UTC is authoritative for storage and exchange.
- MC-002: Time monotonicity — `now_utc()` never appears to go backward within a process.
- MC-003: `seconds_since(dt)` never returns negative values; future timestamps clamp to 0.0.
- MC-004: Naive datetimes passed to conversion methods raise ValueError.
- MC-005: Local time is the system timezone; no per-channel timezone parameters.
- MC-006: Passive design — no timers, listeners, or event scheduling APIs.
- MC-007: Single source of "now" — runtime components must not call `datetime.now()` directly.

---

## Integration Guarantees

- ScheduleService: uses `now_utc()` and converts to local once; applies channel policy (grid, offsets, broadcast_day_start) without per-channel tz.
- ChannelManager/ProgramDirector: use `now_utc()` for offsets/timestamps; local only for operator display.
- AsRunLogger: logs UTC; may include local display time via `now_local()` or `to_local()`.

---

## CLI Test Commands

### `retrovue runtime masterclock`

**Purpose**: Sanity-check core MasterClock behaviors.

**Command Shape**:

```bash
retrovue runtime masterclock [--json] [--precision {second|millisecond|microsecond}]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Infra or contract violation

**JSON Output** (authoritative):

```json
{
  "status": "ok",
  "uses_masterclock_only": true,
  "tzinfo_ok": true,
  "monotonic_ok": true,
  "naive_timestamp_rejected": true,
  "max_skew_seconds": 0.005
}
```

**Behavior Rules**:

- B-1: Validates MC-001 (tz-aware outputs)
- B-2: Validates MC-002 (monotonicity)
- B-3: Validates MC-003 (non-negative seconds_since)
- B-4: Validates MC-004 (naive rejection)
- B-5: Validates MC-007 (no direct datetime.now() usage)

---

### `retrovue runtime masterclock-monotonic`

**Purpose**: Proves time doesn't "run backward" and `seconds_since()` is never negative.

**Command Shape**:

```bash
retrovue runtime masterclock-monotonic [--json]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "monotonic_ok": true,
  "seconds_since_negative_ok": true,
  "future_timestamp_clamp_ok": true
}
```

**Behavior Rules**:

- B-6: Time never goes backward between consecutive calls (MC-002)
- B-7: `seconds_since()` with future timestamps returns 0.0 (MC-003)
- B-8: `seconds_since()` with past timestamps returns positive values (MC-003)

**Why it matters**: ChannelManager uses `seconds_since()` to compute mid-program offsets. We need non-negative offsets.

---

### `retrovue runtime masterclock-logging`

**Purpose**: Verifies timestamps for AsRunLogger are correct and consistent.

**Command Shape**:

```bash
retrovue runtime masterclock-logging [--json]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "tzinfo_ok": true,
  "utc_local_consistent": true,
  "precision_maintained": true
}
```

**Behavior Rules**:

- B-9: All timestamps are timezone-aware (MC-001)
- B-10: UTC and local timestamps are consistent
- B-11: Millisecond precision is maintained

**Why it matters**: AsRunLogger will rely on this format for audit trails.

---

### `retrovue runtime masterclock-scheduler-alignment`

**Purpose**: Validates that ScheduleService obtains time only via MasterClock and preserves broadcast-day boundary logic. Also detects any use of non-MasterClock timestamps in scheduling logic and fails if found.

**Command Shape**:

```bash
retrovue runtime masterclock-scheduler-alignment [--json]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "scheduler_uses_masterclock": true,
  "uses_masterclock_only": true,
  "naive_timestamp_rejected": true,
  "boundary_conditions_ok": true,
  "dst_edge_cases_ok": true
}
```

**Behavior Rules**:

- B-12: Boundary conditions work correctly
- B-13: DST edge cases are handled
- B-14: Off-by-one errors are prevented
- B-15: Uses MasterClock only (MC-007)
- B-16: Naive timestamps rejected (MC-004)

**Why it matters**: The guide channel and "Now Playing / Coming Up Next" banners depend on getting this right.

---

### `retrovue runtime masterclock-stability`

**Purpose**: Stress-tests that repeated tz conversion doesn't leak memory or fall off a performance cliff.

**Command Shape**:

```bash
retrovue runtime masterclock-stability [--json] [--iterations <int>]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation or performance degradation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "peak_calls_per_second": 50000,
  "min_calls_per_second": 45000,
  "final_calls_per_second": 48000,
  "memory_stable": true,
  "cache_hits": 9500,
  "cache_misses": 500
}
```

**Behavior Rules**:

- B-17: Performance remains stable over time
- B-18: Memory usage doesn't grow unbounded
- B-19: Timezone caching works efficiently

**Why it matters**: ProgramDirector and ChannelManager are long-lived; we need to prove we don't keep creating new ZoneInfo objects forever.

---

### `retrovue runtime masterclock-consistency`

**Purpose**: Makes sure different high-level components would see the "same now," not different shapes of time. Also verifies that timestamps from ProgramDirector and ChannelManager are tz-aware, serialize to ISO 8601 with offsets, and round-trip back into equivalent instants in UTC.

**Command Shape**:

```bash
retrovue runtime masterclock-consistency [--json]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "max_skew_seconds": 0.001,
  "tzinfo_ok": true,
  "roundtrip_ok": true,
  "all_tz_aware": true
}
```

**Behavior Rules**:

- B-20: All timestamps are timezone-aware (MC-001)
- B-21: Maximum skew between components is minimal
- B-22: No naive datetimes are returned (MC-004)
- B-23: Round-trip accuracy is maintained

**Why it matters**: This catches any accidental direct `datetime.utcnow()` usage in one component vs `clock.now_utc()` in another.

---

### `retrovue runtime masterclock-serialization`

**Purpose**: Makes sure we can safely serialize timestamps and round-trip them.

**Command Shape**:

```bash
retrovue runtime masterclock-serialization [--json]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Contract violation

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "roundtrip_ok": true,
  "iso8601_ok": true,
  "tzinfo_preserved": true
}
```

**Behavior Rules**:

- B-24: Timezone information is preserved
- B-25: Round-trip accuracy is maintained
- B-26: ISO 8601 serialization works correctly

**Why it matters**: These timestamps will end up in logs, DB rows, API responses, and CLI output. If we lose timezone info on serialization, we create pain later.

---

### `retrovue runtime masterclock-performance`

**Purpose**: Performance benchmarking for MasterClock operations.

**Command Shape**:

```bash
retrovue runtime masterclock-performance [--json] [--iterations <int>]
```

**Exit Codes**:

- `0`: All checks pass
- `1`: Performance below threshold

**JSON Output**:

```json
{
  "status": "ok",
  "test_passed": true,
  "iterations": 10000,
  "peak_calls_per_second": 50000,
  "min_calls_per_second": 45000,
  "final_calls_per_second": 48000,
  "memory_usage_mb": 15.2,
  "cache_hits": 9500,
  "cache_misses": 500
}
```

**Behavior Rules**:

- B-27: Performance metrics are within acceptable thresholds
- B-28: Cache efficiency is maintained

---

## Failure Scenarios

### Common Failures

**Direct datetime.now() usage**:

```json
{
  "status": "error",
  "test_passed": false,
  "uses_masterclock_only": false,
  "errors": ["Component ChannelManager uses datetime.now() directly"]
}
```

**Naive timestamp acceptance**:

```json
{
  "status": "error",
  "test_passed": false,
  "naive_timestamp_rejected": false,
  "errors": ["Component accepted naive datetime without timezone info"]
}
```

**Performance degradation**:

```json
{
  "status": "error",
  "test_passed": false,
  "peak_calls_per_second": 1000,
  "min_calls_per_second": 500,
  "errors": ["Performance degraded below acceptable threshold"]
}
```

**Timezone conversion failure**:

```json
{
  "status": "error",
  "test_passed": false,
  "tzinfo_ok": false,
  "errors": ["Timezone information lost during conversion"]
}
```

---

## Design Principles

- **Safety first**: All tests run against isolated test environments
- **Contract enforcement**: All runtime components must use MasterClock exclusively
- **Tz-aware by default**: Naive datetimes are rejected at all boundaries
- **Performance stability**: Long-running processes must not degrade over time
- **Consistency**: All components see the same "now" with minimal skew

---

## Test Coverage Mapping

| Rule ID | Test Command                              | Assertion                    |
| ------- | ----------------------------------------- | ---------------------------- |
| MC-001  | `runtime masterclock`                     | `tzinfo_ok`                  |
| MC-002  | `runtime masterclock-monotonic`           | `monotonic_ok`               |
| MC-003  | `runtime masterclock-monotonic`           | `seconds_since_negative_ok`  |
| MC-004  | `runtime masterclock`                     | `naive_timestamp_rejected`   |
| MC-007  | `runtime masterclock`                     | `uses_masterclock_only`      |
| MC-007  | `runtime masterclock-scheduler-alignment` | `scheduler_uses_masterclock` |

---

## CI Integration

These tests are designed for CI integration to guarantee that RetroVue never regresses and starts using system time directly or loses timezone information. The tests should be run as part of the continuous integration pipeline to ensure MasterClock contracts remain enforced.

---

## See also

- [ScheduleService](../../runtime/schedule_service.md) — Uses MasterClock for all scheduling operations
- [MasterClock (domain doc)](../../domain/MasterClock.md) — Domain model and integration patterns
- [Channel Contract](ChannelContract.md) — Channel domain contracts
