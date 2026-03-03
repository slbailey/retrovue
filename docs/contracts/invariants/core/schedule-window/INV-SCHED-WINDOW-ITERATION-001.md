# INV-SCHED-WINDOW-ITERATION-001 — A scheduled window may emit multiple independent iterations of a schedulable entry

Status: Invariant
Authority Level: Planning
Derived From: `LAW-TIMELINE`, `LAW-CONTENT-AUTHORITY`

## Purpose

Defines the iteration model for scheduled windows that emit a schedulable entry more than once within a single time boundary. Establishes independence of iterations, timeline continuity, capacity gating under `allow_bleed: false`, and bleed semantics under `allow_bleed: true`. Keeps bleed policy in the schedule layer and out of template resolution logic.

## Guarantee

1. **Multiple iterations permitted.** A scheduled window may emit any number of sequential iterations of its schedulable entry. The iteration count is not fixed at Tier 1; it is determined at Tier 2 by available window capacity and resolved entry duration.

2. **Independent resolution.** Each iteration resolves independently. Selection state produced by one iteration does not constrain selection in any subsequent iteration within the same window, unless the underlying source definition (pool or collection) enforces deduplication internally.

3. **Timeline continuity.** No temporal gap exists between consecutive iterations within a window, or between the final iteration of one window and the nominal start of the next. The timeline is continuous at all times.

4. **Capacity gating — `allow_bleed: false`.** An iteration MUST NOT begin if the minimum possible duration of that iteration exceeds the remaining capacity of the window. Minimum possible duration is the lower bound on resolved duration derivable from the source definitions (e.g., the shortest eligible asset in the pool or collection). A new iteration MAY be withheld even if minimum possible duration equals remaining capacity, when doing so would guarantee overrun under any valid resolution.

5. **Final iteration bleed — `allow_bleed: true`.** When `allow_bleed` is true, the final iteration within the window MAY produce a resolved duration that exceeds the remaining window capacity. The nominal window end boundary does not truncate the in-progress iteration. The next declared window begins immediately after the final iteration of the prior window completes. The nominal window boundary is not used as a start time for the next window when bleed occurs.

6. **Window boundary authority.** Window boundaries declared at Tier 1 are authoritative as start-of-window conditions and as capacity limits under `allow_bleed: false`. They do not truncate in-progress iterations under any configuration.

## Preconditions

- The schedulable entry occupying the window is resolved at Tier 2.
- `allow_bleed` is an explicit property of the schedule window entry. Its absence MUST be treated as `allow_bleed: false`.
- Tier 2 resolution has access to source-level duration constraints sufficient to compute a minimum possible iteration duration.

## Observability

At Tier 2 resolution time, for each window:

- The number of resolved iterations MUST be recorded.
- For each iteration, the resolved start time, resolved end time, and resolved duration MUST be derivable from the output.
- When bleed occurs, the actual end time of the final iteration and the nominal window end time MUST both be recorded. The delta is the bleed duration.
- When an iteration is withheld due to capacity gating, the withheld state MUST be observable (e.g., via a resolution log entry indicating capacity exhaustion).

## Deterministic Testability

**allow_bleed: false, iteration withheld:**
Construct a window with a declared end time leaving 10 minutes of remaining capacity. Configure the schedulable entry such that its minimum possible duration is 11 minutes (e.g., a pool whose shortest eligible asset is 11 minutes). Assert that Tier 2 resolution produces no additional iteration and records a capacity-exhaustion condition.

**allow_bleed: true, iteration permitted to exceed capacity:**
Construct a window with 10 minutes of remaining capacity and `allow_bleed: true`. Configure the schedulable entry to resolve to a duration of 12 minutes. Assert that Tier 2 resolution permits the iteration to proceed, records a bleed duration of 2 minutes, and positions the start of the next window at the resolved end of the bleed iteration (not at the nominal window boundary).

**Timeline continuity:**
Construct two consecutive windows. Assert that the resolved start time of each iteration equals the resolved end time of the prior iteration with zero gap, and that the resolved start time of the first iteration of the second window equals the resolved end time of the final iteration of the first window.

**Independence of iterations:**
Resolve a window that produces multiple iterations from a pool. Assert that asset selection is performed independently per iteration (no carry-forward of selection state between iterations at the resolution layer).

No real-time waits required. All assertions operate on Tier 2 resolution output.

## Failure Semantics

**Planning fault — capacity overrun under allow_bleed: false.** An iteration was permitted to begin under `allow_bleed: false` and its resolved duration exceeded remaining window capacity. The system MUST reject the resolution output and report the fault with: affected window, iteration index, resolved duration, remaining capacity at iteration start, and the invariant tag.

**Planning fault — bleed on non-bleed window.** A resolved iteration extends past the window boundary on a window declared with `allow_bleed: false`. This is equivalent to a duration overrun and MUST be treated as a hard resolution failure.

**Planning fault — gap in timeline.** A resolved iteration sequence contains a temporal gap between iterations or between windows. The system MUST detect and reject any gap, regardless of bleed configuration.

## Required Tests

- `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py::TestCapacityGatingBleedFalse` — iteration withheld when minimum duration exceeds remaining capacity
- `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py::TestBleedIterationPermitted` — bleed iteration proceeds; next window positioned at bleed end
- `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py::TestTimelineContinuity` — no gap between iterations or between windows
- `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py::TestIterationIndependence` — asset selection does not carry forward between iterations
- `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py::TestOverrunRejectedOnNonBleedWindow` — resolved overrun under allow_bleed: false is a hard failure

## Enforcement Evidence

Not yet enforced. Enforcement is expected in the Tier 2 resolution pipeline (Playlog horizon builder) at the point where window iteration capacity is evaluated prior to beginning each iteration.

Error tag: `INV-SCHED-WINDOW-ITERATION-001-VIOLATED`
