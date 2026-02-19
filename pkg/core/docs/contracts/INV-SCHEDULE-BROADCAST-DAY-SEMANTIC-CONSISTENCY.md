# INV-SCHEDULE-BROADCAST-DAY-SEMANTIC-CONSISTENCY

## Statement

**Any component that computes broadcast day MUST use the channel's configured
timezone before applying the day-start boundary logic.**

`programming_day_start_hour` is a **local-time** concept. It means "the broadcast
day starts at 06:00 in the channel's timezone" (e.g., 06:00 EST = 11:00 UTC for
`America/New_York`). Comparing this hour against UTC produces incorrect broadcast
day assignments whenever the channel timezone differs from UTC.

## Canonical Pattern

```python
from zoneinfo import ZoneInfo

def broadcast_date_for(dt_utc: datetime, channel_tz: str, day_start_hour: int) -> date:
    local_dt = dt_utc.astimezone(ZoneInfo(channel_tz))
    if local_dt.hour < day_start_hour:
        return (local_dt - timedelta(days=1)).date()
    return local_dt.date()
```

## Affected Components

| Component | Status | Notes |
|-----------|--------|-------|
| `schedule_compiler.py` | ✅ Compliant | Uses `ZoneInfo(tz_name)` from DSL |
| `dsl_schedule_service.py` (`_build_initial`) | ✅ Compliant | Reads tz from DSL, converts to local |
| `playlog_horizon_daemon.py` | ✅ Fixed (ceeb664) | Was comparing UTC hour; now uses `channel_tz` |
| `schedule_manager.py` (`_get_programming_day_date`) | ⚠️ Legacy | Uses raw `t.hour`; only affects phase3 channels |
| `planning_pipeline.py` | ℹ️ Review | Uses `programming_day_start_hour` in structs; consumers must apply tz |

## Failure Mode

When violated: Tier-2 fills stop at the UTC day-start boundary. Blocks between
UTC-day-start and local-day-start belong to the previous broadcast day's compiled
schedule but are looked up in the current day's schedule, which hasn't started yet.
Result: unfilled blocks, 100% pad frames, `early_exhaustion=Y`.

## Origin

Discovered 2026-02-19. `cheers-24-7` (tz=America/New_York) experienced a 5-hour
Tier-2 gap from 06:00–11:00 UTC because `PlaylogHorizonDaemon._broadcast_date_for()`
compared `programming_day_start_hour=6` against UTC hour 6 instead of EST hour 1.

## Test Coverage

`tests/contracts/test_horizon_broadcast_day_tz.py` — 10 cases covering UTC, EST,
CET, JST, and the exact regression scenario.
