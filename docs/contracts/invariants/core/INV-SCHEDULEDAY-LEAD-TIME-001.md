# INV-SCHEDULEDAY-LEAD-TIME-001 — ScheduleDay must be materialized at least min_schedule_day_lead_days before its broadcast date

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Ensures the downstream derivation chain has sufficient lead time to function. Playlist generation and PlaylogEvent rolling-window extension both depend on a materialized ScheduleDay. If a ScheduleDay does not exist until close to its broadcast date, the chain `ScheduleDay → Playlist → PlaylogEvent` cannot maintain the lookahead depth required by `INV-PLAYLOG-LOOKAHEAD-001`, starving the runtime authority layer.

The lead time is deployment-configurable (`min_schedule_day_lead_days`, default: **3**) to accommodate environments with different operational cadences. All comparisons must use the injected value; the literal value 3 must not appear in enforcement code or tests.

## Guarantee

A ScheduleDay for broadcast date D must be materialized (persisted) no later than:

```
D - min_schedule_day_lead_days calendar days (at midnight)
```

With the default deployment value of `min_schedule_day_lead_days = 3`, this means no later than the end of day D-3.

If no ScheduleDay exists for date D by the computed deadline, a lead-time violation MUST be raised. Enforcement is evaluated at every HorizonManager cycle; the violation persists until the ScheduleDay is materialized or the date passes.

## Preconditions

- Channel has at least one active SchedulePlan.
- The date D is within the plan's effective date range.
- `min_schedule_day_lead_days` is injected into the ScheduleDay lead-time check at service initialization. It MUST NOT be read from a hardcoded constant at enforcement time.

## Observability

HorizonManager monitors the materialization lead time for all active channels. For any date D in the planning horizon, if no ScheduleDay exists by `D - min_schedule_day_lead_days`, a lead-time violation MUST be logged with: channel ID, missing date D, evaluated deadline, and configured `min_schedule_day_lead_days` value. HorizonManager MUST trigger emergency generation or escalate the fault.

## Deterministic Testability

Using FakeAdvancingClock: inject `min_schedule_day_lead_days = N` (test with N=3 as default, N=2 and N=5 to verify parameterization). Advance clock to `D - N + 1` (one day past the deadline) with no ScheduleDay materialized for D. Assert the lead-time check raises a violation. Assert violation record includes the configured N value. Assert violation is cleared once the ScheduleDay is materialized. No real-time waits required. Tests MUST NOT hardcode the literal 3 — they must use the injected N.

## Failure Semantics

**Planning fault.** The HorizonManager or SchedulingService failed to advance the materialization horizon ahead of the required lead time. Indicates a scheduling-service liveness failure.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledayLeadTime001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `check_scheduleday_lead_time()` standalone function accepts `resolved_store`, `channel_id`, `target_date`, `now_utc`, `min_lead_days`, `programming_day_start_hour`; computes deadline as `target_date - min_lead_days` at broadcast start; raises `ValueError` with `INV-SCHEDULEDAY-LEAD-TIME-001-VIOLATED` tag if deadline passed and no ScheduleDay exists
- Error message includes the configured `min_schedule_day_lead_days` value (never hardcoded)
- Error tag: `INV-SCHEDULEDAY-LEAD-TIME-001-VIOLATED`
