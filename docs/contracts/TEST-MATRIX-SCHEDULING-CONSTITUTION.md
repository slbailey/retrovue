# Test Matrix: Scheduling Constitution

**Scope:** Deterministic-clock validation of all 6 constitutional Laws and 24 Invariants governing the RetroVue scheduling pipeline.

**Authoritative inputs:**
- `docs/contracts/laws/LAW-*.md` (6 laws)
- `docs/contracts/invariants/core/INV-*.md` (invariants)
- `docs/contracts/HOUSE-STYLE.md`

**Permitted laws (exhaustive):** `LAW-ELIGIBILITY` · `LAW-GRID` · `LAW-CONTENT-AUTHORITY` · `LAW-DERIVATION` · `LAW-RUNTIME-AUTHORITY` · `LAW-IMMUTABILITY`

**Test file target:** `pkg/core/tests/contracts/test_scheduling_constitution.py`

**Marker:** `@pytest.mark.contract`

---

## 1. Purpose

This matrix validates that the scheduling derivation chain upholds every constitutional guarantee without depending on real-time progression, media decoding, or external services.

Every test in this matrix maps to at least one invariant. Every invariant is covered by at least one test. Cross-layer constitutional scenarios validate law-level guarantees that span multiple components.

### Derivation Chain

```
SchedulePlan → ResolvedScheduleDay → TransmissionLog → ExecutionEntry → AsRun
```

---

## 2. Deterministic Execution Model

All tests operate under these constraints:

| Constraint | Rule |
|---|---|
| **Clock** | `FakeAdvancingClock` only. No `datetime.utcnow()`, no `time.sleep()`, no wall clock reads. |
| **Time advancement** | `clock.advance_ms(n)` or `clock.set_utc(t)`. All "now" reads via `clock.now_utc()`. |
| **Lookahead depth** | Expressed as `min_execution_hours`. Injected via fixture. Never hardcoded. |
| **Media** | No ffmpeg, no file decoding, no media reads. Asset records are stubs with metadata only. |
| **Database** | In-memory or test-isolated Postgres (`RETROVUE_DATABASE_URL` pointing to `*_test`). No production data. |
| **External services** | All external dependencies injected as test doubles. No network calls. |
| **Epoch** | Fixed anchor: `EPOCH = 2026-01-01T06:00:00Z` (represents `programming_day_start` for all test channels unless overridden). |

---

## 3. Fixtures and Test Doubles

### 3.1 Clock

`FakeAdvancingClock`: injectable clock that reads and advances deterministically.

| Method | Description |
|---|---|
| `clock.now_utc()` | Returns current clock time as UTC datetime. |
| `clock.advance_ms(n)` | Advances clock by `n` milliseconds. |
| `clock.set_utc(t)` | Sets clock to absolute UTC datetime `t`. |

`ContractClockFixture`: wrapper provided by `conftest.py` as the `contract_clock` fixture.

### 3.2 Lookahead Configuration

`min_execution_hours`: deployment-configurable integer (default: `3`). Injected into all HorizonManager instances under test. Tests MUST assert `depth >= min_execution_hours` rather than `depth >= 3`. Tests that stress the boundary use `min_execution_hours - epsilon` and `min_execution_hours + epsilon` (where `epsilon` is one grid block duration).

### 3.3 Channel

`TestChannel`: stub channel record with fixed grid configuration.

| Field | Default |
|---|---|
| `channel_id` | Fixed UUID (constant per test suite) |
| `grid_block_minutes` | 30 |
| `block_start_offsets_minutes` | [0] |
| `programming_day_start` | "06:00" |

Tests exercising grid-boundary edge cases (midnight wrap, programming-day rollover) use `TestChannelMidnightGrid` with `programming_day_start="00:00"` and `TestChannelOffsetGrid` with `programming_day_start="03:00"`.

### 3.4 Asset Stubs

`EligibleAsset`: stub asset with `state=ready`, `approved_for_broadcast=true`, `duration_seconds=1800`.

`IneligibleAsset`: stub asset with `state=enriching`, `approved_for_broadcast=false`.

`LongformAsset`: stub asset with `state=ready`, `approved_for_broadcast=true`, `duration_seconds=5400` (90 minutes), `breakpoints=[]`.

`LongformCrossDayAsset`: stub asset with `state=ready`, `approved_for_broadcast=true`, `duration_seconds=7200` (120 minutes), `breakpoints=[]`, scheduled to start at `programming_day_start - 60min`.

`ForeignAsset`: stub asset not referenced in any active SchedulePlan zone. Used only to verify foreign-content rejection.

### 3.5 Plan Builder

`TestPlanBuilder`: fluent builder for SchedulePlan + Zone + SchedulableAsset records without requiring the full operator workflow.

### 3.6 Lock Window

`lock_window_depth`: the period before `now_utc()` during which ExecutionEntry records are considered locked. Injected via fixture; default `30 minutes`. Tests use `lock_window_depth` symbolically.

### 3.7 Observability Surfaces

All scheduling services under test must expose:

| Observable | Type | Purpose |
|---|---|---|
| `result.violations` | `list[ViolationRecord]` | Invariant violations raised during operation |
| `result.fault_class` | `str` | `"planning"` \| `"runtime"` \| `"operator"` |
| `result.artifacts_produced` | `list` | Artifacts created during the operation |
| `horizon_manager.last_extension_reason_code` | `str` | Reason code of most recent extension: `"clock_progression"` expected |
| `horizon_manager.extension_attempt_count` | `int` | Total extension cycles since init |

---

## 4. Implementation Status

### Blocker Invariants (ENFORCED)

These invariants have structural enforcement in production code and passing contract tests.

| Invariant | Tests | Status | Enforcement Location |
|---|---|---|---|
| INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | 2 (negative + positive) | **PASS** | `ExecutionWindowStore.add_entries()` rejects entries missing `channel_id` or `programming_day_date` |
| INV-DERIVATION-ANCHOR-PROTECTED-001 | 2 (negative + positive) | **PASS** | `InMemoryResolvedStore.delete()` checks `ExecutionWindowStore.has_entries_for()` before deletion |
| INV-ASRUN-IMMUTABLE-001 | 3 (mutation + deletion + creation) | **PASS** | `AsRunEvent` is `@dataclass(frozen=True)`; `log_playout_end()` uses `dataclasses.replace()` |
| INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 | 2 (reserved) | **SKIPPED** | Not yet filed as a constitutional invariant; override system does not exist yet |
| INV-PLAN-FULL-COVERAGE-001 | 4 (gap reject + exact tile + pds≠00:00 reject + pds≠00:00 tile) | **PASS** | `validate_zone_plan_integrity()` in `zone_add.py` / `zone_update.py` before `db.commit()` |
| INV-PLAN-NO-ZONE-OVERLAP-001 | 4 (overlap reject + day-filter pass + mutation-induced overlap + precedence) | **PASS** | `validate_zone_plan_integrity()` in `zone_add.py` / `zone_update.py` before `db.commit()` |
| INV-PLAN-GRID-ALIGNMENT-001 | 7 (block start/duration/valid + zone end/start/duration/valid) | **PASS** | `validate_zone_plan_integrity()` in `zone_add.py` / `zone_update.py`; `validate_block_assignment()` in `contracts.py` |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | 3 (unanchored reject + plan_id accept + manual override accept) | **PASS** | `_enforce_derivation_traceability()` in `schedule_manager_service.py`; `InMemoryResolvedStore.store()` / `force_replace()` |
| INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | 3 (carry-in overlap reject + carry-in honored accept + no carry-in accept) | **PASS** | `validate_scheduleday_seam()` in `schedule_manager_service.py`; `InMemoryResolvedStore.store()` / `force_replace()` |

### Aspirational Tests (NOT YET IMPLEMENTED)

All test definitions in sections 5–6 (SCHED-DAY-*, PLAYLOG-*, CROSS-*, GRID-STRESS-*, HORIZON-*, CONST-*) are roadmap items. They define the target behavior for future enforcement work. SCHED-PLAN-001 through SCHED-PLAN-006 are now enforced (see Blocker Invariants above).

---

## 5. Invariant → Test Mapping

### Blocker Tests (Implemented)

| Invariant | Test Class | Test Method(s) | Status |
|---|---|---|---|
| INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | `TestInvExecutionDerivedFromScheduleday001` | `test_..._reject_without_lineage`, `test_..._valid_lineage` | PASS |
| INV-DERIVATION-ANCHOR-PROTECTED-001 | `TestInvDerivationAnchorProtected001` | `test_..._reject_delete_with_downstream`, `test_..._allow_delete_without_downstream` | PASS |
| INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 | `TestInvOverrideRecordPrecedesArtifact001` | `test_..._reject_without_record`, `test_..._atomicity` | SKIPPED |
| INV-ASRUN-IMMUTABLE-001 | `TestInvAsrunImmutable001` | `test_..._reject_mutation`, `test_..._reject_deletion`, `test_..._valid_creation` | PASS |
| INV-PLAN-FULL-COVERAGE-001 | `TestInvPlanFullCoverage001` | `test_..._reject_gap`, `test_..._accept_exact_tile`, `test_..._reject_gap_with_pds_0600`, `test_..._accept_tile_with_pds_0600` | PASS |
| INV-PLAN-NO-ZONE-OVERLAP-001 | `TestInvPlanNoZoneOverlap001` | `test_..._reject_overlapping_zones`, `test_..._allow_mutually_exclusive_days`, `test_..._reject_mutation_induced_overlap`, `test_..._precedence_over_gap` | PASS |
| INV-PLAN-GRID-ALIGNMENT-001 | `TestInvPlanGridAlignment001` | `test_..._reject_off_grid_start`, `test_..._reject_off_grid_duration`, `test_..._valid_alignment`, `test_..._reject_off_grid_zone_end`, `test_..._reject_off_grid_zone_start`, `test_..._reject_off_grid_zone_duration`, `test_..._accept_aligned_zone` | PASS |
| INV-SCHEDULEDAY-ONE-PER-DATE-001 | `TestInvScheduledayOnePerDate001` | `test_..._reject_duplicate_insert`, `test_..._allow_force_regen_atomic_replace`, `test_..._different_dates_independent` | PASS |
| INV-SCHEDULEDAY-IMMUTABLE-001 | `TestInvScheduledayImmutable001` | `test_..._reject_in_place_slot_mutation`, `test_..._reject_plan_id_update`, `test_..._force_regen_creates_new_record`, `test_..._operator_override_creates_new_record` | PASS |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | `TestInvScheduledayDerivationTraceable001` | `test_..._reject_unanchored`, `test_..._accept_with_plan_id`, `test_..._accept_manual_override` | PASS |
| INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | `TestInvScheduledaySeamNoOverlap001` | `test_..._reject_carry_in_overlap`, `test_..._accept_carry_in_honored`, `test_..._no_carry_in_independent` | PASS |

### Full Matrix (Aspirational)

| Invariant | Test ID(s) | Layer |
|---|---|---|
| INV-PLAN-FULL-COVERAGE-001 | SCHED-PLAN-001, SCHED-PLAN-002 | SchedulePlan |
| INV-PLAN-NO-ZONE-OVERLAP-001 | SCHED-PLAN-003, SCHED-PLAN-004 | SchedulePlan |
| INV-PLAN-GRID-ALIGNMENT-001 | SCHED-PLAN-005, SCHED-PLAN-006 | SchedulePlan |
| INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | SCHED-PLAN-007, SCHED-PLAN-008 | SchedulePlan |
| INV-SCHEDULEDAY-ONE-PER-DATE-001 | SCHED-DAY-001, SCHED-DAY-002 | ResolvedScheduleDay |
| INV-SCHEDULEDAY-IMMUTABLE-001 | SCHED-DAY-003, SCHED-DAY-004 | ResolvedScheduleDay |
| INV-SCHEDULEDAY-NO-GAPS-001 | SCHED-DAY-005, SCHED-DAY-006 | ResolvedScheduleDay |
| INV-SCHEDULEDAY-LEAD-TIME-001 | SCHED-DAY-007, SCHED-DAY-008 | ResolvedScheduleDay |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | SCHED-DAY-009, SCHED-DAY-010 | ResolvedScheduleDay |
| INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | SCHED-DAY-011, SCHED-DAY-012 | ResolvedScheduleDay |
| INV-PLAYLOG-ELIGIBLE-CONTENT-001 | PLAYLOG-001 | ExecutionEntry |
| INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 | PLAYLOG-002, PLAYLOG-003 | ExecutionEntry |
| INV-PLAYLOG-LOOKAHEAD-001 | PLAYLOG-004, PLAYLOG-005 | ExecutionEntry |
| INV-PLAYLOG-NO-GAPS-001 | PLAYLOG-006, PLAYLOG-007 | ExecutionEntry |
| INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | PLAYLOG-008, PLAYLOG-009 | ExecutionEntry |
| INV-PLAYLOG-LOCKED-IMMUTABLE-001 | PLAYLOG-IMMUT-001, PLAYLOG-IMMUT-002, PLAYLOG-IMMUT-003 | ExecutionEntry |
| INV-NO-FOREIGN-CONTENT-001 | CROSS-FOREIGN-001, CROSS-FOREIGN-002, CROSS-FOREIGN-003 | Cross-cutting |
| INV-PLAYLIST-GRID-ALIGNMENT-001 | PLAYLIST-GRID-001, PLAYLIST-GRID-002, PLAYLIST-GRID-003 | TransmissionLog |
| INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 | HORIZON-001, HORIZON-002 | ExecutionEntry |
| INV-NO-MID-PROGRAM-CUT-001 | CROSS-001, CROSS-002 | Cross-cutting |
| INV-ASRUN-TRACEABILITY-001 | CROSS-003, CROSS-004 | Cross-cutting |

---

## 6. Layer-Specific Test Definitions

### 6.1 Blocker Tests (Implemented)

---

### BLOCKER-001: ExecutionEntry without schedule lineage is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| **Scenario** | ExecutionEntries missing `channel_id` or `programming_day_date` are submitted to ExecutionWindowStore. The store boundary rejects them. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Construct an ExecutionEntry with `programming_day_date=None`. Submit to `ExecutionWindowStore.add_entries()`. 2. Construct an ExecutionEntry with `channel_id=""`. Submit. |
| **Assertions** | Both submissions raise `ValueError` matching `"INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001"`. Store remains empty after both rejected submissions. |
| **Failure Classification** | Planning |
| **Status** | **PASS** |

---

### BLOCKER-002: ExecutionEntry with valid schedule lineage is accepted

| Field | Value |
|---|---|
| **Invariant(s)** | INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| **Scenario** | ExecutionEntries produced from a valid ResolvedScheduleDay carry correct `channel_id` and `programming_day_date`. Store accepts them. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Materialize a ResolvedScheduleDay for `(channel, 2026-01-01)`. 2. Produce 4 ExecutionEntries with matching lineage. 3. Submit to ExecutionWindowStore. |
| **Assertions** | All 4 entries accepted. Each entry has non-null `programming_day_date` matching the source ScheduleDay. |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### BLOCKER-003: Deletion of ResolvedScheduleDay with downstream execution artifacts is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-DERIVATION-ANCHOR-PROTECTED-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-IMMUTABILITY |
| **Scenario** | A ResolvedScheduleDay has downstream ExecutionEntries in the ExecutionWindowStore. Deletion is attempted. The store guard rejects it. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Materialize ResolvedScheduleDay for `(channel, 2026-01-01)`. 2. Populate ExecutionWindowStore with 4 entries referencing that day. 3. Call `InMemoryResolvedStore.delete(channel, 2026-01-01)`. |
| **Assertions** | Deletion raises `ValueError` matching `"INV-DERIVATION-ANCHOR-PROTECTED-001"`. The ResolvedScheduleDay still exists after the rejected deletion. |
| **Failure Classification** | Planning |
| **Status** | **PASS** |

---

### BLOCKER-004: Deletion of ResolvedScheduleDay without downstream artifacts succeeds

| Field | Value |
|---|---|
| **Invariant(s)** | INV-DERIVATION-ANCHOR-PROTECTED-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-IMMUTABILITY |
| **Scenario** | A ResolvedScheduleDay has no downstream ExecutionEntries. Deletion proceeds normally. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Materialize ResolvedScheduleDay for `(channel, 2026-01-02)`. 2. Confirm no ExecutionEntries reference that day. 3. Call `InMemoryResolvedStore.delete(channel, 2026-01-02)`. |
| **Assertions** | Deletion succeeds. The ResolvedScheduleDay no longer exists in the store. |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### BLOCKER-005: AsRunEvent rejects direct field mutation (frozen dataclass)

| Field | Value |
|---|---|
| **Invariant(s)** | INV-ASRUN-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | An AsRunEvent is created via `AsRunLogger.log_playout_start()`. Direct field mutation is attempted. `log_playout_end()` produces a new instance without mutating the original. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Create AsRunEvent via `log_playout_start()`. 2. Attempt `event.end_time_utc = ...` (direct mutation). 3. Call `log_playout_end()` with a new end time. |
| **Assertions** | Direct mutation raises `AttributeError` (frozen dataclass). `log_playout_end()` returns a new instance (`updated is not original`). Original instance is unmodified (`original.end_time_utc == EPOCH`). |
| **Failure Classification** | Runtime |
| **Status** | **PASS** |

---

### BLOCKER-006: AsRunEvent frozen dataclass prevents field reassignment

| Field | Value |
|---|---|
| **Invariant(s)** | INV-ASRUN-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | After creation, direct field assignment on any AsRunEvent attribute raises `AttributeError`. The event persists in the logger. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Create AsRunEvent via `log_playout_start()`. 2. Attempt field assignment. 3. Verify event still exists in logger. |
| **Assertions** | `AttributeError` raised on direct assignment. Event count in logger is unchanged. |
| **Failure Classification** | Runtime |
| **Status** | **PASS** |

---

### BLOCKER-007: AsRunEvent valid creation persists correctly

| Field | Value |
|---|---|
| **Invariant(s)** | INV-ASRUN-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | A valid AsRunEvent is created with all required fields. It persists in the logger and is queryable by broadcast day. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Create AsRunEvent via `log_playout_start()` with all fields populated. 2. Query `get_events_for_broadcast_day()`. |
| **Assertions** | Exactly one event returned. All fields match input values. `broadcast_day` is correct. |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### 6.2 SchedulePlan Tests

---

### SCHED-PLAN-001: Coverage gap is detected and faulted

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-FULL-COVERAGE-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID |
| **Scenario** | A plan is constructed with two zones leaving a known 2-hour gap. Validation is triggered. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed (coverage is a static structural check). |
| **Stimulus / Actions** | 1. Build a plan with Zone A covering [06:00, 18:00] and Zone B covering [20:00, 06:00+24h]. 2. Trigger plan validation. |
| **Assertions** | Validation raises a coverage fault. Fault identifies the uncovered interval [18:00, 20:00]. No ScheduleDay is generated. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### SCHED-PLAN-002: Full 24-hour coverage by multiple zones passes

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-FULL-COVERAGE-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID |
| **Scenario** | A plan is constructed with three adjacent zones that together cover [00:00, 24:00] with no gaps. Validation passes. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Build a plan with Zone A [06:00, 12:00], Zone B [12:00, 22:00], Zone C [22:00, 06:00+24h]. 2. Trigger plan validation. |
| **Assertions** | Validation succeeds. No coverage fault is raised. Plan is eligible for ScheduleDay generation. |
| **Failure Classification** | N/A (positive path) |

---

### SCHED-PLAN-003: Overlapping zones within the same plan are rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-NO-ZONE-OVERLAP-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID |
| **Scenario** | A plan contains two zones whose windows intersect. Validation detects the overlap. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Build a plan with Zone A [18:00, 22:00] (Mon–Sun) and Zone B [20:00, 24:00] (Mon–Sun). 2. Trigger plan validation. |
| **Assertions** | Validation raises an overlap fault. Fault identifies the overlapping interval [20:00, 22:00] and names both zone IDs. Plan save is rejected. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### SCHED-PLAN-004: Zones with non-overlapping day filters do not conflict

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-NO-ZONE-OVERLAP-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID |
| **Scenario** | Two zones have the same time window but different, mutually exclusive day-of-week filters. No overlap exists in practice. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Build a plan with Zone A [18:00, 22:00] (Mon–Fri) and Zone B [18:00, 22:00] (Sat–Sun). 2. Trigger plan validation. |
| **Assertions** | Validation succeeds. No overlap fault is raised. Plan is eligible for ScheduleDay generation. |
| **Failure Classification** | N/A (positive path) |

---

### SCHED-PLAN-005: Off-grid zone boundary is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A zone is created with a start time that falls between grid boundaries. Validation rejects it. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. Channel grid: `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Construct a zone with `start_time=18:15` against a 30-minute grid. 2. Trigger zone boundary validation. |
| **Assertions** | Validation raises a grid-alignment fault. Fault identifies 18:15 as invalid and reports 18:00 and 18:30 as the nearest valid boundaries. Zone creation is rejected. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### SCHED-PLAN-006: Grid-aligned zone boundary passes

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A zone is created with boundaries that exactly coincide with grid boundaries. Validation passes. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. Channel grid: `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Construct a zone with `start_time=18:00` and `end_time=18:30`. 2. Trigger zone boundary validation. |
| **Assertions** | Validation succeeds. No alignment fault is raised. Zone is accepted. |
| **Failure Classification** | N/A (positive path) |

---

### SCHED-PLAN-007: Ineligible asset is excluded at ScheduleDay generation time

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 |
| **Derived Law(s)** | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| **Scenario** | A zone references an `IneligibleAsset` (`state=enriching`). ScheduleDay generation detects the violation. |
| **Clock Setup** | Clock set to EPOCH (broadcast date D). |
| **Stimulus / Actions** | 1. Build a plan with a zone referencing `IneligibleAsset`. 2. Trigger ScheduleDay generation for date D. |
| **Assertions** | Generation raises an eligibility fault. `IneligibleAsset` is not present in the generated ScheduleDay slots. The fault record includes the asset ID and ineligibility reason (`state=enriching`). Fault class is "planning". |
| **Failure Classification** | Planning |

---

### SCHED-PLAN-008: Asset that becomes ineligible after plan creation is excluded at generation

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 |
| **Derived Law(s)** | LAW-ELIGIBILITY |
| **Scenario** | An asset is eligible at plan creation time but has its `approved_for_broadcast` revoked before ScheduleDay generation. The gate re-evaluates at generation time. |
| **Clock Setup** | Clock set to EPOCH. Advance to D-4 for plan creation. Advance to D-3 (generation trigger) after revoking approval. |
| **Stimulus / Actions** | 1. Create plan with `EligibleAsset`. 2. Advance clock to D-3. 3. Revoke `EligibleAsset.approved_for_broadcast=false`. 4. Trigger ScheduleDay generation. |
| **Assertions** | Generation detects the now-ineligible asset and excludes it. Fault record is created with fault class "runtime". No silent use of the ineligible asset occurs. |
| **Failure Classification** | Runtime |

---

### 6.3 ScheduleDay Tests

---

### SCHED-DAY-001: Duplicate ScheduleDay for same channel+date is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-ONE-PER-DATE-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-IMMUTABILITY |
| **Scenario** | A ScheduleDay for (channel C, date D) already exists. A second attempt to create one for the same pair is rejected. |
| **Clock Setup** | Clock set to EPOCH (date D). |
| **Stimulus / Actions** | 1. Materialize ScheduleDay for (C, D). 2. Attempt to insert a second ScheduleDay for the same (C, D) via the application layer. |
| **Assertions** | The second insert is rejected with a uniqueness fault. Exactly one ScheduleDay record exists for (C, D) after both attempts. Fault class is "planning". |
| **Failure Classification** | Planning |
| **Status** | **PASS** |

---

### SCHED-DAY-002: Force-regeneration replaces the ScheduleDay atomically

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-ONE-PER-DATE-001, INV-SCHEDULEDAY-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY, LAW-DERIVATION |
| **Scenario** | An operator triggers force-regeneration of a materialized ScheduleDay. The old record is replaced atomically by a new one. No intermediate state is visible. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Materialize ScheduleDay SD-OLD for (C, D). Record its ID. 2. Trigger force-regeneration for (C, D). 3. Read (C, D) from the store immediately after. |
| **Assertions** | Exactly one ScheduleDay record exists for (C, D). Its ID differs from SD-OLD.ID. No window during which zero records existed is observable from outside the transaction. Fault class: none (successful operation). |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### SCHED-DAY-003: In-place mutation of a materialized ScheduleDay is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | Code attempts to update a slot's wall-clock time directly on an existing ScheduleDay record. The application layer rejects the mutation. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Materialize ScheduleDay for (C, D). 2. Attempt to update a slot's `start_utc` field via the application layer (not via force-regen). |
| **Assertions** | The update is rejected before reaching the database. The original slot timing is unchanged after the attempt. Fault class is "runtime". |
| **Failure Classification** | Runtime |
| **Status** | **PASS** |

---

### SCHED-DAY-004: Operator manual override creates a new record with superseded reference

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | An operator applies a manual override to a ScheduleDay. The system creates a new ScheduleDay record with `is_manual_override=true`, preserving the original. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Materialize ScheduleDay SD-ORIG for (C, D). 2. Apply operator manual override targeting (C, D) with modified slot content. |
| **Assertions** | A new ScheduleDay record SD-OVERRIDE exists with `is_manual_override=true`. SD-OVERRIDE references SD-ORIG.ID as the superseded record. SD-ORIG is preserved in the store. Only one ScheduleDay with `is_manual_override=false` exists for (C, D). |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### SCHED-DAY-005: ScheduleDay generation with upstream plan gap raises gap fault

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-NO-GAPS-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-RUNTIME-AUTHORITY |
| **Scenario** | A plan with a known coverage gap (bypassing INV-PLAN-FULL-COVERAGE-001 via `empty=True` developer override) is used for ScheduleDay generation. The generation service catches the resulting gap. |
| **Clock Setup** | Clock set to EPOCH (broadcast date D). |
| **Stimulus / Actions** | 1. Build a plan using `empty=True` with zones covering only [06:00, 18:00]. 2. Trigger ScheduleDay generation for date D. |
| **Assertions** | Generation raises a gap fault identifying [18:00, 06:00+24h] as uncovered. No ScheduleDay record is committed. Fault class is "planning". |
| **Failure Classification** | Planning |
| **Status** | **PASS** |

---

### SCHED-DAY-006: ScheduleDay generation with full-coverage plan produces gap-free output

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-NO-GAPS-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-GRID |
| **Scenario** | A plan with full 24-hour zone coverage generates a ScheduleDay with no temporal gaps. |
| **Clock Setup** | Clock set to EPOCH (broadcast date D). |
| **Stimulus / Actions** | 1. Build a plan with full coverage zones (pass SCHED-PLAN-002 conditions). 2. Trigger ScheduleDay generation for date D. |
| **Assertions** | ScheduleDay is committed. Coverage validation finds no uncovered intervals within [06:00, 06:00+24h]. No gap fault is raised. |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### SCHED-DAY-007: Missing ScheduleDay at D-2 raises a lead-time violation

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-LEAD-TIME-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY |
| **Scenario** | No ScheduleDay exists for broadcast date D. Clock advances to D-2. HorizonManager evaluates and detects the lead-time shortfall. |
| **Clock Setup** | Clock set to D-2 at 06:00 (EPOCH + 96 hours). |
| **Stimulus / Actions** | 1. Ensure no ScheduleDay exists for date D. 2. Trigger HorizonManager evaluation at D-2. |
| **Assertions** | HorizonManager raises a lead-time violation. Violation record includes channel ID and the missing date D. HorizonManager triggers emergency generation or escalates. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### SCHED-DAY-008: ScheduleDay materialized at D-4 satisfies the lead-time invariant

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-LEAD-TIME-001 |
| **Derived Law(s)** | LAW-DERIVATION |
| **Scenario** | A ScheduleDay is generated at D-4. HorizonManager at D-2 confirms the invariant is satisfied. |
| **Clock Setup** | Clock starts at D-4 (EPOCH + 48 hours). Advance to D-2 after generation. |
| **Stimulus / Actions** | 1. Trigger ScheduleDay generation at D-4. 2. Advance clock to D-2. 3. Trigger HorizonManager evaluation. |
| **Assertions** | No lead-time violation is raised. HorizonManager health report shows (C, D) as compliant. |
| **Failure Classification** | N/A (positive path) |

---

### SCHED-DAY-009: ScheduleDay without plan reference is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| **Scenario** | Code attempts to insert a ScheduleDay with `plan_id=NULL` and `is_manual_override=false`. The application layer rejects it. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Attempt to insert a ScheduleDay record with `plan_id=NULL` and `is_manual_override=false` via the application layer. |
| **Assertions** | Insert is rejected. No record is committed. Fault identifies missing derivation anchor. Fault class is "planning". |
| **Failure Classification** | Planning |
| **Status** | **PASS** |

---

### SCHED-DAY-010: Manual override ScheduleDay must reference the superseded record

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-IMMUTABILITY |
| **Scenario** | An operator creates a manual override ScheduleDay. The record carries `is_manual_override=true` and references the original ScheduleDay ID it supersedes. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Materialize SD-ORIG for (C, D). 2. Create an override ScheduleDay referencing SD-ORIG.ID. |
| **Assertions** | Override record is accepted. `is_manual_override=true`. Superseded record reference is non-null and equals SD-ORIG.ID. Derivation chain traverses from override back to SD-ORIG. |
| **Failure Classification** | N/A (positive path) |
| **Status** | **PASS** |

---

### 6.4 ExecutionEntry Tests

---

### PLAYLOG-001: Ineligible asset in active window is replaced with filler at extension

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-ELIGIBLE-CONTENT-001 |
| **Derived Law(s)** | LAW-ELIGIBILITY, LAW-DERIVATION |
| **Scenario** | An ExecutionEntry exists referencing an asset that has since had its approval revoked. Rolling-window extension detects and replaces the entry. |
| **Clock Setup** | Clock set to EPOCH. Advance to T=EPOCH+1h to trigger window extension covering the affected entry. |
| **Stimulus / Actions** | 1. Create TransmissionLogEntry for `EligibleAsset` at T+2h. Derive ExecutionEntry from it. 2. Revoke `EligibleAsset.approved_for_broadcast=false`. 3. Advance clock to EPOCH+1h. Trigger rolling-window extension. |
| **Assertions** | ExecutionEntry at T+2h references filler, not the original asset. A violation record includes asset ID, channel ID, and reason `approved_for_broadcast=false`. Fault class is "runtime". |
| **Failure Classification** | Runtime |

---

### PLAYLOG-002: ExecutionEntry timestamps match the injected clock

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | ExecutionEntry generation is run with a known deterministic clock value. Output timestamps must match clock-derived offsets from the TransmissionLogEntry. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Create TransmissionLogEntry with `start_time=EPOCH+30min`, `end_time=EPOCH+60min`. 2. Run ExecutionEntry generation with injected clock at EPOCH. |
| **Assertions** | Generated ExecutionEntry has `start_utc_ms=EPOCH+30min` and `end_utc_ms=EPOCH+60min`. Timestamps are derived from the injected clock. |
| **Failure Classification** | N/A (positive path) |

---

### PLAYLOG-003: Different injected clocks produce different timestamps

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | Two generation runs with different injected clock values produce timestamps differing by the exact clock delta. |
| **Clock Setup** | Run A: clock at EPOCH. Run B: clock at EPOCH+24h. |
| **Stimulus / Actions** | 1. Generate ExecutionEntry with clock at EPOCH. Record timestamps. 2. Generate equivalent ExecutionEntry with clock at EPOCH+24h. Record timestamps. |
| **Assertions** | Run B timestamps are exactly 24 hours later than Run A timestamps. No shared state between runs contaminates the result. |
| **Failure Classification** | N/A (positive path) |

---

### PLAYLOG-004: Lookahead shortfall triggers window extension

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOOKAHEAD-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | ExecutionEntry sequence depth falls below `min_execution_hours`. HorizonManager detects the shortfall and extends. |
| **Clock Setup** | Clock set to T=EPOCH. ExecutionEntry sequence extends to EPOCH + `min_execution_hours` - 10min. |
| **Stimulus / Actions** | 1. Populate ExecutionEntry sequence ending at EPOCH + `min_execution_hours` - 10min. 2. Set clock to EPOCH. 3. Trigger HorizonManager lookahead evaluation. |
| **Assertions** | HorizonManager detects shortfall (`depth < min_execution_hours`). Extension is triggered. After extension, sequence extends to at least EPOCH + `min_execution_hours` with no gaps. Violation record emitted with depth shortfall in minutes. Fault class is "runtime". |
| **Failure Classification** | Runtime |

---

### PLAYLOG-005: Lookahead at exactly `min_execution_hours` is compliant

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOOKAHEAD-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | ExecutionEntry sequence ends exactly at T + `min_execution_hours`. No shortfall. No violation raised. |
| **Clock Setup** | Clock set to T=EPOCH. ExecutionEntry sequence ends at EPOCH + `min_execution_hours`. |
| **Stimulus / Actions** | 1. Populate ExecutionEntry sequence ending at EPOCH + `min_execution_hours`. 2. Trigger HorizonManager lookahead evaluation at EPOCH. |
| **Assertions** | No lookahead violation is raised. Health report shows channel as compliant. |
| **Failure Classification** | N/A (positive path) |

---

### PLAYLOG-006: Temporal gap in ExecutionEntry sequence is detected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-NO-GAPS-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | ExecutionEntry sequence has a 10-minute gap within the lookahead window. Continuity validation detects it. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Populate ExecutionEntry records for [EPOCH, EPOCH+1h] and [EPOCH+1h10m, EPOCH+`min_execution_hours`] — leaving a 10-minute gap at [EPOCH+1h, EPOCH+1h10m]. 2. Trigger continuity validation. |
| **Assertions** | Validation raises a gap fault identifying [EPOCH+1h, EPOCH+1h10m]. Fault includes channel ID and gap boundaries. HorizonManager attempts to fill the gap. No sequence with an unresolved gap is committed. Fault class is "runtime". |
| **Failure Classification** | Runtime |

---

### PLAYLOG-007: Gap in ExecutionEntry traces back to upstream ResolvedScheduleDay gap

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-NO-GAPS-001, INV-SCHEDULEDAY-NO-GAPS-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION |
| **Scenario** | A ResolvedScheduleDay was committed with a coverage gap. The resulting TransmissionLog has no entries for that window. The ExecutionEntry gap is traceable to the TransmissionLog gap, which is traceable to the ResolvedScheduleDay gap. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Manually insert a ResolvedScheduleDay with a gap at [EPOCH+2h, EPOCH+2h30m]. 2. Generate TransmissionLog from this ResolvedScheduleDay. 3. Generate ExecutionEntries from the TransmissionLog. 4. Trigger continuity validation. |
| **Assertions** | ExecutionEntry gap fault is raised. Traceability chain identifies: ExecutionEntry gap → TransmissionLog gap → ResolvedScheduleDay gap. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### PLAYLOG-008: ExecutionEntry without TransmissionLogEntry reference is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| **Scenario** | Code attempts to create an ExecutionEntry with no TransmissionLogEntry reference and no operator override record. The application layer rejects it. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Attempt to create an ExecutionEntry with `transmission_log_entry_id=NULL` and no override record. |
| **Assertions** | Creation is rejected. No record is committed. Fault identifies the missing derivation anchor. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### PLAYLOG-009: ExecutionEntry created by operator override is accepted without TransmissionLogEntry reference

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-IMMUTABILITY |
| **Scenario** | An operator creates an emergency override ExecutionEntry. It has no TransmissionLogEntry reference but carries a valid override record. It is accepted. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Create an operator override record authorizing substitution for (channel C, window [EPOCH+1h, EPOCH+1h30m]). 2. Create an ExecutionEntry referencing the override record, with `transmission_log_entry_id=NULL`. |
| **Assertions** | Creation is accepted. Override record reference is present and valid. ExecutionEntry is marked as an override. Derivation audit terminates at the override record (not a fault). |
| **Failure Classification** | N/A (positive path) |

---

### 6.5 ExecutionEntry Lock Window Tests

---

### PLAYLOG-IMMUT-001: Mutation of a locked ExecutionEntry without override record is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOCKED-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY |
| **Scenario** | An ExecutionEntry within the locked execution window is targeted for in-place mutation. No override record exists. The application layer rejects it. |
| **Clock Setup** | Clock set to EPOCH. Lock window: [EPOCH, EPOCH + `lock_window_depth`]. ExecutionEntry at [EPOCH+15m, EPOCH+45m] is within the lock window. |
| **Stimulus / Actions** | 1. Create ExecutionEntry EE at [EPOCH+15m, EPOCH+45m]. 2. Attempt in-place mutation of EE's asset reference without a prior override record. |
| **Assertions** | Mutation is rejected before reaching the database. EE content is unchanged. Violation record includes EE ID, mutation type, window status `"locked"`, and fault class `"runtime"`. |
| **Failure Classification** | Runtime |

---

### PLAYLOG-IMMUT-002: Mutation of a past-window ExecutionEntry is rejected unconditionally

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOCKED-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | An ExecutionEntry that has already been broadcast (its `end_utc_ms` is in the past) is targeted for mutation. Even with a valid override record, the mutation is rejected. Past-window entries are immutable without exception. |
| **Clock Setup** | Clock set to EPOCH + 2h (so EPOCH+30m to EPOCH+60m is in the past). |
| **Stimulus / Actions** | 1. Create ExecutionEntry EE at [EPOCH+30m, EPOCH+60m]. 2. Advance clock to EPOCH+2h (EE is now in past window). 3. Create an operator override record for EE. 4. Attempt mutation of EE referencing the override record. |
| **Assertions** | Mutation is rejected. Violation record includes EE ID, window status `"past"`, and fault class `"operator"`. Override record is present but does not exempt a past-window entry. |
| **Failure Classification** | Operator |

---

### PLAYLOG-IMMUT-003: Valid atomic override inside locked window is accepted

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOCKED-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY |
| **Scenario** | An operator performs a valid emergency override of a locked ExecutionEntry. The override record is persisted first; the ExecutionEntry update follows atomically. |
| **Clock Setup** | Clock set to EPOCH. Lock window: [EPOCH, EPOCH + `lock_window_depth`]. ExecutionEntry at [EPOCH+10m, EPOCH+40m]. |
| **Stimulus / Actions** | 1. Create ExecutionEntry EE at [EPOCH+10m, EPOCH+40m]. 2. Persist operator override record OR-1 targeting EE. 3. Update EE's asset reference to reference the override content, linked to OR-1. |
| **Assertions** | Override record OR-1 exists and is committed before EE is updated. EE update is accepted. EE's override record reference equals OR-1.ID. No window during which EE references new content without OR-1 being committed is observable. |
| **Failure Classification** | N/A (positive path) |

---

### 6.6 TransmissionLog Grid Alignment Tests

---

### PLAYLIST-GRID-001: Off-grid TransmissionLogEntry boundary is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | TransmissionLog generation produces an entry with `start_time=18:15` against a 30-minute grid. Validation detects and rejects the off-grid boundary. |
| **Clock Setup** | Clock set to EPOCH. Channel: `TestChannel` (30-min grid). |
| **Stimulus / Actions** | 1. Manually construct a TransmissionLogEntry with `start_time=18:15`. 2. Trigger TransmissionLog grid-alignment validation. |
| **Assertions** | Validation raises a grid-alignment fault. Fault identifies 18:15 as invalid. Nearest valid boundaries (18:00, 18:30) are reported. Entry is rejected. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### PLAYLIST-GRID-002: Programming-day-start boundary rollover aligns correctly

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A TransmissionLogEntry spans the `programming_day_start` boundary (e.g., 05:30 to 06:30 where `programming_day_start=06:00`). Both `start_time` and `end_time` must align to grid boundaries. The `programming_day_start` itself is a valid grid boundary. |
| **Clock Setup** | Clock set to EPOCH - 30min. Channel: `TestChannel` with `programming_day_start="06:00"` and `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Generate a TransmissionLogEntry spanning [05:30, 06:30] across the programming-day boundary. 2. Trigger validation. |
| **Assertions** | Both 05:30 and 06:30 are valid grid boundaries (on a 30-minute grid relative to `programming_day_start`). Validation passes. No fractional minutes appear. No sub-grid boundary is produced at the rollover point. |
| **Failure Classification** | N/A (positive path) |

---

### PLAYLIST-GRID-003: Cross-midnight boundary produces no hidden micro-gap

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | Two adjacent TransmissionLogEntries span across calendar midnight. The first entry ends at 00:00:00 and the second starts at 00:00:00. No gap exists at the midnight boundary. |
| **Clock Setup** | Clock set to EPOCH with `programming_day_start="06:00"`. Calendar midnight is internal to the broadcast day. |
| **Stimulus / Actions** | 1. Construct TransmissionLogEntry A with `end_time=00:00:00` and entry B with `start_time=00:00:00`. 2. Assert B.start_time == A.end_time (exact equality). 3. Trigger continuity validation on the sequence. |
| **Assertions** | No micro-gap exists at the midnight boundary. No fractional millisecond difference between A.end_time and B.start_time. Continuity validation finds no gap. Both boundaries are grid-aligned. |
| **Failure Classification** | N/A (positive path) |

---

### 6.7 Cross-Cutting Tests

---

### CROSS-001: Breakpoint-free program is not cut mid-play in the generated TransmissionLog

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-MID-PROGRAM-CUT-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-GRID |
| **Scenario** | A `LongformAsset` (90 minutes, no breakpoints) is placed in a zone covering [18:00, 22:00] against a 30-minute grid. TransmissionLog generation must not cut it mid-program. |
| **Clock Setup** | Clock set to EPOCH. Broadcast date D. |
| **Stimulus / Actions** | 1. Build a plan with a zone [18:00, 22:00] containing `LongformAsset` (90 minutes, `breakpoints=[]`). 2. Generate ResolvedScheduleDay and TransmissionLog for date D. |
| **Assertions** | TransmissionLog contains no cut-point within the 90-minute program. The program consumes 3 whole 30-minute grid blocks [18:00–19:30]. No TransmissionLogEntry boundary falls inside the program's duration. |
| **Failure Classification** | Planning (if violated) |

---

### CROSS-002: Breakpoint-free 120-minute longform spans 4 blocks without mid-cut

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-MID-PROGRAM-CUT-001 |
| **Derived Law(s)** | LAW-DERIVATION, LAW-GRID |
| **Scenario** | A 120-minute `LongformAsset` with no breakpoints is placed in a zone covering [20:00, 24:00]. TransmissionLog generation assigns it across 4 contiguous grid blocks. |
| **Clock Setup** | Clock set to EPOCH. Broadcast date D. Channel grid: 30-minute blocks. |
| **Stimulus / Actions** | 1. Build a plan with a zone [20:00, 24:00] containing a 120-minute `LongformAsset` with `breakpoints=[]`. 2. Generate TransmissionLog. |
| **Assertions** | TransmissionLog contains a single entry spanning [20:00, 00:00+24h]. No cut exists within the program boundary. Program consumes exactly 4 grid blocks. |
| **Failure Classification** | Planning (if violated) |

---

### CROSS-003: AsRun entry without ExecutionEntry reference is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-ASRUN-TRACEABILITY-001 |
| **Derived Law(s)** | LAW-DERIVATION |
| **Scenario** | An AsRun record is created with `execution_entry_id=NULL`. The application layer rejects it. |
| **Clock Setup** | Clock set to EPOCH. No advancement needed. |
| **Stimulus / Actions** | 1. Attempt to create an AsRun record with `execution_entry_id=NULL`. |
| **Assertions** | Creation is rejected. No record is committed. Fault identifies missing ExecutionEntry reference. Fault class is "runtime". |
| **Failure Classification** | Runtime |

---

### CROSS-004: AsRun chain is fully traversable to originating SchedulePlan

| Field | Value |
|---|---|
| **Invariant(s)** | INV-ASRUN-TRACEABILITY-001 |
| **Derived Law(s)** | LAW-DERIVATION |
| **Scenario** | A valid AsRun entry is created via the full constitutional chain. The complete chain from AsRun back to SchedulePlan is traversable. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Build plan SP. 2. Generate ResolvedScheduleDay SD (→ SP). 3. Generate TransmissionLogEntry TLE (→ SD). 4. Generate ExecutionEntry EE (→ TLE). 5. Create AsRun AR (→ EE). 6. Traverse: AR → EE → TLE → SD → SP. |
| **Assertions** | All five links are non-null. Chain terminates at SP without a broken node. Audit query returns no violation rows. |
| **Failure Classification** | N/A (positive path) |

---

### 6.8 Foreign Content Injection Tests

---

### CROSS-FOREIGN-001: ScheduleDay slot referencing an asset absent from the generating plan is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-FOREIGN-CONTENT-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| **Scenario** | A `ForeignAsset` (not referenced in any zone of the active SchedulePlan) is injected into a ScheduleDay slot during generation. The generation layer detects and rejects it. |
| **Clock Setup** | Clock set to EPOCH (broadcast date D). |
| **Stimulus / Actions** | 1. Build a plan with zones referencing only `EligibleAsset`. 2. Manually inject `ForeignAsset` into a ScheduleDay slot during the generation workflow (simulating a logic error). 3. Trigger generation-time asset validation. |
| **Assertions** | Validation raises a foreign-content fault. `ForeignAsset` ID is absent from the committed ScheduleDay. Fault record includes `ForeignAsset.id`, artifact type `ScheduleDay`, and the upstream authority checked (SchedulePlan ID). Fault class is "planning". |
| **Failure Classification** | Planning |

---

### CROSS-FOREIGN-002: TransmissionLogEntry referencing an asset absent from the source ResolvedScheduleDay is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-FOREIGN-CONTENT-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| **Scenario** | A `ForeignAsset` not present in the ResolvedScheduleDay is injected into a TransmissionLogEntry during TransmissionLog generation. The TransmissionLog layer detects it. |
| **Clock Setup** | Clock set to EPOCH (broadcast date D). |
| **Stimulus / Actions** | 1. Generate ResolvedScheduleDay SD with only `EligibleAsset`. 2. During TransmissionLog generation from SD, inject a TransmissionLogEntry referencing `ForeignAsset` (simulating a generation logic error). 3. Trigger TransmissionLog validation against SD. |
| **Assertions** | Validation raises a foreign-content fault identifying `ForeignAsset` as absent from SD. The TransmissionLogEntry is rejected. Fault class is "planning". |
| **Failure Classification** | Planning |

---

### CROSS-FOREIGN-003: ExecutionEntry referencing an asset absent from the source TransmissionLog is rejected

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-FOREIGN-CONTENT-001 |
| **Derived Law(s)** | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| **Scenario** | A `ForeignAsset` not present in any TransmissionLogEntry is injected into an ExecutionEntry during rolling-window extension. The ExecutionEntry layer detects it. |
| **Clock Setup** | Clock set to EPOCH. |
| **Stimulus / Actions** | 1. Generate TransmissionLog from ResolvedScheduleDay. TransmissionLog contains only `EligibleAsset`. 2. During ExecutionEntry generation, inject an entry referencing `ForeignAsset` (not present in any TransmissionLogEntry, no override record). 3. Trigger ExecutionEntry derivation validation. |
| **Assertions** | Validation raises a foreign-content fault. `ForeignAsset` ID is absent from the committed ExecutionEntry sequence. Fault record includes `ForeignAsset.id`, artifact type `ExecutionEntry`, and the TransmissionLogEntry set checked. Fault class is "runtime". |
| **Failure Classification** | Runtime |

---

### 6.9 Grid Boundary Stress Tests

---

### GRID-STRESS-001: programming_day_start boundary rollover produces grid-aligned ResolvedScheduleDay slots

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-GRID-ALIGNMENT-001, INV-SCHEDULEDAY-NO-GAPS-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A plan spans the `programming_day_start` boundary. ResolvedScheduleDay generation produces slots that align precisely at the rollover point with no fractional minutes and no micro-gap. |
| **Clock Setup** | Clock at EPOCH. Channel: `TestChannel` with `programming_day_start="06:00"`, `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Build a plan with Zone A [04:00, 06:00] and Zone B [06:00, 08:00]. 2. Generate ResolvedScheduleDay. 3. Inspect slot boundaries around 06:00. |
| **Assertions** | Zone A's last slot ends exactly at 06:00:00.000000. Zone B's first slot starts exactly at 06:00:00.000000. No fractional second difference exists between them. No micro-gap is present. Coverage validation passes. |
| **Failure Classification** | Planning (if violated) |

---

### GRID-STRESS-002: Calendar midnight wrap produces no fractional-minute boundary

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A TransmissionLogEntry straddles calendar midnight. The midnight boundary itself is a valid grid point (given a 30-minute grid aligned to hour 0). No fractional minutes appear at 00:00:00. |
| **Clock Setup** | Clock at EPOCH. Channel `TestChannel` with `programming_day_start="06:00"`. Calendar midnight (00:00) is mid-broadcast-day. |
| **Stimulus / Actions** | 1. Generate a TransmissionLogEntry ending at 00:00:00 and a subsequent entry starting at 00:00:00. 2. Verify both timestamps. |
| **Assertions** | End time is exactly 00:00:00. Start time is exactly 00:00:00. No fractional milliseconds. No gap between entries. Both timestamps are valid grid boundaries on a 30-minute grid. |
| **Failure Classification** | N/A (positive path) |

---

### GRID-STRESS-003: Zone spanning midnight has aligned boundaries on both sides

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-GRID-ALIGNMENT-001, INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A zone declared as [22:00, 02:00] spans calendar midnight. Both the pre-midnight boundary (22:00) and the post-midnight boundary (02:00) must be grid-aligned. The zone must produce TransmissionLogEntries with no sub-grid boundaries anywhere in the midnight-spanning window. |
| **Clock Setup** | Clock at EPOCH. Channel `TestChannel` with `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Define Zone [22:00, 02:00] (spans midnight). 2. Generate ResolvedScheduleDay and TransmissionLog for the zone. 3. Inspect all TransmissionLogEntry boundaries within [22:00, 02:00]. |
| **Assertions** | All TransmissionLogEntry boundaries within the zone are multiples of 30 minutes from any valid grid anchor. No boundary falls at a fractional minute. No boundary falls at a non-grid minute (e.g., 22:17). No micro-gap at 00:00. |
| **Failure Classification** | Planning (if violated) |

---

### GRID-STRESS-004: Longform asset spanning programming_day_start produces no off-grid fence

| Field | Value |
|---|---|
| **Invariant(s)** | INV-NO-MID-PROGRAM-CUT-001, INV-PLAYLIST-GRID-ALIGNMENT-001 |
| **Derived Law(s)** | LAW-GRID, LAW-DERIVATION |
| **Scenario** | A `LongformCrossDayAsset` starts at `programming_day_start - 60min` and runs 120 minutes, crossing the programming-day boundary. The program must not be cut at the boundary. Its start (carry-in) is at the prior broadcast day's grid; its end must be grid-aligned in the new day. |
| **Clock Setup** | Clock at EPOCH - 60min. Channel `TestChannel` with `programming_day_start="06:00"`, `grid_block_minutes=30`. |
| **Stimulus / Actions** | 1. Schedule `LongformCrossDayAsset` starting at 05:00 (programming_day_start - 60min). 2. Generate ResolvedScheduleDay and TransmissionLog for both broadcast days (Day-1 and Day-2). 3. Inspect TransmissionLogEntries spanning 05:00 to 07:00. |
| **Assertions** | No cut-point exists at 06:00 (programming_day_start). The program is represented as a contiguous entry (or a carry-in continuation) with no fence inside the program's duration. End time (07:00) is grid-aligned. No fractional boundaries in the Day-2 carry-in entry. |
| **Failure Classification** | Planning (if violated) |

---

### 6.10 Horizon Tests

---

### HORIZON-001: HorizonManager extension is triggered by clock progression, not consumer demand

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | FakeAdvancingClock advances continuously without any playout consumer activity. HorizonManager monitors the clock and triggers extension when depth falls below `min_execution_hours`. No consumer request initiates the extension. |
| **Clock Setup** | Clock starts at EPOCH. ExecutionEntry sequence initially extends to EPOCH + `min_execution_hours`. No consumer activity simulated. |
| **Stimulus / Actions** | 1. Initialize HorizonManager with injected `FakeAdvancingClock` and `min_execution_hours`. 2. Advance clock by `1 grid block` increments, each time triggering HorizonManager evaluation — without simulating any consumer content requests. 3. Record extension reason code on each triggered extension. |
| **Assertions** | Extension is triggered when remaining depth falls below `min_execution_hours`. Extension reason code is `"clock_progression"` on every triggered extension. No extension reason code is `"consumer_demand"` or any variant. The extension count increases in proportion to clock advancement. |
| **Failure Classification** | Runtime (if extension triggered by consumer demand) |

---

### HORIZON-002: No extension occurs when depth already satisfies `min_execution_hours`

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | ExecutionEntry sequence already extends beyond `min_execution_hours` from current clock time. HorizonManager evaluation confirms no extension is needed. No redundant extension cycle is triggered. |
| **Clock Setup** | Clock set to EPOCH. ExecutionEntry sequence extends to EPOCH + `min_execution_hours` + 1h (excess depth). |
| **Stimulus / Actions** | 1. Populate ExecutionEntry sequence to EPOCH + `min_execution_hours` + 1h. 2. Trigger HorizonManager evaluation at EPOCH. 3. Record extension attempt count before and after. |
| **Assertions** | Extension attempt count does not increase after evaluation. No extension cycle fires. HorizonManager health report shows depth = `min_execution_hours + 1h`, status compliant. |
| **Failure Classification** | N/A (positive path) |

---

## 7. Cross-Layer Constitutional Scenarios

---

### CONST-001: Full derivation chain integrity — Plan to AsRun

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001, INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001, INV-ASRUN-TRACEABILITY-001 |
| **Derived Law(s)** | LAW-DERIVATION |
| **Scenario** | A complete scheduling cycle is executed from plan creation through AsRun. Every artifact in the chain carries a non-null reference to its upstream authority. |
| **Clock Setup** | Clock starts at D-4 (EPOCH). Advance to D-3 (ResolvedScheduleDay), to D-1 (ExecutionEntry population), to D+0h30m (AsRun). |
| **Stimulus / Actions** | 1. Create SchedulePlan SP at D-4. 2. Generate ResolvedScheduleDay SD at D-3 (→ SP). 3. Generate TransmissionLog TL from SD at D-1. 4. Generate ExecutionEntries EE from TL. 5. Advance to D+0h30m. Create AsRun AR (→ EE). 6. Traverse: AR → EE → TL → SD → SP. |
| **Assertions** | All links are non-null. AR.execution_entry_id = EE.id. EE.transmission_log_entry_id = TL.id. TL.schedule_day_id = SD.id. SD.plan_id = SP.id. Audit query returns zero violation rows. |
| **Failure Classification** | Planning if any derivation link is absent. |

---

### CONST-002: Eligibility change mid-cycle — asset revoked between planning and execution

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001, INV-PLAYLOG-ELIGIBLE-CONTENT-001 |
| **Derived Law(s)** | LAW-ELIGIBILITY |
| **Scenario** | An asset is eligible at plan creation and ResolvedScheduleDay generation. Between ResolvedScheduleDay generation and ExecutionEntry window extension, its approval is revoked. The ExecutionEntry layer must detect this. The ResolvedScheduleDay is not retroactively altered (immutable). |
| **Clock Setup** | Clock at D-4 (plan), D-3 (ResolvedScheduleDay), D-1 (revocation), D (ExecutionEntry extension). |
| **Stimulus / Actions** | 1. Create plan with `EligibleAsset`. Generate ResolvedScheduleDay containing the asset. 2. Advance to D-1. Revoke `approved_for_broadcast=false`. 3. Advance to D. Trigger ExecutionEntry rolling-window extension for the asset's scheduled slot. |
| **Assertions** | ResolvedScheduleDay is unchanged (immutable — still contains the originally eligible asset). ExecutionEntry extension replaces the now-ineligible entry with filler. Violation record emitted: fault class "runtime". The ResolvedScheduleDay layer receives no notification and performs no action. |
| **Failure Classification** | Runtime (ExecutionEntry layer). |

---

### CONST-003: Immutability cascade — locked, past, and future window behavior under regeneration

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-IMMUTABLE-001, INV-PLAYLOG-LOCKED-IMMUTABLE-001, INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY, LAW-DERIVATION |
| **Scenario** | A force-regeneration is applied to a ResolvedScheduleDay during active broadcast. This scenario explicitly validates four immutability zones: (A) locked window entries are unchanged, (B) past window entries are unchanged, (C) future window entries may be replaced, (D) the transition at the lock boundary is atomic. |
| **Clock Setup** | Clock at D+1h (active broadcast). Locked window: [D, D + `lock_window_depth`]. Past window: before D. Future window: beyond D + `lock_window_depth`. |
| **Stimulus / Actions** | 1. Materialize ResolvedScheduleDay SD-OLD and generate ExecutionEntries EE-PAST (before D), EE-LOCKED (in lock window), EE-FUTURE (beyond lock window). 2. Trigger force-regeneration of SD-OLD → SD-NEW. 3. Generate new TransmissionLog and ExecutionEntries from SD-NEW for the future window only. 4. Attempt to mutate EE-LOCKED and EE-PAST directly. Observe EE-FUTURE. |
| **Assertions** | **(A) Locked window:** EE-LOCKED entries are unchanged after regeneration. Direct mutation of EE-LOCKED is rejected. **(B) Past window:** EE-PAST entries are unchanged. Direct mutation of EE-PAST is rejected unconditionally (no override exemption). **(C) Future window:** EE-FUTURE entries derived from SD-OLD may be replaced by new entries derived from SD-NEW. New entries for [D + `lock_window_depth`, D+6h] trace to SD-NEW (not SD-OLD). **(D) Lock boundary atomicity:** No window exists during which new future entries are visible before SD-NEW is fully committed. The transition at the lock boundary is a single atomic step. |
| **Failure Classification** | Runtime if locked/past entries are modified. Runtime if lock-boundary transition is non-atomic. |

---

### CONST-004: Runtime authority isolation — planning artifacts do not drive playout directly

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | The execution layer's content schedule is sourced exclusively from ExecutionEntry. Mutating the underlying TransmissionLogEntry after ExecutionEntries are generated does not alter the active playout plan. |
| **Clock Setup** | Clock at D+0h30m (active window). |
| **Stimulus / Actions** | 1. Generate ExecutionEntries EE for [D, D + `min_execution_hours`]. 2. Capture the content schedule visible to the execution layer. 3. Mutate the underlying TransmissionLogEntry's asset reference (simulating a post-derivation mutation). 4. Re-read the execution layer's content schedule. |
| **Assertions** | Execution layer content schedule is unchanged after the TransmissionLog mutation. It reflects ExecutionEntry content, not the mutated TransmissionLogEntry. ExecutionEntry record is the sole source driving execution. |
| **Failure Classification** | Runtime if execution layer reads from TransmissionLog directly. |

---

### CONST-005: Grid boundary cascade stress test — off-grid plan fault propagates at each layer

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAN-GRID-ALIGNMENT-001, INV-SCHEDULEDAY-NO-GAPS-001, INV-PLAYLOG-NO-GAPS-001 |
| **Derived Law(s)** | LAW-GRID |
| **Scenario** | A plan with an off-grid zone boundary (bypassing enforcement via developer override) cascades faults through ResolvedScheduleDay, TransmissionLog, and ExecutionEntry. Each layer independently detects and reports the violation. |
| **Clock Setup** | Clock at D-4. |
| **Stimulus / Actions** | 1. Build plan using `empty=True` with Zone A having `start_time=18:15` (off-grid on 30-min grid). 2. Attempt ResolvedScheduleDay generation. Force past the fault if needed. 3. Attempt TransmissionLog generation. Force past the fault if needed. 4. Attempt ExecutionEntry generation. |
| **Assertions** | Each layer independently detects and reports the grid-alignment violation. Violations at each layer identify the originating off-grid boundary (18:15) and fault class "planning". No silent propagation of an off-grid boundary from one layer to the next. |
| **Failure Classification** | Planning (at all layers — same root fault) |

---

### CONST-006: Operator override atomicity — override record must precede the override artifact

| Field | Value |
|---|---|
| **Invariant(s)** | INV-SCHEDULEDAY-IMMUTABLE-001, INV-PLAYLOG-LOCKED-IMMUTABLE-001 |
| **Derived Law(s)** | LAW-IMMUTABILITY |
| **Scenario** | An operator override for an ExecutionEntry is applied. The override record is persisted before the ExecutionEntry is updated. No window exists where the override content is active without a backing override record. |
| **Clock Setup** | Clock at D+0h45m (lock window active). |
| **Stimulus / Actions** | 1. Generate ExecutionEntries for [D, D + `min_execution_hours`]. 2. Begin operator override targeting EE at [D+1h, D+1h30m]. 3. Persist override record OR-1 first. 4. Update EE to reference OR-1's content. 5. Query the store at each step. |
| **Assertions** | At no point does EE reference override content without OR-1 being committed. Override record is committed first; EE update is committed second. If EE update fails, EE retains original content and OR-1 is rolled back or orphaned (but OR-1 must never be the sole committed record without a corresponding EE update). |
| **Failure Classification** | Runtime or Operator if the sequence is reversed or non-atomic. |

---

### CONST-007: Lookahead depth maintained gap-free over simulated 4-hour clock run

| Field | Value |
|---|---|
| **Invariant(s)** | INV-PLAYLOG-LOOKAHEAD-001, INV-PLAYLOG-NO-GAPS-001, INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 |
| **Derived Law(s)** | LAW-RUNTIME-AUTHORITY |
| **Scenario** | The clock advances in 30-minute increments over a simulated 4-hour period. At each step, the lookahead depth is evaluated. Extensions are triggered by clock progression (not consumer demand) when depth falls below `min_execution_hours`. The sequence must remain gap-free throughout. |
| **Clock Setup** | Clock starts at EPOCH. ExecutionEntry sequence initially extends to EPOCH + `min_execution_hours`. Advance in 30-minute increments, 8 steps total (simulating 4 hours of broadcast time). |
| **Stimulus / Actions** | For each 30-minute increment: 1. Advance clock by 30 minutes. 2. Trigger HorizonManager evaluation (no consumer demand simulated). 3. Assert depth >= `min_execution_hours`. 4. Assert no gaps in sequence. 5. Assert extension reason code is `"clock_progression"` if extension was triggered. |
| **Assertions** | After each of the 8 clock advances, depth remains >= `min_execution_hours`. No gaps appear at any point. All triggered extensions carry reason code `"clock_progression"`. No extension triggers with reason `"consumer_demand"`. Extension count equals or exceeds the number of 30-minute blocks consumed over 4 hours. No violation is raised at any step after extension completes. |
| **Failure Classification** | Runtime if depth falls below threshold without extension. Runtime if extensions triggered by consumer demand. |

---

## 8. Test ID Index

### Blocker Tests (Implemented)

| Test ID | Invariant(s) | Law(s) | Summary | Status |
|---|---|---|---|---|
| BLOCKER-001 | INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | LAW-DERIVATION, LAW-CONTENT-AUTHORITY | ExecutionEntry without lineage rejected | **PASS** |
| BLOCKER-002 | INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | LAW-DERIVATION, LAW-CONTENT-AUTHORITY | ExecutionEntry with valid lineage accepted | **PASS** |
| BLOCKER-003 | INV-DERIVATION-ANCHOR-PROTECTED-001 | LAW-DERIVATION, LAW-IMMUTABILITY | ResolvedScheduleDay delete with downstream rejected | **PASS** |
| BLOCKER-004 | INV-DERIVATION-ANCHOR-PROTECTED-001 | LAW-DERIVATION, LAW-IMMUTABILITY | ResolvedScheduleDay delete without downstream succeeds | **PASS** |
| BLOCKER-005 | INV-ASRUN-IMMUTABLE-001 | LAW-IMMUTABILITY | AsRunEvent rejects mutation; replace produces new instance | **PASS** |
| BLOCKER-006 | INV-ASRUN-IMMUTABLE-001 | LAW-IMMUTABILITY | AsRunEvent frozen dataclass prevents field reassignment | **PASS** |
| BLOCKER-007 | INV-ASRUN-IMMUTABLE-001 | LAW-IMMUTABILITY | AsRunEvent valid creation persists correctly | **PASS** |

### Full Matrix (Aspirational)

| Test ID | Invariant(s) | Law(s) | Summary |
|---|---|---|---|
| SCHED-PLAN-001 | INV-PLAN-FULL-COVERAGE-001 | LAW-CONTENT-AUTHORITY, LAW-GRID | Coverage gap detected and faulted |
| SCHED-PLAN-002 | INV-PLAN-FULL-COVERAGE-001 | LAW-CONTENT-AUTHORITY, LAW-GRID | Full 24h coverage by multiple zones passes |
| SCHED-PLAN-003 | INV-PLAN-NO-ZONE-OVERLAP-001 | LAW-CONTENT-AUTHORITY, LAW-GRID | Overlapping zones rejected |
| SCHED-PLAN-004 | INV-PLAN-NO-ZONE-OVERLAP-001 | LAW-CONTENT-AUTHORITY, LAW-GRID | Non-overlapping day-filtered zones pass |
| SCHED-PLAN-005 | INV-PLAN-GRID-ALIGNMENT-001 | LAW-GRID | Off-grid zone boundary rejected |
| SCHED-PLAN-006 | INV-PLAN-GRID-ALIGNMENT-001 | LAW-GRID | Grid-aligned zone boundary passes |
| SCHED-PLAN-007 | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY | Ineligible asset excluded at generation |
| SCHED-PLAN-008 | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | LAW-ELIGIBILITY | Asset revoked after plan creation excluded |
| SCHED-DAY-001 | INV-SCHEDULEDAY-ONE-PER-DATE-001 | LAW-DERIVATION, LAW-IMMUTABILITY | Duplicate ScheduleDay rejected |
| SCHED-DAY-002 | INV-SCHEDULEDAY-ONE-PER-DATE-001, INV-SCHEDULEDAY-IMMUTABLE-001 | LAW-IMMUTABILITY, LAW-DERIVATION | Force-regen replaces atomically |
| SCHED-DAY-003 | INV-SCHEDULEDAY-IMMUTABLE-001 | LAW-IMMUTABILITY | In-place mutation rejected |
| SCHED-DAY-004 | INV-SCHEDULEDAY-IMMUTABLE-001 | LAW-IMMUTABILITY | Manual override creates new record with ref |
| SCHED-DAY-005 | INV-SCHEDULEDAY-NO-GAPS-001 | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-RUNTIME-AUTHORITY | ScheduleDay generation with plan gap raises fault |
| SCHED-DAY-006 | INV-SCHEDULEDAY-NO-GAPS-001 | LAW-CONTENT-AUTHORITY, LAW-GRID | Full-coverage plan generates gap-free day |
| SCHED-DAY-007 | INV-SCHEDULEDAY-LEAD-TIME-001 | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY | Missing ScheduleDay at D-2 raises violation |
| SCHED-DAY-008 | INV-SCHEDULEDAY-LEAD-TIME-001 | LAW-DERIVATION | ScheduleDay at D-4 satisfies lead time |
| SCHED-DAY-009 | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | LAW-DERIVATION, LAW-CONTENT-AUTHORITY | Unanchored ScheduleDay rejected |
| SCHED-DAY-010 | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | LAW-DERIVATION, LAW-IMMUTABILITY | Override ScheduleDay references superseded record |
| PLAYLOG-001 | INV-PLAYLOG-ELIGIBLE-CONTENT-001 | LAW-ELIGIBILITY, LAW-DERIVATION | Ineligible asset replaced at window extension |
| PLAYLOG-002 | INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 | LAW-RUNTIME-AUTHORITY | ExecutionEntry timestamps match injected clock |
| PLAYLOG-003 | INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 | LAW-RUNTIME-AUTHORITY | Different injected clocks produce different timestamps |
| PLAYLOG-004 | INV-PLAYLOG-LOOKAHEAD-001 | LAW-RUNTIME-AUTHORITY | Lookahead shortfall (< min_execution_hours) triggers extension |
| PLAYLOG-005 | INV-PLAYLOG-LOOKAHEAD-001 | LAW-RUNTIME-AUTHORITY | Depth at exactly min_execution_hours is compliant |
| PLAYLOG-006 | INV-PLAYLOG-NO-GAPS-001 | LAW-RUNTIME-AUTHORITY | Gap in ExecutionEntry sequence detected and faulted |
| PLAYLOG-007 | INV-PLAYLOG-NO-GAPS-001, INV-SCHEDULEDAY-NO-GAPS-001 | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION | ExecutionEntry gap traced to upstream ResolvedScheduleDay gap |
| PLAYLOG-008 | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY | Unanchored ExecutionEntry rejected |
| PLAYLOG-009 | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | LAW-DERIVATION, LAW-IMMUTABILITY | Override ExecutionEntry accepted without TransmissionLogEntry ref |
| PLAYLOG-IMMUT-001 | INV-PLAYLOG-LOCKED-IMMUTABLE-001 | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY | Locked ExecutionEntry mutation without override rejected |
| PLAYLOG-IMMUT-002 | INV-PLAYLOG-LOCKED-IMMUTABLE-001 | LAW-IMMUTABILITY | Past-window ExecutionEntry mutation rejected unconditionally |
| PLAYLOG-IMMUT-003 | INV-PLAYLOG-LOCKED-IMMUTABLE-001 | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY | Valid atomic override inside locked window accepted |
| PLAYLIST-GRID-001 | INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID | Off-grid TransmissionLogEntry boundary rejected |
| PLAYLIST-GRID-002 | INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID | programming_day_start rollover alignment passes |
| PLAYLIST-GRID-003 | INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID | Cross-midnight entry has no hidden micro-gap |
| CROSS-001 | INV-NO-MID-PROGRAM-CUT-001 | LAW-DERIVATION, LAW-GRID | Breakpoint-free program not cut in TransmissionLog |
| CROSS-002 | INV-NO-MID-PROGRAM-CUT-001 | LAW-DERIVATION, LAW-GRID | 120-min longform spans 4 blocks without mid-cut |
| CROSS-003 | INV-ASRUN-TRACEABILITY-001 | LAW-DERIVATION | AsRun without ExecutionEntry ref rejected |
| CROSS-004 | INV-ASRUN-TRACEABILITY-001 | LAW-DERIVATION | Full chain traversable Plan→ResolvedScheduleDay→TransmissionLog→ExecutionEntry→AsRun |
| CROSS-FOREIGN-001 | INV-NO-FOREIGN-CONTENT-001 | LAW-CONTENT-AUTHORITY, LAW-DERIVATION | ResolvedScheduleDay slot with foreign asset rejected |
| CROSS-FOREIGN-002 | INV-NO-FOREIGN-CONTENT-001 | LAW-CONTENT-AUTHORITY, LAW-DERIVATION | TransmissionLogEntry with foreign asset rejected |
| CROSS-FOREIGN-003 | INV-NO-FOREIGN-CONTENT-001 | LAW-CONTENT-AUTHORITY, LAW-DERIVATION | ExecutionEntry with foreign asset rejected |
| GRID-STRESS-001 | INV-PLAN-GRID-ALIGNMENT-001, INV-SCHEDULEDAY-NO-GAPS-001 | LAW-GRID | programming_day_start rollover produces aligned boundary |
| GRID-STRESS-002 | INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID | Calendar midnight produces no fractional-minute boundary |
| GRID-STRESS-003 | INV-PLAN-GRID-ALIGNMENT-001, INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID | Zone spanning midnight has aligned boundaries on both sides |
| GRID-STRESS-004 | INV-NO-MID-PROGRAM-CUT-001, INV-PLAYLIST-GRID-ALIGNMENT-001 | LAW-GRID, LAW-DERIVATION | Longform spanning programming_day_start produces no off-grid fence |
| HORIZON-001 | INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 | LAW-RUNTIME-AUTHORITY | Extension triggered by clock progression only |
| HORIZON-002 | INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 | LAW-RUNTIME-AUTHORITY | No extension when depth >= min_execution_hours |
| CONST-001 | INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001, INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001, INV-ASRUN-TRACEABILITY-001 | LAW-DERIVATION | Full derivation chain integrity Plan→ResolvedScheduleDay→TransmissionLog→ExecutionEntry→AsRun |
| CONST-002 | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001, INV-PLAYLOG-ELIGIBLE-CONTENT-001 | LAW-ELIGIBILITY | Eligibility change mid-cycle propagation |
| CONST-003 | INV-SCHEDULEDAY-IMMUTABLE-001, INV-PLAYLOG-LOCKED-IMMUTABLE-001, INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | LAW-IMMUTABILITY, LAW-DERIVATION | Immutability cascade: locked / past / future / atomic boundary |
| CONST-004 | INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | LAW-RUNTIME-AUTHORITY | Planning artifacts do not drive playout directly |
| CONST-005 | INV-PLAN-GRID-ALIGNMENT-001, INV-SCHEDULEDAY-NO-GAPS-001, INV-PLAYLOG-NO-GAPS-001 | LAW-GRID | Off-grid fault cascades independently at every layer |
| CONST-006 | INV-SCHEDULEDAY-IMMUTABLE-001, INV-PLAYLOG-LOCKED-IMMUTABLE-001 | LAW-IMMUTABILITY | Override record persisted before override artifact |
| CONST-007 | INV-PLAYLOG-LOOKAHEAD-001, INV-PLAYLOG-NO-GAPS-001, INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 | LAW-RUNTIME-AUTHORITY | Lookahead gap-free over 4h deterministic clock run |
| CROSSDAY-001 | INV-PLAYLOG-CROSSDAY-NOT-SPLIT-001 | LAW-RUNTIME-AUTHORITY, LAW-IMMUTABILITY | PlaylogEvent spanning 06:00 boundary persists as single record |
| CROSSDAY-002 | INV-PLAYLOG-CROSSDAY-NOT-SPLIT-001 | LAW-RUNTIME-AUTHORITY, LAW-IMMUTABILITY | AsRun record not duplicated for cross-boundary PlaylogEvent |
| CROSSDAY-003 | INV-PLAYLOG-CROSSDAY-NOT-SPLIT-001 | LAW-IMMUTABILITY | Day-close operation does not mutate committed cross-boundary PlaylogEvent |
| CROSSDAY-004 | INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY | Broadcast-day row for ending day references source PlaylogEvent ID |
| CROSSDAY-005 | INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY | Broadcast-day row for starting day references same source PlaylogEvent ID |
| CROSSDAY-006 | INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 | LAW-DERIVATION | Projection row with null source record ID rejected |
| CROSSDAY-007 | INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 | LAW-DERIVATION | Projection row interval not subset of source record interval rejected |
| CROSSDAY-008 | INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | LAW-GRID, LAW-DERIVATION | Tuesday slot starting at 06:00 rejected when Monday carry-in ends at 07:00 |
| CROSSDAY-009 | INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | LAW-GRID, LAW-DERIVATION | Tuesday first slot correctly opens at carry-in end_utc |
| CROSSDAY-010 | INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | LAW-DERIVATION | Carry-in slot ID appears only in Monday ScheduleDay, not duplicated in Tuesday |
| CROSSDAY-011 | INV-PLAYLOG-CONTINUITY-SINGLE-AUTHORITY-AT-TIME-001 | LAW-RUNTIME-AUTHORITY | Single PlaylogEvent returned for every instant within cross-boundary interval |
| CROSSDAY-012 | INV-PLAYLOG-CONTINUITY-SINGLE-AUTHORITY-AT-TIME-001 | LAW-RUNTIME-AUTHORITY | Two PlaylogEvents covering overlapping 06:00–06:30 interval rejected |
| CROSSDAY-013 | INV-PLAYLOG-CONTINUITY-SINGLE-AUTHORITY-AT-TIME-001, INV-PLAYLOG-CROSSDAY-NOT-SPLIT-001 | LAW-RUNTIME-AUTHORITY, LAW-IMMUTABILITY | Boundary event does not produce dual authority at DAY_BOUNDARY instant |
