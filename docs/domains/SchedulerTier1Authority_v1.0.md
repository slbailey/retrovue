# Scheduler Tier 1 Authority — v1.0

**Status:** Binding
**Owner:** Core / Scheduler
**Last revised:** 2026-03-02
**Related documents:**
- `docs/domains/ProgramTemplateAssembly.md` — template DSL and segment resolution
- `pkg/core/src/retrovue/runtime/template_runtime.py` — canonical runtime structure definitions
- `docs/contracts/invariants/` — machine-checked invariant registry

---

## 1. Purpose

This document defines the authoritative rules governing Tier 1 schedule commitments in RetroVue Core. It specifies:

- What a Tier 1 window is and what it stores.
- When and how windows are created, rebuilt, and invalidated.
- How the `TemplateReferenceIndex` is maintained and why.
- What enforcement the Scheduler owns at template mutation time.
- The boundary between Tier 1 authority and Tier 2 resolution authority.

This document is binding. Any code or process that commits, rebuilds, or validates Tier 1 schedule windows must conform to the rules stated here.

---

## 2. Scope and Authority Boundary

RetroVue's schedule system is divided into three layers of increasing specificity:

```
L0  Config / TemplateRegistry   — live template definitions; owned by Config loader
L1  ScheduleRegistry            — committed time windows and entry references; owned by Scheduler
L2  PlaylogRegistry             — resolved event sequences per window; owned by ProgramDirector
```

**L0 authority (Config loader):**
- Defines and maintains `TemplateDef` objects in `TemplateRegistry`.
- Computes `primary_segment_index` at parse time.
- Does not know about scheduled time windows.

**L1 authority (Scheduler) — this document:**
- Owns `ScheduleRegistry` and `TemplateReferenceIndex`.
- Commits `ScheduledEntry` objects that record *what* should air during *which* wall-clock window.
- Does NOT resolve templates to concrete assets.
- Does NOT snapshot `TemplateRegistry` at commit time.
- Does NOT write to `PlaylogRegistry` or `ChannelActiveState`.

**L2 authority (ProgramDirector):**
- Reads L1 commitments and resolves them into concrete `PlaylogWindow` and `PlaylogEvent` objects.
- Reads `TemplateRegistry` live at each build; sees whatever template definition is current.
- Writes `PlaylogRegistry` exclusively.
- Detects Tier 1 staleness by comparing `PlaylogWindow.source_window_uuid` against `ScheduledEntry.window_uuid`.

**Strict boundary rule:** The Scheduler writes only to L0 (template mutation via operator action) and L1. It never reads `PlaylogRegistry` and never transitions `PlaylogWindowState`. The Scheduler's only permitted mutation to an existing `ScheduledEntry` after commit is a full replacement via explicit rebuild (see §5).

---

## 3. Canonical Schedule Entry Schema

A Tier 1 committed window stores exactly the following fields on `ScheduledEntry`. No other schedule-time information is persisted at L1.

| Field | Type | Description |
|---|---|---|
| `window_uuid` | `str` (UUID4) | Stable identity of this specific commit. Changes on every rebuild of the same logical window. |
| `window_key` | `WindowKey` | Time-coordinate identity: `(channel_id, wall_start_ms, wall_end_ms)`. Stable across rebuilds of the same logical window. |
| `type` | `"template"` \| `"pool"` \| `"asset"` | Entry type discriminator. |
| `name` | `str \| None` | Template ID or pool ID. Set when `type == "template"` or `type == "pool"`. Null when `type == "asset"`. |
| `asset_id` | `str \| None` | Direct asset reference. Set only when `type == "asset"`. Null otherwise. |
| `epg_title` | `str \| None` | Operator-assigned EPG display title. If set, this is the Tier 1 authority for EPG identity. Null triggers Tier 2 derivation from primary content asset. |
| `allow_bleed` | `bool` | When true, the last content iteration may run past `wall_end_ms`. Default false. Capacity gating above this floor belongs to the scheduling layer, not to Tier 2 fill logic. |
| `mode` | `str \| None` | Selection strategy (e.g. `"random"`). Applicable only when `type == "pool"`. Null otherwise. |
| `committed_at_ms` | `int` | Epoch ms at which this commit was recorded. |
| `state` | `ScheduleWindowState` | `COMMITTED` (default) or `BLOCKED`. See §6. |
| `blocked_reason_code` | `str \| None` | Machine-readable failure code. Null while `state == COMMITTED`. |
| `blocked_at_ms` | `int \| None` | Epoch ms of BLOCKED transition. Null while `state == COMMITTED`. |
| `blocked_details` | `str \| None` | Human-readable failure context for operator. Null while `state == COMMITTED`. |

**Field constraints (enforced at parse / schedule build; VAL-PARSE-* series):**

```
type == "template"  →  name is set, asset_id is None, mode is None
type == "pool"      →  name is set, asset_id is None, mode may be set
type == "asset"     →  name is None, asset_id is set, mode is None
```

**What Tier 1 does NOT store:**

- Template segment definitions or counts.
- Asset IDs resolved from templates (those are Tier 2 outputs).
- Duration of any resolved content (Tier 2 concern).
- PlaylogEvent sequences.
- Any snapshot of the template definition as it existed at commit time.

The Tier 1 record is intentionally thin. It is a *reference* to schedulable content and a *time window*. Resolution of that reference is deferred to Tier 2.

---

## 4. Window Time Model

All time values in Tier 1 are stored as absolute epoch milliseconds (UTC). The Scheduler is responsible for converting HH:MM boundaries from channel config into absolute epoch ms before creating a `WindowKey`.

**HH:MM → epoch ms conversion rules:**

1. The channel's configured timezone is applied when resolving HH:MM to a wall-clock instant on `target_date`.
2. Midnight crossing is resolved at build time: if `end < start` in clock terms, `wall_end_ms` is placed on the following calendar day.
3. The resulting `WindowKey` always satisfies `wall_end_ms > wall_start_ms`.
4. Conversion is performed by a dedicated helper (`_resolve_window_bounds`). The Scheduler does not inline this logic.

**Cross-midnight windows** are represented as a single `ScheduledEntry` with a `WindowKey` spanning the midnight boundary. There is no split into two entries.

---

## 5. Tier 1 Build Algorithm

The Scheduler builds the schedule horizon additively. It does not rebuild existing windows; that is an explicit operator action (§6).

**Preconditions before build:**

- `schedule_config` has been parsed and validated (parse-time validation; see §8).
- `target_date` is provided by the orchestration layer.
- All HH:MM boundaries have been resolved to epoch ms by `_resolve_window_bounds`.

**Build procedure:**

1. For each entry specification in `schedule_config.entries` (in declared order):
   a. Resolve `wall_start_ms` and `wall_end_ms` from the entry's `start` and `end` HH:MM fields and `target_date`.
   b. Construct a `WindowKey(channel_id, wall_start_ms, wall_end_ms)`.
   c. Construct a `ScheduledEntry` with a freshly generated UUID4 `window_uuid`, all canonical fields from the entry spec, `committed_at_ms` set to the current wall clock, and `state == COMMITTED`.

2. Under a single atomic lock acquisition of `ScheduleRegistry._lock` followed by `TemplateReferenceIndex._lock` (in that order — global lock positions 2 then 3):
   a. For each prepared entry, check whether `window_key` is already present in `ScheduleRegistry._windows`.
   b. If already present: **skip**. Horizon builds are additive and do not overwrite existing windows. A BLOCKED window for a given key can only be replaced by explicit `rebuild_window`.
   c. If not present: insert the entry into `ScheduleRegistry._windows`.
   d. If the entry is `type == "template"`: call `_index_insert` to add `window_key` to `TemplateReferenceIndex._index[entry.name]`, maintaining ascending `wall_start_ms` sort order.

3. Release both locks together.

**Atomicity guarantee:** Steps 2a–2d for all entries in a single call are executed within the same lock acquisition. Partially committed batches do not occur.

**Note on template existence:** The Scheduler does NOT verify that a referenced template exists in `TemplateRegistry` at commit time. Template resolution occurs at Tier 2 build time. A reference to a non-existent template results in a BLOCKED window via VAL-T2-001 at Tier 2, not at Tier 1 commit time. This preserves the L0/L1 boundary: Tier 1 stores references, not resolved content.

---

## 6. Tier 1 Rebuild Semantics

A Tier 1 rebuild is an **explicit operator action** that replaces a single committed window with a new commit. Rebuilds are not triggered automatically by the system.

**When rebuild is required:**

- The operator has changed the content assignment for an already-committed time slot.
- A window is in `BLOCKED` state and the operator has corrected the underlying cause (e.g., the missing template has been added, or the time slot has been restructured).
- The operator wishes to reset a BLOCKED window to COMMITTED for retry.

**Rebuild procedure (`rebuild_window`):**

1. Prepare the replacement `ScheduledEntry` with:
   - A freshly generated UUID4 `window_uuid`. This is the critical signal to Tier 2: the old `window_uuid` is now invalid.
   - The same `window_key` as the window being replaced (same time slot).
   - `state == COMMITTED` and all `blocked_*` fields set to `None` — regardless of the previous entry's state.
   - `committed_at_ms` set to the current wall clock.
   - All other fields from `replacement_spec` as provided by the operator.

2. Under a single atomic lock acquisition of `ScheduleRegistry._lock` then `TemplateReferenceIndex._lock` (positions 2 then 3):
   a. Retrieve the existing `ScheduledEntry` for `window_key` (if any).
   b. If the existing entry is `type == "template"`: call `_index_remove` to remove its `window_key` from `TemplateReferenceIndex._index[old_entry.name]`.
   c. Insert the new entry into `ScheduleRegistry._windows`, replacing the old entry.
   d. If the new entry is `type == "template"`: call `_index_insert` to add its `window_key` to `TemplateReferenceIndex._index[new_entry.name]`.

3. Release both locks together.

**Effect on Tier 2:** ProgramDirector detects the new `window_uuid` on the next `extend_horizon` call. Any existing `PlaylogWindow` for the same `window_key` built from the old commit will have a `source_window_uuid` that no longer matches the new `ScheduledEntry.window_uuid`. ProgramDirector discards that stale `PlaylogWindow` (if `PENDING`) and rebuilds. If the existing `PlaylogWindow` is `ACTIVE`, it is protected by the window-level freeze and is not disturbed; ProgramDirector will detect the staleness and rebuild after the window expires.

**Immutability rule:** The Scheduler **never mutates** any field of a committed `ScheduledEntry` except through rebuild (which replaces the entry entirely). The `state` field (`COMMITTED → BLOCKED`) is written only by `ProgramDirector` via `_mark_blocked`. A rebuild resets `state` to `COMMITTED` by construction — not by mutation of the existing object.

---

## 7. window_uuid Semantics

`window_uuid` is a UUID4 string that identifies a specific **commit version** of a Tier 1 window.

| Property | Rule |
|---|---|
| Assigned | Once, at commit time by the Scheduler. |
| Stable | Unchanged for the lifetime of that `ScheduledEntry` object. |
| Invalidated | When `rebuild_window` replaces the entry. The old object is discarded; a new object with a new UUID is created. |
| Not reused | No two `ScheduledEntry` commits, past or present, share a `window_uuid` for the same channel. |
| Staleness signal | ProgramDirector compares `PlaylogWindow.source_window_uuid` against `ScheduledEntry.window_uuid`. A mismatch means the Tier 1 entry has been rebuilt since the `PlaylogWindow` was last built. |
| Not a seed | `window_uuid` is not used to derive the Tier 2 build seed. The Tier 2 build seed is drawn fresh per build session and stored in `PlaylogBuildContext.seed`. |

`WindowKey` is **not** the commit identity. Multiple `ScheduledEntry` commits may share the same `WindowKey` (same time slot, different rebuild versions) over time. `WindowKey` is the **time-coordinate lookup key**; `window_uuid` is the **version identity**.

---

## 8. TemplateReferenceIndex

The `TemplateReferenceIndex` is a reverse index maintained atomically with `ScheduleRegistry`. It maps:

```
template_id  →  list[WindowKey]   (sorted ascending by wall_start_ms)
```

**State coverage (SCHED-INDEX-001):**

The index must include ALL `ScheduledEntry` records that reference a given `template_id`, regardless of `ScheduleWindowState`. Both `COMMITTED` and `BLOCKED` entries are indexed.

Rationale: A `BLOCKED` window is a committed Tier 1 entry. It still holds a live reference to its template. Allowing that template to be deleted while the window is `BLOCKED` would create a dangling reference that will fail again on the next rebuild attempt. The operator must explicitly remove or rebuild the `BLOCKED` window before the template can be deleted.

**Index maintenance events (all atomic with ScheduleRegistry write, both locks held):**

| Event | Index action |
|---|---|
| New window committed (`type == "template"`) | Insert `window_key` into `_index[template_id]` |
| Window rebuilt (template reference changed) | Remove old `window_key`; insert new `window_key` |
| Window rebuilt (type changed away from `"template"`) | Remove old `window_key` |
| Window rebuilt (type changed to `"template"`) | Insert new `window_key` |
| Window explicitly removed by operator | Remove `window_key` from `_index[template_id]` |
| `COMMITTED → BLOCKED` transition | No change — `window_key` stays in index |
| Template deletion approved (zero references) | `template_id` already absent from index |
| Template rename approved (zero references) | Old key already absent; new key not yet present |

**Invariant:** A `template_id` present in the index has at least one `ScheduledEntry` (in any state) whose `name == template_id`. Absence from the index is equivalent to zero references and is the gate for deletion and rename operations.

---

## 9. Template Mutation Enforcement

The Scheduler is the sole enforcer of template deletion and rename constraints. These rules apply at mutation time, not at horizon build time.

### 9.1 Template Deletion — VAL-T1-004

**Rule:** A template definition may not be deleted from `TemplateRegistry` while any `ScheduledEntry` in `ScheduleRegistry` references it, regardless of that entry's `ScheduleWindowState`.

**Enforcement procedure:**

Acquire all three locks in global order before performing the check:

```
TemplateRegistry._lock  (position 1)
  ScheduleRegistry._lock  (position 2)
    TemplateReferenceIndex._lock  (position 3)
```

All three locks must be held simultaneously during the check and the deletion. `ScheduleRegistry._lock` is required in addition to `TemplateReferenceIndex._lock` to close the race window in which a concurrent commit could have updated `ScheduleRegistry._windows` but not yet updated `TemplateReferenceIndex._index`.

**Decision logic:**

1. Look up `template_id` in `TemplateReferenceIndex._index`.
2. If any `WindowKey` entries are present (list is non-empty): **reject**.
3. If the list is empty or absent: proceed with deletion from `TemplateRegistry._templates`.

**Rejection error (VAL-T1-004):**

```
code:    "VAL-T1-004"
message: "cannot delete template '<template_id>': referenced by <N> window(s);
          earliest: channel=<channel_id> start=<wall_start_ms_iso> (state=<state>)"
```

Where:
- `<N>` is the total number of `WindowKey` entries in `TemplateReferenceIndex._index[template_id]`.
- `earliest` is the `WindowKey` at index 0 of the sorted list (smallest `wall_start_ms`).
- `<state>` is the `ScheduleWindowState` of the `ScheduledEntry` at that `WindowKey` (e.g. `"committed"` or `"blocked"`).

### 9.2 Template Rename — VAL-T1-005

**Rule:** A template definition may not be renamed while any `ScheduledEntry` references the current `template_id`, regardless of that entry's `ScheduleWindowState`. No partial rename is permitted.

**Enforcement procedure:**

Identical lock acquisition order as VAL-T1-004 (positions 1 → 2 → 3). Same race window rationale applies.

**Decision logic:**

1. Look up `old_template_id` in `TemplateReferenceIndex._index`.
2. If any `WindowKey` entries are present: **reject**.
3. If zero references: construct a new `TemplateDef` with `id = new_template_id`, preserving `segments` and `primary_segment_index` from the old definition. Remove the old entry and insert the new entry within the same lock scope.

**Rejection error (VAL-T1-005):**

```
code:    "VAL-T1-005"
message: "cannot rename template '<old_template_id>' → '<new_template_id>':
          referenced by <N> window(s);
          earliest: channel=<channel_id> start=<wall_start_ms_iso> (state=<state>)"
```

Same field definitions as VAL-T1-004.

**Post-rename state:** After a successful rename, `TemplateReferenceIndex` contains no entry for `old_template_id` (it was zero before the rename) and no entry for `new_template_id` (no `ScheduledEntry` references it yet). The next horizon build that references `new_template_id` will populate the index in the normal course of commit.

---

## 10. BLOCKED State at Tier 1

`ScheduleWindowState.BLOCKED` is set by `ProgramDirector`, not by the Scheduler. It signals that a Tier 2 resolution attempt for this window encountered a non-retryable failure (currently: VAL-T2-001, template absent at resolution time).

**Scheduler's relationship to BLOCKED state:**

- The Scheduler does NOT set `BLOCKED`.
- The Scheduler does NOT clear `BLOCKED` by mutation. It clears it implicitly by replacing the entry via `rebuild_window`, which creates a new `ScheduledEntry` with `state == COMMITTED` and all `blocked_*` fields set to `None`.
- `build_schedule_horizon` does NOT overwrite a `BLOCKED` entry. A `BLOCKED` entry occupies its `window_key` in `ScheduleRegistry` and will be skipped by any subsequent horizon build for the same key.
- `TemplateReferenceIndex` continues to index `BLOCKED` entries. Operator rebuild (not automatic retry) is required to resolve a `BLOCKED` window.

---

## 11. Lock Ordering

The Scheduler participates in the system-wide global lock ordering defined in `template_runtime.py`:

```
1. TemplateRegistry._lock
2. ScheduleRegistry._lock
3. TemplateReferenceIndex._lock
4. PlaylogRegistry._lock   (Scheduler never acquires this)
```

**Rules for the Scheduler:**

- When acquiring multiple locks, always acquire in ascending position order.
- Never acquire a lock at a lower position number while holding a lock at a higher position number.
- Single-lock operations may acquire any one lock independently without considering order.
- The Scheduler never acquires `PlaylogRegistry._lock` (position 4).

**Operations and their lock sets:**

| Operation | Locks acquired | Order |
|---|---|---|
| `build_schedule_horizon` | ScheduleRegistry(2), TemplateReferenceIndex(3) | 2 → 3 |
| `rebuild_window` | ScheduleRegistry(2), TemplateReferenceIndex(3) | 2 → 3 |
| `delete_template` | TemplateRegistry(1), ScheduleRegistry(2), TemplateReferenceIndex(3) | 1 → 2 → 3 |
| `rename_template` | TemplateRegistry(1), ScheduleRegistry(2), TemplateReferenceIndex(3) | 1 → 2 → 3 |

---

## 12. Validation IDs Covered by This Document

| ID | Tier | Condition | Enforcer |
|---|---|---|---|
| VAL-T1-001 | Tier 1 | Duplicate `window_key` in a single horizon build batch | Scheduler (skip on conflict) |
| VAL-T1-002 | Tier 1 | `wall_end_ms <= wall_start_ms` after HH:MM resolution | `_resolve_window_bounds` helper |
| VAL-T1-003 | Tier 1 | Required field absent or mismatched for declared `type` (e.g. `type == "template"` with no `name`) | Config parser (parse-time) |
| VAL-T1-004 | Tier 1 | Template deletion attempted while referenced by any `ScheduledEntry` | Scheduler (mutation-time) |
| VAL-T1-005 | Tier 1 | Template rename attempted while referenced by any `ScheduledEntry` | Scheduler (mutation-time) |

Parse-time failures (VAL-PARSE-* series) that precede Tier 1 build — including field type errors, unknown entry types, missing required fields, and `primary_segment_index` inference failures — are defined and enforced by the config parser layer. They are outside the scope of this document and are catalogued in `docs/domains/ProgramTemplateAssembly.md`.

Tier 2 failures (VAL-T2-* series) that trigger `BLOCKED` state transitions are outside the scope of this document and are owned by `ProgramDirector`.

---

## 13. Non-Goals

This document does not define and the Scheduler does not own:

- **Segment resolution:** The Scheduler does not resolve template segments to concrete assets. This is Tier 2 behavior owned by `ProgramDirector`.
- **PlaylogWindow lifecycle:** The Scheduler does not read, write, or transition `PlaylogWindowState`. It does not know whether a `PlaylogWindow` exists for any committed entry.
- **Tier 2 staleness handling:** The Scheduler does not trigger Tier 2 discards or rebuilds. It issues a new `window_uuid` on rebuild; `ProgramDirector` detects the staleness signal on its next `extend_horizon` call.
- **Asset approval and availability:** Asset approval state is an `AssetCatalog` concern evaluated at Tier 2.
- **EPG derivation from asset metadata:** EPG title derivation from the primary content asset is a Tier 2 concern. The Scheduler stores only the operator-committed `epg_title` string (or `None`).
- **Filler scheduling:** Gaps between resolved events and `wall_end_ms` are handled by the channel-level filler system, not by the Scheduler.
- **Bleed extension duration calculation:** The Scheduler stores `allow_bleed` as a flag. The extent of any bleed is determined by the runtime duration of the last resolved event; the Scheduler has no knowledge of content durations.
- **TemplateRegistry content:** The Scheduler does not define, parse, or validate template segment composition. It stores `name` (a `template_id` string reference) and nothing more.

---

## 14. Test Coverage

The following test files are expected to exist and cover the behavioral contracts defined in this document. These files may not yet exist; their absence is a coverage gap.

### `pkg/core/tests/contracts/runtime/test_inv_sched_index_atomicity.py`

Verifies SCHED-INDEX-001: `TemplateReferenceIndex` is always consistent with `ScheduleRegistry` across all Tier 1 mutations.

Expected cases:
- After `build_schedule_horizon`, every `type == "template"` entry in `ScheduleRegistry` has a corresponding `WindowKey` in `TemplateReferenceIndex`.
- After `rebuild_window` replacing a template entry, the old `WindowKey` is absent and the new `WindowKey` is present.
- After `rebuild_window` changing `type` from `"template"` to `"pool"`, the `WindowKey` is removed from the index.
- `BLOCKED` entries remain in the index after `ProgramDirector` sets `state == BLOCKED`.
- Concurrent `build_schedule_horizon` and `rebuild_window` calls leave the index consistent.

### `pkg/core/tests/contracts/runtime/test_inv_tier1_immutability.py`

Verifies that committed `ScheduledEntry` field values are not mutated after commit except through an explicit rebuild that replaces the entry.

Expected cases:
- All non-state fields on a committed entry are identical before and after a `build_schedule_horizon` call on the same channel.
- `rebuild_window` produces a new object with a new `window_uuid`; the old object is no longer present in `ScheduleRegistry`.
- `COMMITTED → BLOCKED` transition (simulated via `_mark_blocked`) changes only `state`, `blocked_reason_code`, `blocked_at_ms`, and `blocked_details`; all other fields are unchanged.
- No field mutation path exists on `ScheduledEntry` other than the four `blocked_*` fields.

### `pkg/core/tests/contracts/test_scheduler_tier1_contract.py`

Integration-level contract tests covering the full Tier 1 authority surface.

Expected cases:
- `build_schedule_horizon` is additive: calling it twice with the same config produces no duplicates and does not overwrite existing entries.
- `build_schedule_horizon` skips `BLOCKED` windows without raising.
- `rebuild_window` on a `COMMITTED` entry replaces it with a new `window_uuid` and `state == COMMITTED`.
- `rebuild_window` on a `BLOCKED` entry replaces it with `state == COMMITTED` and all `blocked_*` fields `None`.
- `delete_template` raises `VAL-T1-004` when any `ScheduledEntry` (state `COMMITTED`) references the template; error message contains the `template_id`, reference count, earliest `window_key`, and state.
- `delete_template` raises `VAL-T1-004` when any `ScheduledEntry` (state `BLOCKED`) references the template.
- `delete_template` succeeds when `TemplateReferenceIndex` has zero entries for `template_id`.
- `rename_template` raises `VAL-T1-005` under the same conditions as `delete_template`; error message contains `old_template_id → new_template_id`, reference count, earliest `window_key`, and state.
- `rename_template` succeeds when zero references; resulting `TemplateRegistry` contains `new_template_id` with original `segments` and `primary_segment_index`; `old_template_id` is absent.
- `window_uuid` values are unique across all commits in a build session (no reuse).
- Lock ordering is never violated: acquiring `ScheduleRegistry` and `TemplateReferenceIndex` out of order raises a deadlock-detection assertion (if instrumented).
