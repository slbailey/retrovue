# Schedule Constraints

**Scope:** Pluggable constraint framework that validates scheduling decisions at plan-edit and compilation time.

**Authority:** SchedulePlan (planning layer). Constraints produce structured violation outputs. They do NOT mutate Playlog or execution state.

---

## 1. Constraint Families

### 1.1 Blackout Constraints

A blackout constraint defines a date/time exclusion window during which specific content MUST NOT be scheduled.

**Data model:**
- `asset_ids: frozenset[str]` — assets subject to the blackout (empty = all assets)
- `start_date: date` — first date the blackout applies (inclusive)
- `end_date: date` — last date the blackout applies (inclusive)
- `start_time: time` — start of daily exclusion window (broadcast-day-relative)
- `end_time: time` — end of daily exclusion window (broadcast-day-relative)
- `day_filters: frozenset[str] | None` — day-of-week filter (None = all days)
- `reason: str` — operator-provided justification

**Evaluation:** For each zone's schedulable assets, if any asset appears in a blackout window that overlaps the zone's time range on a matching day, the constraint is violated.

### 1.2 Adjacency Constraints

An adjacency constraint defines back-to-back content rules: two content classifications MUST NOT air in direct succession.

**Data model:**
- `classification_a: str` — first content classification (e.g. "horror")
- `classification_b: str` — second content classification (e.g. "children")
- `direction: str` — "both" (symmetric) or "a_before_b" (directional)
- `reason: str` — operator-provided justification

**Evaluation:** At compilation time, for each pair of adjacent blocks in the compiled schedule, if the trailing block's classification matches one side and the leading block's classification matches the other (respecting direction), the constraint is violated.

### 1.3 Content Restriction Constraints

A content restriction constraint defines rating/classification gates that restrict content to specific time windows (e.g. watershed rules).

**Data model:**
- `classification: str` — content classification subject to restriction (e.g. "18+", "mature")
- `allowed_start_time: time` — earliest permitted air time (broadcast-day-relative)
- `allowed_end_time: time` — latest permitted air time (broadcast-day-relative)
- `day_filters: frozenset[str] | None` — day-of-week filter (None = all days)
- `reason: str` — operator-provided justification

**Evaluation:** At plan-edit or compilation time, if content matching the restricted classification is scheduled outside the allowed time window on a matching day, the constraint is violated.

---

## 2. Evaluation Properties

### 2.1 Idempotency

Constraint evaluation MUST be idempotent: given the same inputs (zones, constraints, compiled blocks), evaluation MUST produce the same violation set. Constraints are pure functions with no side effects.

### 2.2 Structured Violations

Every violation MUST be a structured object containing:
- `invariant_id: str` — the invariant tag (e.g. `INV-CONSTRAINT-BLACKOUT-001-VIOLATED`)
- `constraint_type: str` — family identifier ("blackout", "adjacency", "content_restriction")
- `message: str` — human-readable description
- `details: dict` — machine-parseable context (asset IDs, time windows, classifications)

### 2.3 Enforcement Points

Constraints are evaluated at two enforcement points:

1. **Plan-edit time:** Within `validate_zone_plan_integrity()` pipeline, after existing checks (grid > overlap > coverage > eligibility > constraints). Blackout and content restriction constraints apply here.

2. **Compilation time:** Within `_compile_day()` after block assembly. Adjacency constraints apply here (require ordered block list). Blackout and content restriction constraints are re-checked against resolved blocks.

### 2.4 Failure Semantics

Constraint violations at plan-edit time are **Planning faults** — the operator MUST resolve them before the plan is accepted.

Constraint violations at compilation time are **Planning faults** that surface as `INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001` when they prevent a valid schedule from being produced.

---

## 3. Invariants

| Invariant | Guarantee |
|-----------|-----------|
| INV-CONSTRAINT-BLACKOUT-001 | Content subject to an active blackout MUST NOT appear in the schedule during the blackout window |
| INV-CONSTRAINT-ADJACENCY-001 | Adjacent blocks MUST NOT violate declared adjacency restrictions |
| INV-CONSTRAINT-CONTENT-RESTRICTION-001 | Restricted content MUST NOT appear outside its allowed time window |
| INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001 | Constraint evaluation MUST be a pure function: same inputs produce same violations |

---

## 4. Non-goals

- Constraint editor UI
- Dynamic runtime modification of constraints
- Priority/weighting between constraints
- Constraint relaxation or override mechanisms
