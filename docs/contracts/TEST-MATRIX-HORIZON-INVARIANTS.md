# Test Matrix: Horizon Invariants

**Scope:** Deterministic-clock validation of all invariants created from ScheduleHorizonManagementContract_v0.1.

**Test file:** `pkg/core/tests/contracts/runtime/test_horizon_invariants.py`

**Clock:** `FakeAdvancingClock` via `contract_clock` fixture. No `time.sleep`. All time progression via `contract_clock.advance_ms()`. Current time read via `contract_clock.now_utc_ms()`.

**Marker:** `@pytest.mark.contract`

---

## Fixtures and Test Doubles

### Clock

`FakeAdvancingClock` (from `conftest.py`). Initial time anchored to a fixed UTC epoch `EPOCH_MS` = 1,738,987,200,000 ms (2025-02-08T06:00:00Z, programming day start). All time reads via `contract_clock.now_utc_ms() -> int`.

### Horizon Manager Instrumentation

Every test MUST use a `HorizonManager` instance exposing:

| Observable | Type | Purpose |
|---|---|---|
| `horizon_manager.evaluate_once()` | method | Runs one extension evaluation cycle |
| `horizon_manager.health_report()` | `-> HorizonHealthReport` | Returns current compliance state |
| `horizon_manager.last_extension_reason_code` | `str` | Reason code of most recent extension attempt |
| `horizon_manager.extension_attempt_count` | `int` | Total extension attempts since init |
| `horizon_manager.extension_success_count` | `int` | Successful extensions since init |
| `horizon_manager.extension_forbidden_trigger_count` | `int` | Forbidden-trigger attempts intercepted since init |
| `horizon_manager.extension_attempt_log` | `list[ExtensionAttempt]` | Full log of all extension attempts |

`ExtensionAttempt` fields:

| Field | Type | Constraint |
|---|---|---|
| `attempt_id` | `str` | Unique per attempt |
| `now_utc_ms` | `int` | `contract_clock.now_utc_ms()` at time of attempt |
| `window_end_before_ms` | `int` | `execution_store.get_window_end_utc_ms()` before attempt |
| `window_end_after_ms` | `int` | `execution_store.get_window_end_utc_ms()` after attempt |
| `reason_code` | `str` | One of: `"REASON_TIME_THRESHOLD"`, `"DAILY_ROLL"`, `"REASON_OPERATOR_OVERRIDE"` |
| `triggered_by` | `str` | MUST always be `"SCHED_MGR_POLICY"` for allowed extensions |
| `success` | `bool` | Whether extension produced new entries |
| `error_code` | `str\|None` | Pipeline error code on failure, `None` on success |

### Execution Window Store

`InMemoryExecutionWindowStore` implementing snapshot-read semantics:

| Method | Signature | Semantics |
|---|---|---|
| `read_window_snapshot` | `(start_utc_ms: int, end_utc_ms: int) -> WindowSnapshot` | Returns all entries in range; all entries MUST share one `generation_id` |
| `get_window_end_utc_ms` | `() -> int` | `end_utc_ms` of farthest entry |
| `get_entry_at_utc_ms` | `(t: int) -> ExecutionEntry\|None` | Entry covering time `t` |
| `get_next_entry_after_utc_ms` | `(t: int) -> ExecutionEntry\|None` | First entry with `start_utc_ms > t` |
| `locked_window_end_utc_ms` | `(now_utc_ms: int) -> int` | Returns `now_utc_ms + LOCKED_WINDOW_MS` |
| `mutate_entry_in_place` | `(entry_id: str, patch: dict) -> MutationResult` | In-place field mutation; MUST fail inside locked window |
| `publish_atomic_replace` | `(range_start_ms, range_end_ms, new_entries, generation_id, reason_code, operator_override) -> PublishResult` | Atomic batch replace |

`WindowSnapshot` fields: `generation_id: int`, `entries: list[ExecutionEntry]`.

`ExecutionEntry` fields: `entry_id: str`, `start_utc_ms: int`, `end_utc_ms: int`, `generation_id: int`, `block_index: int`, `block_id: str`.

`MutationResult` fields: `ok: bool`, `error_code: str|None`.

`PublishResult` fields: `ok: bool`, `published_generation_id: int`, `error_code: str|None`.

### Channel Timeline

| Callable | Signature |
|---|---|
| `timeline.compute_position` | `(now_utc_ms: int, channel_epoch_utc_ms: int, snapshot: WindowSnapshot) -> ChannelPosition` |

`ChannelPosition` fields: `block_id: str`, `block_index: int`, `block_start_utc_ms: int`, `offset_ms: int`.

The `snapshot` parameter is a `WindowSnapshot` as returned by `execution_store.read_window_snapshot()`. This is the sole snapshot type in the matrix.

### Other Doubles

| Double | Purpose |
|---|---|
| `FakeScheduleService` | Deterministic grid-aligned block generation. Configurable `block_duration_ms`. |
| `StubPlanningPipeline` | Returns pre-built execution data for `extend_execution_day()`. Configurable to simulate failure via `error_code`. |

### Constants

| Symbol | Value | Notes |
|---|---|---|
| `BLOCK_DUR_MS` | 1,800,000 | 30-minute grid block |
| `MIN_EXEC_HORIZON_MS` | 21,600,000 | 6-hour minimum execution horizon depth |
| `EXTEND_WATERMARK_MS` | 10,800,000 | 3-hour watermark; extend when `get_window_end_utc_ms() - now_utc_ms <= EXTEND_WATERMARK_MS` |
| `LOCKED_WINDOW_MS` | 7,200,000 | 2-hour locked window; locked region is `[now, now + LOCKED_WINDOW_MS)`; MUST be `<= MIN_EXEC_HORIZON_MS` |
| `MIN_EPG_DAYS` | 3 | Minimum EPG coverage |
| `DAY_MS` | 86,400,000 | 24 hours |
| `EPOCH_MS` | 1,738,987,200,000 | 2025-02-08T06:00:00Z (programming day start) |
| `PROG_DAY_START_HOUR` | 6 | Programming day begins at 06:00 |

### Policy Semantics (enforced by all tests)

1. Extension is ONLY allowed when `reason_code` in `{"REASON_TIME_THRESHOLD", "DAILY_ROLL", "REASON_OPERATOR_OVERRIDE"}` and `triggered_by == "SCHED_MGR_POLICY"`.
2. Any extension attempt from a consumer path MUST increment `extension_forbidden_trigger_count` with one of: `"CONSUMER_READ"`, `"TUNE_IN"`, `"BLOCK_COMPLETED"`, `"ATTACH_STREAM"`, `"START_SESSION"`.
3. `execution_store.read_window_snapshot(start, end)` MUST return a `WindowSnapshot` where `snapshot.generation_id` matches every `entry.generation_id` in `snapshot.entries`.
4. At any fence time `F` where current entry ends: `get_next_entry_after_utc_ms(F - 1)` MUST be non-`None` and MUST satisfy `next.start_utc_ms == current.end_utc_ms`.
5. Any in-place mutation inside `[now, now + LOCKED_WINDOW_MS)` MUST return `ok=False` with `error_code="LOCKED_IMMUTABLE"`. Only `publish_atomic_replace` with `operator_override=True` may change locked data, and it is all-or-nothing.
6. `ChannelPosition.offset_ms` MUST equal `now_utc_ms - block_start_utc_ms`. Restarts and viewer absence MUST NOT change computed position for the same `now_utc_ms`.
7. `generation_id` values assigned by `publish_atomic_replace` MUST be monotonically increasing. `PublishResult.published_generation_id` MUST equal the `generation_id` argument passed to the call.

---

## INV-HORIZON-PROACTIVE-EXTEND-001

> Horizon extension is triggered exclusively by authoritative time crossing a defined threshold.

### THPE-001: Extension triggers when clock crosses watermark boundary

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Clock advances to exactly cross the `EXTEND_WATERMARK_MS` boundary; no ChannelManager activity. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate execution horizon covering `[EPOCH_MS, EPOCH_MS + MIN_EXEC_HORIZON_MS)` with `generation_id=1`. |
| **Actions** | 1. Let `T_cross = (EPOCH_MS + MIN_EXEC_HORIZON_MS) - EXTEND_WATERMARK_MS`. 2. `contract_clock.advance_ms(T_cross - EPOCH_MS)` — clock is now at exact watermark crossing. 3. Assert `execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms() == EXTEND_WATERMARK_MS`. 4. `horizon_manager.evaluate_once()`. |
| **Assertions** | `horizon_manager.extension_attempt_count == 1`. `horizon_manager.extension_success_count == 1`. `horizon_manager.last_extension_reason_code == "REASON_TIME_THRESHOLD"`. `horizon_manager.extension_attempt_log[-1].triggered_by == "SCHED_MGR_POLICY"`. `horizon_manager.extension_attempt_log[-1].window_end_after_ms > horizon_manager.extension_attempt_log[-1].window_end_before_ms`. `horizon_manager.extension_forbidden_trigger_count == 0`. `execution_store.get_window_end_utc_ms() > EPOCH_MS + MIN_EXEC_HORIZON_MS`. |
| **Failure mode** | Extension did not fire at watermark crossing; or `reason_code` is not `"REASON_TIME_THRESHOLD"`; or `triggered_by` is not `"SCHED_MGR_POLICY"`. |

### THPE-002: ChannelManager read produces no extension side-effects

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | ChannelManager reads current block. No extension state changes. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record baselines: `W_before = execution_store.get_window_end_utc_ms()`. `C_before = horizon_manager.extension_attempt_count`. `L_before = len(horizon_manager.extension_attempt_log)`. `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. `execution_store.get_entry_at_utc_ms(contract_clock.now_utc_ms())` — consumer read. 2. `contract_clock.advance_ms(1)`. 3. `horizon_manager.evaluate_once()` — watermark not crossed, no extension. |
| **Assertions** | `execution_store.get_window_end_utc_ms() == W_before`. `horizon_manager.extension_attempt_count == C_before`. `len(horizon_manager.extension_attempt_log) == L_before`. `horizon_manager.extension_forbidden_trigger_count == F_before`. |
| **Failure mode** | Any of `W_before`, `C_before`, `L_before`, or `F_before` changed after consumer read. |

### THPE-003: Viewer tune-in produces no extension side-effects

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Simulated viewer tune-in event fires. No extension state changes. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record baselines: `W_before = execution_store.get_window_end_utc_ms()`. `C_before = horizon_manager.extension_attempt_count`. `L_before = len(horizon_manager.extension_attempt_log)`. `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. Emit simulated viewer tune-in event. 2. `horizon_manager.evaluate_once()` — watermark not crossed, no extension. |
| **Assertions** | `execution_store.get_window_end_utc_ms() == W_before`. `horizon_manager.extension_attempt_count == C_before`. `len(horizon_manager.extension_attempt_log) == L_before`. `horizon_manager.extension_forbidden_trigger_count == F_before`. |
| **Failure mode** | Any baseline value changed after tune-in event. |

### THPE-004: BlockCompleted produces no extension side-effects

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | `BlockCompleted` event fires for first block. No extension state changes. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record baselines: `W_before = execution_store.get_window_end_utc_ms()`. `C_before = horizon_manager.extension_attempt_count`. `L_before = len(horizon_manager.extension_attempt_log)`. `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. Emit `BlockCompleted` event for block at `EPOCH_MS`. 2. `horizon_manager.evaluate_once()` — watermark not crossed, no extension. |
| **Assertions** | `execution_store.get_window_end_utc_ms() == W_before`. `horizon_manager.extension_attempt_count == C_before`. `len(horizon_manager.extension_attempt_log) == L_before`. `horizon_manager.extension_forbidden_trigger_count == F_before`. |
| **Failure mode** | Any baseline value changed after `BlockCompleted` event. |

### THPE-005: No duplicate extension at same clock value

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Multiple `evaluate_once()` calls at same `contract_clock.now_utc_ms()` produce exactly one extension. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate coverage. Advance clock to watermark crossing: `contract_clock.advance_ms((EPOCH_MS + MIN_EXEC_HORIZON_MS) - EXTEND_WATERMARK_MS - EPOCH_MS)`. |
| **Actions** | 1. `horizon_manager.evaluate_once()` — extension fires. Record `C1 = horizon_manager.extension_attempt_count`. Record `W1 = execution_store.get_window_end_utc_ms()`. Record `L1 = len(horizon_manager.extension_attempt_log)`. 2. `horizon_manager.evaluate_once()` again without advancing clock. Record `C2 = horizon_manager.extension_attempt_count`. Record `W2 = execution_store.get_window_end_utc_ms()`. Record `L2 = len(horizon_manager.extension_attempt_log)`. |
| **Assertions** | `C2 == C1`. `W2 == W1`. `L2 == L1`. No duplicate attempt for same `now_utc_ms`. |
| **Failure mode** | `C2 > C1`; or `W2 != W1`; or `L2 != L1`. |

---

## INV-HORIZON-EXECUTION-MIN-001

> `execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms() >= MIN_EXEC_HORIZON_MS` at every successful evaluation exit.

### THEM-001: Horizon meets minimum after initialization

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-EXECUTION-MIN-001` |
| **Scenario** | Fresh system start. Horizon manager initializes and extends. |
| **Clock setup** | Start at `EPOCH_MS`. Empty execution store (`get_window_end_utc_ms() == 0`). |
| **Actions** | 1. `horizon_manager.evaluate_once()`. |
| **Assertions** | `execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms() >= MIN_EXEC_HORIZON_MS`. `horizon_manager.health_report().execution_compliant == True`. `horizon_manager.extension_success_count >= 1`. `horizon_manager.extension_attempt_log[-1].reason_code == "REASON_TIME_THRESHOLD"`. `horizon_manager.extension_attempt_log[-1].success == True`. |
| **Failure mode** | Depth after initialization is less than `MIN_EXEC_HORIZON_MS`; or `health_report().execution_compliant == False`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` |
| **Status** | **PASS** |

### THEM-002: Horizon depth maintained across 24-hour progression

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-EXECUTION-MIN-001` |
| **Scenario** | Clock advances through full 24-hour broadcast day in `BLOCK_DUR_MS` steps. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon via `evaluate_once()` to minimum depth. |
| **Actions** | For each of 48 steps `i` in `0..47`: 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 2. `horizon_manager.evaluate_once()`. 3. `depth = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. 4. `report = horizon_manager.health_report()`. |
| **Assertions** | At every step: `depth >= MIN_EXEC_HORIZON_MS`. At every step: `report.execution_compliant == True`. `horizon_manager.extension_forbidden_trigger_count == 0` at end of walk. Every entry in `horizon_manager.extension_attempt_log` has `triggered_by == "SCHED_MGR_POLICY"`. |
| **Failure mode** | `depth < MIN_EXEC_HORIZON_MS` at any step; or `execution_compliant == False` at any step. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` |
| **Status** | **PASS** |

### THEM-003: Violation detected when pipeline fails

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-EXECUTION-MIN-001` |
| **Scenario** | Planning pipeline returns failure. Horizon cannot extend. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon to exactly `MIN_EXEC_HORIZON_MS`. |
| **Actions** | 1. Configure `StubPlanningPipeline` to return `error_code="PIPELINE_EXHAUSTED"` on next call. 2. `contract_clock.advance_ms(2 * BLOCK_DUR_MS)`. 3. `horizon_manager.evaluate_once()`. |
| **Assertions** | `horizon_manager.health_report().execution_compliant == False`. `execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms() < MIN_EXEC_HORIZON_MS`. `horizon_manager.extension_attempt_log[-1].success == False`. `horizon_manager.extension_attempt_log[-1].error_code == "PIPELINE_EXHAUSTED"`. `horizon_manager.extension_success_count` unchanged from before the failed attempt. |
| **Failure mode** | `execution_compliant` remains `True` despite deficit; or failed attempt not logged with `error_code`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` |
| **Status** | **PASS** |

### THEM-004: Horizon survives programming day boundary

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-EXECUTION-MIN-001` |
| **Scenario** | Clock advances from 05:00 to 07:00, crossing `PROG_DAY_START_HOUR` boundary at 06:00. |
| **Clock setup** | Start at `EPOCH_MS - 3_600_000` (05:00 UTC). Initialize horizon via `evaluate_once()`. |
| **Actions** | For 4 steps across boundary: 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 2. `horizon_manager.evaluate_once()`. 3. `depth = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. |
| **Assertions** | `depth >= MIN_EXEC_HORIZON_MS` at every step including the step that crosses 06:00. `horizon_manager.health_report().execution_compliant == True` at every step. Every entry in `horizon_manager.extension_attempt_log` has `triggered_by == "SCHED_MGR_POLICY"` and `reason_code` in `{"REASON_TIME_THRESHOLD", "DAILY_ROLL"}`. |
| **Failure mode** | Depth drops below `MIN_EXEC_HORIZON_MS` at the programming day boundary crossing. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_execution_min.py` |
| **Status** | **PASS** |

---

## INV-HORIZON-NEXT-BLOCK-READY-001

> At fence time `F` of any block, `get_next_entry_after_utc_ms(F - 1)` is non-`None` and starts at `F`.

### THNB-001: Next block present before fence at every boundary

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-NEXT-BLOCK-READY-001` |
| **Scenario** | Walk through 12 consecutive blocks. At each fence, verify N+1 exists and starts at exact fence time. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon with >= 12 blocks via `evaluate_once()`. |
| **Actions** | For `i` in `0..11`: 1. Let `F = EPOCH_MS + ((i + 1) * BLOCK_DUR_MS)` (fence time = `end_utc_ms` of block `i`). 2. `current = execution_store.get_entry_at_utc_ms(F - 1)`. 3. `next_entry = execution_store.get_next_entry_after_utc_ms(F - 1)`. |
| **Assertions** | At every fence: `next_entry is not None`. `next_entry.start_utc_ms == current.end_utc_ms == F`. `next_entry.block_index == current.block_index + 1`. |
| **Failure mode** | `next_entry is None` at any fence; or `next_entry.start_utc_ms != F`. |

### THNB-002: Next-next block present when `required_lookahead_blocks=2`

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-NEXT-BLOCK-READY-001` |
| **Scenario** | Lookahead configured to 2. At each fence, both N+1 and N+2 exist. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon with >= 12 blocks. `required_lookahead_blocks = 2`. |
| **Actions** | For `i` in `0..9`: 1. Let `F = EPOCH_MS + ((i + 1) * BLOCK_DUR_MS)`. 2. `n1 = execution_store.get_next_entry_after_utc_ms(F - 1)`. 3. `n2 = execution_store.get_next_entry_after_utc_ms(n1.end_utc_ms - 1)`. |
| **Assertions** | At every fence: `n1 is not None` and `n2 is not None`. `n1.start_utc_ms == F`. `n2.start_utc_ms == n1.end_utc_ms`. `n2.block_index == n1.block_index + 1`. |
| **Failure mode** | `n2 is None` at any fence where `required_lookahead_blocks == 2`. |

### THNB-003: Missing next block at fence detected as planning fault

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-NEXT-BLOCK-READY-001` |
| **Scenario** | Execution store has exactly one block. Clock advances to its fence. |
| **Clock setup** | Start at `EPOCH_MS`. Populate store with single block: `entry_id="B0"`, `start_utc_ms=EPOCH_MS`, `end_utc_ms=EPOCH_MS + BLOCK_DUR_MS`, `block_index=0`. |
| **Actions** | 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 2. Let `F = contract_clock.now_utc_ms()`. 3. `next_entry = execution_store.get_next_entry_after_utc_ms(F - 1)`. 4. `report = horizon_manager.health_report()`. |
| **Assertions** | `next_entry is None`. `report.execution_compliant == False`. `report` contains a fence-starvation fault identifying `block_id="B0"` and `fence_utc_ms=F`. |
| **Failure mode** | Missing block at fence not reflected in `health_report()`; or `execution_compliant` remains `True`. |

### THNB-004: Fence boundary at programming day crossover

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-NEXT-BLOCK-READY-001` |
| **Scenario** | Last block of day N ends at next day's programming start. Next block belongs to day N+1. |
| **Clock setup** | Start at `EPOCH_MS + DAY_MS - BLOCK_DUR_MS`. Initialize horizon covering day boundary. |
| **Actions** | 1. Let `F = EPOCH_MS + DAY_MS` (fence = day boundary). 2. `contract_clock.advance_ms(BLOCK_DUR_MS)` — clock is now at `F`. 3. `current = execution_store.get_entry_at_utc_ms(F - 1)`. 4. `next_entry = execution_store.get_next_entry_after_utc_ms(F - 1)`. |
| **Assertions** | `current.end_utc_ms == F`. `next_entry is not None`. `next_entry.start_utc_ms == F`. `next_entry.end_utc_ms == F + BLOCK_DUR_MS`. |
| **Failure mode** | `next_entry is None` at day crossover; or `next_entry.start_utc_ms != F`. |

---

## INV-HORIZON-CONTINUOUS-COVERAGE-001

> For every adjacent pair in `ExecutionWindowStore`: `E_i.end_utc_ms == E_{i+1}.start_utc_ms` (integer equality).

### THCC-001: Contiguous boundaries across full horizon

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Walk all blocks in the execution horizon via snapshot. Verify exact integer equality at every seam. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize full `MIN_EXEC_HORIZON_MS` horizon (12 blocks at 30 min each) via `evaluate_once()`. |
| **Actions** | 1. `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. 2. For each adjacent pair `(snap.entries[i], snap.entries[i+1])`: compare `end_utc_ms` to `start_utc_ms`. |
| **Assertions** | For every pair: `snap.entries[i].end_utc_ms == snap.entries[i+1].start_utc_ms`. Every entry satisfies `entry.end_utc_ms > entry.start_utc_ms` (positive duration). No two entries share the same `start_utc_ms`. `len(snap.entries) == 12`. |
| **Failure mode** | Any adjacent pair where `end_utc_ms != start_utc_ms`; or any entry with non-positive duration. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` |
| **Status** | **PASS** |

### THCC-002: Gap detected and reported as violation

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Inject a 1 ms gap between two blocks. Seam validation detects it. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate block A: `start_utc_ms=EPOCH_MS`, `end_utc_ms=EPOCH_MS + BLOCK_DUR_MS`, `block_index=0`. 2. Populate block B: `start_utc_ms=EPOCH_MS + BLOCK_DUR_MS + 1`, `end_utc_ms=EPOCH_MS + 2 * BLOCK_DUR_MS + 1`, `block_index=1`. 3. `snap = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 2 * BLOCK_DUR_MS + 1)`. 4. Run seam validation on `snap.entries`. |
| **Assertions** | Validation fails. `delta_ms = snap.entries[1].start_utc_ms - snap.entries[0].end_utc_ms == 1`. Error identifies `left_block_id=A.block_id`, `right_block_id=B.block_id`, `delta_ms=1`. Classified as planning fault. |
| **Failure mode** | Gap not detected; or `delta_ms` not reported. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` |
| **Status** | **PASS** |

### THCC-003: Overlap detected and reported as violation

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Inject a 1 ms overlap between two blocks. Seam validation detects it. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate block A: `start_utc_ms=EPOCH_MS`, `end_utc_ms=EPOCH_MS + BLOCK_DUR_MS`, `block_index=0`. 2. Populate block B: `start_utc_ms=EPOCH_MS + BLOCK_DUR_MS - 1`, `end_utc_ms=EPOCH_MS + 2 * BLOCK_DUR_MS - 1`, `block_index=1`. 3. `snap = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 2 * BLOCK_DUR_MS)`. 4. Run seam validation on `snap.entries`. |
| **Assertions** | Validation fails. `delta_ms = snap.entries[1].start_utc_ms - snap.entries[0].end_utc_ms == -1`. Error identifies `left_block_id`, `right_block_id`, `delta_ms=-1`. |
| **Failure mode** | Overlap not detected; or `delta_ms` not reported. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` |
| **Status** | **PASS** |

### THCC-004: Coverage maintained after horizon extension

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Horizon extends. Seam between old and new blocks is contiguous. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon with 12 blocks via `evaluate_once()`. |
| **Actions** | 1. Record `W1 = execution_store.get_window_end_utc_ms()`. 2. `contract_clock.advance_ms(MIN_EXEC_HORIZON_MS - EXTEND_WATERMARK_MS)` — cross watermark. 3. `horizon_manager.evaluate_once()` — triggers extension. 4. Record `W2 = execution_store.get_window_end_utc_ms()`. 5. `snap = execution_store.read_window_snapshot(EPOCH_MS, W2)`. 6. Validate all seams in `snap.entries`. |
| **Assertions** | `W2 > W1`. All seams pass: `entries[i].end_utc_ms == entries[i+1].start_utc_ms` for every pair. The seam at the extension join (entry with `end_utc_ms == W1` adjacent to entry with `start_utc_ms == W1`) is included and passes. |
| **Failure mode** | Gap or overlap at the extension join. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` |
| **Status** | **PASS** |

### THCC-005: Coverage across 24-hour progression

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Full 24-hour walk in `BLOCK_DUR_MS` steps. Validate contiguity at each evaluation cycle. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon via `evaluate_once()`. |
| **Actions** | For each of 48 steps: 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 2. `horizon_manager.evaluate_once()`. 3. `snap = execution_store.read_window_snapshot(contract_clock.now_utc_ms(), execution_store.get_window_end_utc_ms())`. 4. Validate all seams in `snap.entries`. |
| **Assertions** | Zero seam violations across all 48 cycles. Every snapshot satisfies integer equality at every seam. |
| **Failure mode** | Seam violation at any step during 24-hour walk. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_continuous_coverage.py` |
| **Status** | **PASS** |

### THCC-006: No duplicate `entry_id` or time-slot within rolling window

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Justification** | Each temporal position maps to exactly one entry. Duplicate `entry_id` or duplicate `(start_utc_ms, end_utc_ms)` tuples within the execution horizon would make block-level operations (completion tracking, mutation, snapshot reads) ambiguous. Note: `block_id` may legitimately repeat when a schedule replays the same content in different time slots; `entry_id` and time-slot identity MUST NOT repeat. |
| **Scenario** | Walk the full execution horizon. Assert all `entry_id` values are unique and all `(start_utc_ms, end_utc_ms)` tuples are unique within the current window. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize full `MIN_EXEC_HORIZON_MS` horizon via `evaluate_once()`. |
| **Actions** | 1. `snap = execution_store.read_window_snapshot(contract_clock.now_utc_ms(), execution_store.get_window_end_utc_ms())`. 2. Collect all `entry_id` values and all `(start_utc_ms, end_utc_ms)` tuples from `snap.entries`. 3. `contract_clock.advance_ms(4 * BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()`. 4. `snap2 = execution_store.read_window_snapshot(contract_clock.now_utc_ms(), execution_store.get_window_end_utc_ms())`. 5. Collect all `entry_id` values and all `(start_utc_ms, end_utc_ms)` tuples from `snap2.entries`. |
| **Assertions** | `len(set(e.entry_id for e in snap.entries)) == len(snap.entries)`. `len(set((e.start_utc_ms, e.end_utc_ms) for e in snap.entries)) == len(snap.entries)`. `len(set(e.entry_id for e in snap2.entries)) == len(snap2.entries)`. `len(set((e.start_utc_ms, e.end_utc_ms) for e in snap2.entries)) == len(snap2.entries)`. |
| **Failure mode** | Duplicate `entry_id` or duplicate `(start_utc_ms, end_utc_ms)` found within a single rolling window snapshot. |

---

## INV-HORIZON-ATOMIC-PUBLISH-001

> Every snapshot read returns entries with exactly one `generation_id` per publish range. `generation_id` is monotonically increasing.

### THAP-001: Consumer sees complete generation after publish

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-ATOMIC-PUBLISH-001` |
| **Scenario** | Publish G2 replacing time range covered by G1. Snapshot read after publish returns only G2. `generation_id` is monotonically increasing. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate store with 6 blocks covering `[EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)` with `generation_id=1`. 2. `snap_before = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`. 3. `result = execution_store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS, new_entries=<6 replacement entries>, generation_id=2, reason_code="OPERATOR_OVERRIDE", operator_override=True)`. 4. `snap_after = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == True`. `result.published_generation_id == 2`. `snap_before.generation_id == 1`. `snap_after.generation_id == 2`. `snap_after.generation_id > snap_before.generation_id`. Every `entry.generation_id == 2` in `snap_after.entries`. `len(snap_after.entries) == 6`. No entry with `generation_id == 1` in `snap_after`. |
| **Failure mode** | Any entry in `snap_after` has `generation_id != 2`; or `snap_after.generation_id <= snap_before.generation_id`; or `result.published_generation_id != 2`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` |
| **Status** | **PASS** |

### THAP-002: Non-overlapping range unaffected by publish

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-ATOMIC-PUBLISH-001` |
| **Scenario** | Publish replaces range R1. Adjacent range R2 retains original generation. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate 12 blocks covering `[EPOCH_MS, EPOCH_MS + 12 * BLOCK_DUR_MS)` with `generation_id=1`. Let R1 = `[EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`, R2 = `[EPOCH_MS + 6 * BLOCK_DUR_MS, EPOCH_MS + 12 * BLOCK_DUR_MS)`. 2. `result = execution_store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS, new_entries=<6 replacement entries>, generation_id=2, reason_code="OPERATOR_OVERRIDE", operator_override=True)`. 3. `snap_r1 = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`. 4. `snap_r2 = execution_store.read_window_snapshot(EPOCH_MS + 6 * BLOCK_DUR_MS, EPOCH_MS + 12 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.published_generation_id == 2`. `snap_r1.generation_id == 2`. Every entry in `snap_r1.entries` has `generation_id == 2`. `snap_r2.generation_id == 1`. Every entry in `snap_r2.entries` has `generation_id == 1`. |
| **Failure mode** | R2 entries have `generation_id == 2`; publish bled into adjacent range. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` |
| **Status** | **PASS** |

### THAP-003: Snapshot read returns single generation; monotonicity holds

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-ATOMIC-PUBLISH-001` |
| **Scenario** | Snapshot before and after publish each return exactly one `generation_id`. Post-publish `generation_id` is strictly greater. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate 6 blocks with `generation_id=1`. 2. `snap_before = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`. 3. `result = execution_store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS, new_entries=<6 replacement entries>, generation_id=2, reason_code="REASON_TIME_THRESHOLD", operator_override=False)`. 4. `snap_after = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS)`. |
| **Assertions** | `len(set(e.generation_id for e in snap_before.entries)) == 1`. `snap_before.generation_id == 1`. `len(set(e.generation_id for e in snap_after.entries)) == 1`. `snap_after.generation_id == 2`. `snap_after.generation_id > snap_before.generation_id`. `result.published_generation_id == 2`. |
| **Failure mode** | `len(set(e.generation_id for e in snap.entries)) > 1` for any snapshot; or `snap_after.generation_id <= snap_before.generation_id`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` |
| **Status** | **PASS** |

### THAP-004: Operator override produces new generation for partial range

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-ATOMIC-PUBLISH-001` |
| **Scenario** | Operator override regenerates two blocks within a 12-block window. |
| **Clock setup** | Start at `EPOCH_MS`. |
| **Actions** | 1. Populate 12 blocks with `generation_id=1`. Let override range = `[EPOCH_MS + 3 * BLOCK_DUR_MS, EPOCH_MS + 5 * BLOCK_DUR_MS)` (blocks 3-4). 2. `result = execution_store.publish_atomic_replace(range_start_ms=EPOCH_MS + 3 * BLOCK_DUR_MS, range_end_ms=EPOCH_MS + 5 * BLOCK_DUR_MS, new_entries=<2 replacement entries>, generation_id=2, reason_code="OPERATOR_OVERRIDE", operator_override=True)`. 3. `snap_override = execution_store.read_window_snapshot(EPOCH_MS + 3 * BLOCK_DUR_MS, EPOCH_MS + 5 * BLOCK_DUR_MS)`. 4. `snap_before = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 3 * BLOCK_DUR_MS)`. 5. `snap_after = execution_store.read_window_snapshot(EPOCH_MS + 5 * BLOCK_DUR_MS, EPOCH_MS + 12 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == True`. `result.published_generation_id == 2`. `snap_override.generation_id == 2`. All entries in `snap_override.entries` have `generation_id == 2`. `snap_before.generation_id == 1`. All entries in `snap_before.entries` have `generation_id == 1`. `snap_after.generation_id == 1`. All entries in `snap_after.entries` have `generation_id == 1`. |
| **Failure mode** | Override range contains mixed generations; or non-override ranges affected; or `result.published_generation_id != 2`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_atomic_publish.py` |
| **Status** | **PASS** |

---

## INV-HORIZON-LOCKED-IMMUTABLE-001

> In-place mutation inside `[now, now + LOCKED_WINDOW_MS)` returns `ok=False, error_code="LOCKED_IMMUTABLE"`.

### THLI-001: Publish inside locked window rejected

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | `publish_atomic_replace` targets a single block inside the locked window with `operator_override=False`. |
| **Clock setup** | `FakeClock` at `EPOCH_MS`. Store populated with 12 blocks at `generation_id=1` via `operator_override=True`. `locked_end = _locked_window_end_ms(EPOCH_MS, LOCKED_WINDOW_MS)`. Assert `EPOCH_MS + BLOCK_DUR_MS <= locked_end`. |
| **Actions** | 1. `result = store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + BLOCK_DUR_MS, new_entries=[block-0], generation_id=2, reason_code="REASON_TIME_THRESHOLD", operator_override=False)`. 2. `snap = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == False`. `"INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result.error_code`. `snap.generation_id == 1` (original generation preserved). All entries have `generation_id == 1`. |
| **Failure mode** | `result.ok == True`; publish succeeded without operator override inside locked window. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` |
| **Status** | **PASS** |

### THLI-002: Automated multi-block publish in locked window rejected

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | Automated process attempts `publish_atomic_replace` for a 4-block range fully inside locked window with `operator_override=False`. |
| **Clock setup** | `FakeClock` at `EPOCH_MS`. Store populated with 12 blocks at `generation_id=1`. Assert `EPOCH_MS + 4 * BLOCK_DUR_MS <= locked_end`. |
| **Actions** | 1. `result = store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + 4 * BLOCK_DUR_MS, new_entries=[blocks 0-3], generation_id=2, reason_code="AUTOMATED_REGEN", operator_override=False)`. 2. `snap = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 4 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == False`. `"INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result.error_code`. `snap.generation_id == 1`. |
| **Failure mode** | `result.ok == True`; automated multi-block replace succeeded inside locked window. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` |
| **Status** | **PASS** |

### THLI-003: Operator override replaces locked block with new generation

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | Operator override replaces a two-block range within the locked window. |
| **Clock setup** | `FakeClock` at `EPOCH_MS`. Store populated with 12 blocks at `generation_id=1`. Assert `EPOCH_MS + 2 * BLOCK_DUR_MS <= locked_end`. |
| **Actions** | 1. `result = store.publish_atomic_replace(range_start_ms=EPOCH_MS, range_end_ms=EPOCH_MS + 2 * BLOCK_DUR_MS, new_entries=[blocks 0-1], generation_id=2, reason_code="OPERATOR_OVERRIDE", operator_override=True)`. 2. `snap_replaced = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 2 * BLOCK_DUR_MS)`. 3. `snap_rest = store.read_window_snapshot(EPOCH_MS + 2 * BLOCK_DUR_MS, EPOCH_MS + 12 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == True`. `result.published_generation_id == 2`. `snap_replaced.generation_id == 2`. All entries in `snap_replaced` have `generation_id == 2`. `snap_rest.generation_id == 1`. All entries in `snap_rest` have `generation_id == 1`. |
| **Failure mode** | `result.ok == False`; or non-overridden blocks affected; or `result.published_generation_id != 2`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` |
| **Status** | **PASS** |

### THLI-004: Publish beyond locked window accepted without override

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | Publish targeting only the flexible future (beyond locked window) with `operator_override=False`. |
| **Clock setup** | `FakeClock` at `EPOCH_MS`. Store populated with 12 blocks at `generation_id=1`. `flexible_start = EPOCH_MS + 4 * BLOCK_DUR_MS`. Assert `flexible_start >= locked_end`. |
| **Actions** | 1. `result = store.publish_atomic_replace(range_start_ms=flexible_start, range_end_ms=flexible_start + 2 * BLOCK_DUR_MS, new_entries=[blocks 4-5], generation_id=2, reason_code="REASON_TIME_THRESHOLD", operator_override=False)`. 2. `snap = store.read_window_snapshot(flexible_start, flexible_start + 2 * BLOCK_DUR_MS)`. |
| **Assertions** | `result.ok == True`. `result.published_generation_id == 2`. `snap.generation_id == 2`. All entries have `generation_id == 2`. |
| **Failure mode** | `result.ok == False`; locked-window enforcement extends beyond `LOCKED_WINDOW_MS`. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` |
| **Status** | **PASS** |

### THLI-005: Clock advance moves lock boundary; previously-flexible becomes locked

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | Clock advances. Previously-flexible block enters the locked window and becomes immutable. |
| **Clock setup** | `FakeClock` at `EPOCH_MS`. Store populated with 12 blocks at `generation_id=1`. |
| **Actions** | 1. `flexible_start = EPOCH_MS + 4 * BLOCK_DUR_MS`. 2. `result_1 = store.publish_atomic_replace(range_start_ms=flexible_start, range_end_ms=flexible_start + 2 * BLOCK_DUR_MS, ..., generation_id=2, operator_override=False)` — succeeds. 3. `clock.advance_ms(2 * BLOCK_DUR_MS)`. 4. `locked_end_2 = _locked_window_end_ms(clock.now_utc_ms(), LOCKED_WINDOW_MS)`. Assert `flexible_start < locked_end_2`. 5. `result_2 = store.publish_atomic_replace(range_start_ms=flexible_start, ..., generation_id=3, operator_override=False)`. |
| **Assertions** | `result_1.ok == True`. `result_2.ok == False`. `"INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result_2.error_code`. `locked_end_2 > EPOCH_MS + LOCKED_WINDOW_MS` (boundary moved). |
| **Failure mode** | `result_2.ok == True`; block remains mutable after entering the locked window. |
| **Test file** | `pkg/core/tests/contracts/test_inv_horizon_locked_immutable.py` |
| **Status** | **PASS** |

---

## INV-CHANNEL-TIMELINE-CONTINUITY-001

> `timeline.compute_position(T, channel_epoch_utc_ms, snapshot)` returns identical `ChannelPosition` for identical `T` regardless of runtime events. `offset_ms == T - block_start_utc_ms`.

### THTC-001: Position identical before and after AIR restart

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | Compute position. Simulate AIR stop + restart. Recompute at same T. All fields identical. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. Let `T = EPOCH_MS + 5 * BLOCK_DUR_MS + 900_000` (mid-block 5, 15 minutes in). |
| **Actions** | 1. `contract_clock.advance_ms(T - EPOCH_MS)`. 2. `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. 3. `P1 = timeline.compute_position(now_utc_ms=T, channel_epoch_utc_ms=EPOCH_MS, snapshot=snap)`. 4. Simulate AIR stop event. 5. Simulate AIR start event (new session). 6. `P2 = timeline.compute_position(now_utc_ms=T, channel_epoch_utc_ms=EPOCH_MS, snapshot=snap)`. |
| **Assertions** | `P1.block_id == P2.block_id`. `P1.block_index == P2.block_index == 5`. `P1.block_start_utc_ms == P2.block_start_utc_ms == EPOCH_MS + 5 * BLOCK_DUR_MS`. `P1.offset_ms == P2.offset_ms == 900_000`. `P1.offset_ms == T - P1.block_start_utc_ms`. |
| **Failure mode** | Any field of `P1 != P2`; or `offset_ms != T - block_start_utc_ms`. |

### THTC-002: Position after viewer absence equals f(T2, epoch, schedule)

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | Viewers depart. Clock advances 5 hours. Viewer returns. Position reflects current clock, not departure time. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. |
| **Actions** | 1. Let `T1 = EPOCH_MS + 2 * BLOCK_DUR_MS`. `contract_clock.advance_ms(T1 - EPOCH_MS)`. 2. `snap1 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P1 = timeline.compute_position(T1, EPOCH_MS, snap1)`. 3. Simulate all viewers depart (playout stops). 4. For 10 steps: `contract_clock.advance_ms(BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()`. 5. Let `T2 = contract_clock.now_utc_ms()` = `EPOCH_MS + 12 * BLOCK_DUR_MS`. 6. Simulate viewer tune-in. 7. `snap2 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P2 = timeline.compute_position(T2, EPOCH_MS, snap2)`. |
| **Assertions** | `P2.block_index == 12`. `P2.block_start_utc_ms == EPOCH_MS + 12 * BLOCK_DUR_MS`. `P2.offset_ms == 0` (exactly at block start). `P2.offset_ms == T2 - P2.block_start_utc_ms`. `horizon_manager.extension_forbidden_trigger_count == 0`. |
| **Failure mode** | `P2.block_index != 12`; position reflects departure time; or `extension_forbidden_trigger_count > 0`. |

### THTC-003: Two independent computations yield identical output

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | Two independent position computations with identical inputs produce identical `ChannelPosition`. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. Let `T = EPOCH_MS + 7 * BLOCK_DUR_MS + 600_000` (10 min into block 7). |
| **Actions** | 1. `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. 2. `P_A = timeline.compute_position(T, EPOCH_MS, snap)`. 3. `P_B = timeline.compute_position(T, EPOCH_MS, snap)`. |
| **Assertions** | `P_A.block_id == P_B.block_id`. `P_A.block_index == P_B.block_index == 7`. `P_A.block_start_utc_ms == P_B.block_start_utc_ms == EPOCH_MS + 7 * BLOCK_DUR_MS`. `P_A.offset_ms == P_B.offset_ms == 600_000`. `P_A.offset_ms == T - P_A.block_start_utc_ms`. |
| **Failure mode** | `P_A != P_B` on any field. |

### THTC-004: Five restart cycles produce zero cumulative drift

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | 5 AIR crash/restart cycles at deterministic offsets. Position at each T matches `f(T, epoch, schedule)`. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. Deterministic offsets: `[BLOCK_DUR_MS, 2 * BLOCK_DUR_MS, BLOCK_DUR_MS, 3 * BLOCK_DUR_MS, BLOCK_DUR_MS]` (total = 8 blocks = 4 hours). |
| **Actions** | For `i` in `0..4`: 1. `contract_clock.advance_ms(offsets[i])`. 2. Simulate AIR crash + restart. 3. Let `T = contract_clock.now_utc_ms()`. 4. `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. 5. `P = timeline.compute_position(T, EPOCH_MS, snap)`. 6. Compute expected: `expected_block_index = (T - EPOCH_MS) // BLOCK_DUR_MS`. `expected_block_start = EPOCH_MS + expected_block_index * BLOCK_DUR_MS`. `expected_offset = T - expected_block_start`. |
| **Assertions** | At every step: `P.block_index == expected_block_index`. `P.block_start_utc_ms == expected_block_start`. `P.offset_ms == expected_offset`. `P.offset_ms == T - P.block_start_utc_ms`. `P.block_id` is stable (same `block_id` for same `T` across all computations at that step). No cumulative drift. |
| **Failure mode** | Any `P.block_index != expected_block_index`; or `P.offset_ms != expected_offset`; drift accumulates across restarts. |

### THTC-005: Position correct across programming day boundary after restart

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | AIR restart at programming day boundary (06:00 next day). Position references day 2 block 0. |
| **Clock setup** | Start at `EPOCH_MS + DAY_MS - BLOCK_DUR_MS` (last block of day 1). Initialize horizon covering day boundary. |
| **Actions** | 1. Let `T_before = EPOCH_MS + DAY_MS - 1` (1 ms before boundary). `contract_clock.advance_ms(T_before - (EPOCH_MS + DAY_MS - BLOCK_DUR_MS))`. `snap = execution_store.read_window_snapshot(EPOCH_MS + DAY_MS - BLOCK_DUR_MS, execution_store.get_window_end_utc_ms())`. `P1 = timeline.compute_position(T_before, EPOCH_MS, snap)`. 2. `contract_clock.advance_ms(1)` — clock at `EPOCH_MS + DAY_MS`. 3. Simulate AIR restart. 4. Let `T_after = contract_clock.now_utc_ms()` = `EPOCH_MS + DAY_MS`. `snap2 = execution_store.read_window_snapshot(EPOCH_MS + DAY_MS - BLOCK_DUR_MS, execution_store.get_window_end_utc_ms())`. `P2 = timeline.compute_position(T_after, EPOCH_MS, snap2)`. |
| **Assertions** | `P1.block_start_utc_ms == EPOCH_MS + DAY_MS - BLOCK_DUR_MS` (last block of day 1). `P1.offset_ms == BLOCK_DUR_MS - 1`. `P1.offset_ms == T_before - P1.block_start_utc_ms`. `P2.block_start_utc_ms == EPOCH_MS + DAY_MS` (first block of day 2). `P2.offset_ms == 0`. `P2.offset_ms == T_after - P2.block_start_utc_ms`. `P2.block_id != P1.block_id`. |
| **Failure mode** | `P2` references day 1; or `offset_ms` incorrect at boundary; restart corrupted day-2 position. |

### THTC-006: 24-hour interrupted vs. uninterrupted parity

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | Compare positions from uninterrupted 24-hour walk against walk with 3 restart events. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. |
| **Actions** | **Path A (uninterrupted):** For `i` in `0..47`: `T = EPOCH_MS + i * BLOCK_DUR_MS + 900_000` (15 min into each block). `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `positions_A[i] = timeline.compute_position(T, EPOCH_MS, snap)`. **Path B (interrupted):** Same computation at same `T` values, but simulate AIR restart before steps 8, 24, and 40. |
| **Assertions** | For all `i` in `0..47`: `positions_A[i].block_id == positions_B[i].block_id`. `positions_A[i].block_index == positions_B[i].block_index`. `positions_A[i].block_start_utc_ms == positions_B[i].block_start_utc_ms`. `positions_A[i].offset_ms == positions_B[i].offset_ms == 900_000`. `positions_A[i].offset_ms == T - positions_A[i].block_start_utc_ms`. |
| **Failure mode** | Any positional divergence between paths A and B at any step. |

---

## Cross-Invariant Scenario Tests

### TXSC-001: Full 24-hour broadcast day progression

| Field | Value |
|---|---|
| **Invariants** | `INV-HORIZON-EXECUTION-MIN-001`, `INV-HORIZON-NEXT-BLOCK-READY-001`, `INV-HORIZON-CONTINUOUS-COVERAGE-001`, `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Simulate complete broadcast day. Validate all four invariants at every block boundary. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon via `evaluate_once()`. |
| **Actions** | For each of 48 steps: 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 2. `horizon_manager.evaluate_once()`. 3. `depth = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. 4. `F = contract_clock.now_utc_ms()`. `next_entry = execution_store.get_next_entry_after_utc_ms(F - 1)`. 5. `snap = execution_store.read_window_snapshot(F, execution_store.get_window_end_utc_ms())`. Validate all seams. 6. `report = horizon_manager.health_report()`. |
| **Assertions** | (a) `depth >= MIN_EXEC_HORIZON_MS` at every step. (b) `next_entry is not None` and `next_entry.start_utc_ms == F` at every fence. (c) Zero seam violations across all 48 snapshots. (d) `horizon_manager.extension_forbidden_trigger_count == 0` at end. (e) Every entry in `horizon_manager.extension_attempt_log` has `triggered_by == "SCHED_MGR_POLICY"` and `reason_code` in `{"REASON_TIME_THRESHOLD", "DAILY_ROLL"}`. (f) `report.execution_compliant == True` at every step. |
| **Failure mode** | Any single invariant violation at any step. |

### TXSC-002: Viewer absence with horizon maintenance

| Field | Value |
|---|---|
| **Invariants** | `INV-CHANNEL-TIMELINE-CONTINUITY-001`, `INV-HORIZON-EXECUTION-MIN-001`, `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Viewers depart. Clock continues. Horizon manager continues evaluating. Viewer returns. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. |
| **Actions** | 1. Let `T1 = EPOCH_MS + 2 * BLOCK_DUR_MS`. `contract_clock.advance_ms(T1 - EPOCH_MS)`. `snap1 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P1 = timeline.compute_position(T1, EPOCH_MS, snap1)`. 2. Simulate all viewers depart. 3. For 4 steps: `contract_clock.advance_ms(BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()`. 4. Let `T2 = contract_clock.now_utc_ms()`. Simulate viewer tune-in. 5. `snap2 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P2 = timeline.compute_position(T2, EPOCH_MS, snap2)`. 6. `depth = execution_store.get_window_end_utc_ms() - T2`. |
| **Assertions** | (a) `depth >= MIN_EXEC_HORIZON_MS` at T2. (b) `P2.block_index == (T2 - EPOCH_MS) // BLOCK_DUR_MS`. `P2.offset_ms == T2 - P2.block_start_utc_ms`. (c) `horizon_manager.extension_forbidden_trigger_count == 0`. Every extension during absence has `triggered_by == "SCHED_MGR_POLICY"`. |
| **Failure mode** | Horizon stale after absence; or position reseeded by tune-in; or `extension_forbidden_trigger_count > 0`. |

### TXSC-003: AIR restart with atomic regeneration

| Field | Value |
|---|---|
| **Invariants** | `INV-CHANNEL-TIMELINE-CONTINUITY-001`, `INV-HORIZON-ATOMIC-PUBLISH-001`, `INV-HORIZON-LOCKED-IMMUTABLE-001` |
| **Scenario** | AIR crashes. Operator triggers partial schedule override. New AIR starts. |
| **Clock setup** | Start at `EPOCH_MS + 6 * BLOCK_DUR_MS` (mid-day). Initialize horizon. |
| **Actions** | 1. Let `T = contract_clock.now_utc_ms()`. `snap0 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P1 = timeline.compute_position(T, EPOCH_MS, snap0)`. 2. Simulate AIR crash. 3. `result = execution_store.publish_atomic_replace(range_start_ms=EPOCH_MS + 7 * BLOCK_DUR_MS, range_end_ms=EPOCH_MS + 9 * BLOCK_DUR_MS, new_entries=<2 replacement entries>, generation_id=2, reason_code="OPERATOR_OVERRIDE", operator_override=True)`. 4. `snap_override = execution_store.read_window_snapshot(EPOCH_MS + 7 * BLOCK_DUR_MS, EPOCH_MS + 9 * BLOCK_DUR_MS)`. 5. `snap_untouched = execution_store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 7 * BLOCK_DUR_MS)`. 6. Simulate AIR restart. `snap1 = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. `P2 = timeline.compute_position(T, EPOCH_MS, snap1)`. |
| **Assertions** | (a) `P1.block_id == P2.block_id`. `P1.offset_ms == P2.offset_ms`. `P2.offset_ms == T - P2.block_start_utc_ms`. (b) `result.ok == True`. `result.published_generation_id == 2`. `snap_override.generation_id == 2`. `snap_untouched.generation_id == 1`. (c) Non-overridden locked blocks unchanged. |
| **Failure mode** | Position changed by crash; or override corrupted non-target blocks; or mixed generations. |

### TXSC-004: Rapid fence transitions with lookahead

| Field | Value |
|---|---|
| **Invariants** | `INV-HORIZON-NEXT-BLOCK-READY-001`, `INV-HORIZON-CONTINUOUS-COVERAGE-001` |
| **Scenario** | Advance clock through 20 fence boundaries. Validate next-block readiness and seam contiguity at each. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon with >= 20 blocks. `required_lookahead_blocks = 2`. |
| **Actions** | For `i` in `0..19`: 1. Let `F = EPOCH_MS + (i + 1) * BLOCK_DUR_MS` (fence). 2. `contract_clock.advance_ms(BLOCK_DUR_MS)`. 3. `current = execution_store.get_entry_at_utc_ms(F - 1)`. 4. `n1 = execution_store.get_next_entry_after_utc_ms(F - 1)`. 5. `n2 = execution_store.get_next_entry_after_utc_ms(n1.end_utc_ms - 1)`. 6. Assert seam: `current.end_utc_ms == n1.start_utc_ms`. |
| **Assertions** | At every fence: `n1 is not None`. `n2 is not None`. `n1.start_utc_ms == current.end_utc_ms == F`. `n2.start_utc_ms == n1.end_utc_ms`. 20 fence transitions, zero violations. |
| **Failure mode** | Missing block or seam violation at any fence. |

### TXSC-005: Extension failure recovery

| Field | Value |
|---|---|
| **Invariants** | `INV-HORIZON-EXECUTION-MIN-001`, `INV-HORIZON-PROACTIVE-EXTEND-001`, `INV-HORIZON-NEXT-BLOCK-READY-001` |
| **Scenario** | Planning pipeline fails for one cycle. Recovers on next. Initial horizon has sufficient headroom to absorb one missed cycle. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon to minimum depth via `evaluate_once()`. Record `depth_initial = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. Assert `depth_initial >= MIN_EXEC_HORIZON_MS`. |
| **Actions** | 1. `contract_clock.advance_ms(BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()` — succeeds. `S1 = horizon_manager.extension_success_count`. 2. Configure `StubPlanningPipeline` to return `error_code="PIPELINE_EXHAUSTED"`. `contract_clock.advance_ms(BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()` — fails. 3. `depth_after_fail = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. `report = horizon_manager.health_report()`. 4. Restore pipeline. `contract_clock.advance_ms(BLOCK_DUR_MS)`. `horizon_manager.evaluate_once()` — succeeds. `depth_recovered = execution_store.get_window_end_utc_ms() - contract_clock.now_utc_ms()`. |
| **Assertions** | (a) `horizon_manager.extension_attempt_log[-2].success == False`. `horizon_manager.extension_attempt_log[-2].error_code == "PIPELINE_EXHAUSTED"`. (b) `depth_after_fail >= MIN_EXEC_HORIZON_MS` (headroom absorbed the missed cycle; total clock advance is `3 * BLOCK_DUR_MS` which is less than `EXTEND_WATERMARK_MS`). (c) `depth_recovered >= MIN_EXEC_HORIZON_MS`. `horizon_manager.extension_attempt_log[-1].success == True`. (d) `horizon_manager.extension_forbidden_trigger_count == 0`. Every attempt has `triggered_by == "SCHED_MGR_POLICY"`. |
| **Failure mode** | Single pipeline failure causes depth violation; or recovery does not restore depth. |

---

## Additional Tests

### THTC-007: Restart rejoins mid-block at exact computed offset

| Field | Value |
|---|---|
| **Invariant** | `INV-CHANNEL-TIMELINE-CONTINUITY-001` |
| **Scenario** | AIR restart occurs 20 minutes into a 30-minute block. `compute_position` returns `offset_ms = 1_200_000`. Restart rejoins at the computed offset, not at block start. |
| **Clock setup** | Start at `EPOCH_MS`. Initialize horizon. |
| **Actions** | 1. `contract_clock.advance_ms(3 * BLOCK_DUR_MS + 1_200_000)` — 20 min into block 3. 2. Let `T = contract_clock.now_utc_ms()` = `EPOCH_MS + 3 * BLOCK_DUR_MS + 1_200_000`. 3. Simulate AIR crash + restart. 4. `snap = execution_store.read_window_snapshot(EPOCH_MS, execution_store.get_window_end_utc_ms())`. 5. `P = timeline.compute_position(T, EPOCH_MS, snap)`. |
| **Assertions** | `P.block_index == 3`. `P.block_start_utc_ms == EPOCH_MS + 3 * BLOCK_DUR_MS`. `P.offset_ms == 1_200_000`. `P.offset_ms == T - P.block_start_utc_ms`. The restart consumer receives `offset_ms = 1_200_000` for mid-block join, not `0`. |
| **Failure mode** | `P.offset_ms == 0` (restart reseeded to block start); or `P.offset_ms != T - P.block_start_utc_ms`; or `P.block_index != 3`. |

### THPE-006: Forbidden consumer-read path intercepted and counted

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Deliberately invoke the extension pipeline from a consumer-read code path. Verify `extension_forbidden_trigger_count` increments with code `"CONSUMER_READ"`. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. Invoke `horizon_manager.attempt_extend_from_consumer_read()` (test-only method that simulates a misrouted consumer-read extension attempt). |
| **Assertions** | `horizon_manager.extension_forbidden_trigger_count == F_before + 1`. `horizon_manager.extension_attempt_count` unchanged (forbidden attempt is not a real attempt). `execution_store.get_window_end_utc_ms()` unchanged. `horizon_manager.extension_attempt_log` length unchanged (forbidden triggers are not logged as attempts). |
| **Failure mode** | `extension_forbidden_trigger_count` did not increment; or extension state changed despite forbidden trigger. |

### THPE-007: Forbidden tune-in path intercepted and counted

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Deliberately invoke the extension pipeline from a tune-in code path. Verify `extension_forbidden_trigger_count` increments with code `"TUNE_IN"`. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. Invoke `horizon_manager.attempt_extend_from_tune_in()` (test-only method that simulates a misrouted tune-in extension attempt). |
| **Assertions** | `horizon_manager.extension_forbidden_trigger_count == F_before + 1`. `horizon_manager.extension_attempt_count` unchanged. `execution_store.get_window_end_utc_ms()` unchanged. `horizon_manager.extension_attempt_log` length unchanged. |
| **Failure mode** | `extension_forbidden_trigger_count` did not increment; or extension state changed. |

### THPE-008: Forbidden block-completed path intercepted and counted

| Field | Value |
|---|---|
| **Invariant** | `INV-HORIZON-PROACTIVE-EXTEND-001` |
| **Scenario** | Deliberately invoke the extension pipeline from a block-completed code path. Verify `extension_forbidden_trigger_count` increments with code `"BLOCK_COMPLETED"`. |
| **Clock setup** | Start at `EPOCH_MS`. Pre-populate full `MIN_EXEC_HORIZON_MS` coverage. Record `F_before = horizon_manager.extension_forbidden_trigger_count`. |
| **Actions** | 1. Invoke `horizon_manager.attempt_extend_from_block_completed()` (test-only method that simulates a misrouted block-completed extension attempt). |
| **Assertions** | `horizon_manager.extension_forbidden_trigger_count == F_before + 1`. `horizon_manager.extension_attempt_count` unchanged. `execution_store.get_window_end_utc_ms()` unchanged. `horizon_manager.extension_attempt_log` length unchanged. |
| **Failure mode** | `extension_forbidden_trigger_count` did not increment; or extension state changed. |

---

## Test ID Index

| Test ID | Invariant | Summary | Status |
|---|---|---|---|
| THPE-001 | INV-HORIZON-PROACTIVE-EXTEND-001 | Extension at watermark crossing with REASON_TIME_THRESHOLD reason | TODO |
| THPE-002 | INV-HORIZON-PROACTIVE-EXTEND-001 | Consumer read: all four baselines unchanged | TODO |
| THPE-003 | INV-HORIZON-PROACTIVE-EXTEND-001 | Tune-in: all four baselines unchanged | TODO |
| THPE-004 | INV-HORIZON-PROACTIVE-EXTEND-001 | BlockCompleted: all four baselines unchanged | TODO |
| THPE-005 | INV-HORIZON-PROACTIVE-EXTEND-001 | No duplicate extension at same clock value | TODO |
| THPE-006 | INV-HORIZON-PROACTIVE-EXTEND-001 | Forbidden consumer-read path increments counter | TODO |
| THPE-007 | INV-HORIZON-PROACTIVE-EXTEND-001 | Forbidden tune-in path increments counter | TODO |
| THPE-008 | INV-HORIZON-PROACTIVE-EXTEND-001 | Forbidden block-completed path increments counter | TODO |
| TPX-001 | INV-HORIZON-PROACTIVE-EXTEND-001 | No extension when remaining > proactive threshold | **PASS** |
| TPX-002 | INV-HORIZON-PROACTIVE-EXTEND-001 | Extension when crossing threshold; depth increased | **PASS** |
| TPX-003 | INV-HORIZON-PROACTIVE-EXTEND-001 | Fires before min_execution_hours violation | **PASS** |
| TPX-004 | INV-HORIZON-PROACTIVE-EXTEND-001 | Pipeline failure during proactive extend; store not corrupted | **PASS** |
| TPX-005 | INV-HORIZON-PROACTIVE-EXTEND-001 | Idempotent per tick; no duplicate at same clock | **PASS** |
| THEM-001 | INV-HORIZON-EXECUTION-MIN-001 | Depth meets minimum after init | **PASS** |
| THEM-002 | INV-HORIZON-EXECUTION-MIN-001 | Depth maintained across 24h walk | **PASS** |
| THEM-003 | INV-HORIZON-EXECUTION-MIN-001 | Pipeline failure produces deficit and fault | **PASS** |
| THEM-004 | INV-HORIZON-EXECUTION-MIN-001 | Survives programming day boundary | **PASS** |
| THNB-001 | INV-HORIZON-NEXT-BLOCK-READY-001 | Next block at every fence via get_next_entry_after_utc_ms | TODO |
| THNB-002 | INV-HORIZON-NEXT-BLOCK-READY-001 | Next-next block for lookahead=2 | TODO |
| THNB-003 | INV-HORIZON-NEXT-BLOCK-READY-001 | Missing block at fence detected as planning fault | TODO |
| THNB-004 | INV-HORIZON-NEXT-BLOCK-READY-001 | Fence at day crossover | TODO |
| TNB-001 | INV-HORIZON-NEXT-BLOCK-READY-001 | Next block present after init via HorizonManager._check_next_block_ready | **PASS** |
| TNB-002 | INV-HORIZON-NEXT-BLOCK-READY-001 | Gap at now filled by pipeline extension | **PASS** |
| TNB-003 | INV-HORIZON-NEXT-BLOCK-READY-001 | Pipeline failure leaves gap; next_block_compliant=False | **PASS** |
| TNB-004 | INV-HORIZON-NEXT-BLOCK-READY-001 | Locked window prevents fill; LOCKED_IMMUTABLE error | **PASS** |
| THCC-001 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | Contiguous boundaries via snapshot read | **PASS** |
| THCC-002 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | 1 ms gap detected with delta_ms | **PASS** |
| THCC-003 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | 1 ms overlap detected with delta_ms | **PASS** |
| THCC-004 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | Contiguity at extension join | **PASS** |
| THCC-005 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | 48-step 24-hour walk contiguity | **PASS** |
| THCC-006 | INV-HORIZON-CONTINUOUS-COVERAGE-001 | No duplicate entry_id or time-slot in rolling window | TODO |
| THAP-001 | INV-HORIZON-ATOMIC-PUBLISH-001 | Complete generation after publish; monotonic generation_id | **PASS** |
| THAP-002 | INV-HORIZON-ATOMIC-PUBLISH-001 | Non-overlapping range retains original generation | **PASS** |
| THAP-003 | INV-HORIZON-ATOMIC-PUBLISH-001 | Snapshot single generation_id; monotonicity enforced | **PASS** |
| THAP-004 | INV-HORIZON-ATOMIC-PUBLISH-001 | Operator override partial range new generation | **PASS** |
| THLI-001 | INV-HORIZON-LOCKED-IMMUTABLE-001 | publish_atomic_replace inside locked window rejected | **PASS** |
| THLI-002 | INV-HORIZON-LOCKED-IMMUTABLE-001 | Automated multi-block publish in locked window rejected | **PASS** |
| THLI-003 | INV-HORIZON-LOCKED-IMMUTABLE-001 | Operator override replaces locked block with new generation_id | **PASS** |
| THLI-004 | INV-HORIZON-LOCKED-IMMUTABLE-001 | Publish beyond locked window accepted without override | **PASS** |
| THLI-005 | INV-HORIZON-LOCKED-IMMUTABLE-001 | Clock advance moves lock boundary; previously-flexible becomes locked | **PASS** |
| THTC-001 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Position same after AIR restart; offset_ms verified | TODO |
| THTC-002 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Position after viewer absence; offset_ms = T - block_start | TODO |
| THTC-003 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Two independent computations identical | TODO |
| THTC-004 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Five restarts zero drift; offset_ms and block_id verified | TODO |
| THTC-005 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Day boundary + restart; offset_ms correct | TODO |
| THTC-006 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | 24h interrupted vs uninterrupted parity | TODO |
| THTC-007 | INV-CHANNEL-TIMELINE-CONTINUITY-001 | Restart rejoins mid-block at exact offset | TODO |
| TXSC-001 | Multi | Full 24-hour broadcast day; forbidden count == 0 | TODO |
| TXSC-002 | Multi | Viewer absence + horizon; forbidden count == 0 | TODO |
| TXSC-003 | Multi | AIR restart + atomic regeneration | TODO |
| TXSC-004 | Multi | Rapid fence transitions with lookahead=2 | TODO |
| TXSC-005 | Multi | Extension failure recovery; headroom absorbs miss | TODO |
