# Domain — Schedule Persistence Design v1.0

**Status:** Authoritative persistence design (Postgres + SQLAlchemy)  
**Aligns with:** [SCHEDULING-CONTRACT-v1.1.md](SCHEDULING-CONTRACT-v1.1.md)  
**Version:** 1.0  
**Date:** 2026-04-14

---

## Persistence model

**ScheduleRevision — responsibilities**

- Holds **metadata** for one **version** of the channel’s editorial schedule: identity, lifecycle state, timestamps, optional provenance (compilation id, operator id, reason).
- Owns **exactly one** full snapshot of `ScheduleItem` rows for that version (no partial revision without items).
- Carries **no** independent timeline authority beyond pointing to its child items; “truth at `t`” is always **items of the single active revision** for the channel.
- Optional columns such as `broadcast_day` (or `scope_label`) are **reporting / retention / UI** metadata only; they **must not** participate in mutability or uniqueness rules beyond secondary indexes.

**ScheduleItem — responsibilities**

- Represents one **half-open** program interval `[start_utc, end_utc)` in absolute UTC.
- Carries **editorial identity**: canonical content reference(s), duration, structural disambiguation fields required by Core (aligned to v1.1 editorial tuple).
- Is **always** bound to exactly one `revision_id` (and, if denormalized for constraints, `channel_id` duplicated from the parent revision for indexing).

**Relationship between revisions and items**

- **One-to-many:** `ScheduleRevision` → many `ScheduleItem` rows.
- A revision’s items form the **ordered** timeline snapshot `T` for that version; together they are the full authoritative state that revision represents.
- **No** item may reference more than one revision; **no** shared item rows across revisions (copies on splice, not shared pointers).

**Enforcing “active revision”**

- **Rule:** At most **one** row per `channel_id` may have `status = 'active'`.
- **Mechanism (Postgres):** a **partial unique index** on `(channel_id)` **where** `status = 'active'` (and optionally `WHERE status IN ('active')` with enum). This is the persistence anchor for **single timeline authority**: the active head is unique per channel.
- Drafts use `status = 'draft'` and do not participate in read paths for canonical schedule until promoted in the same transaction as splice + supersession.

---

## Writer behavior (CRITICAL)

**Procedure:** `write_active_revision_from_compiled_schedule` (name illustrative; one entry point for automated splice publish).

**Inputs:** `channel_id`, compiled **future-only** suffix `S_new` (ordered `ScheduleItem`-shaped payloads with `start_utc > now` for every row, using the transaction’s `now`), plus any metadata required to construct `R_new`.

**Steps (must run in order inside one transaction; see Transaction model):**

1. **Load current active revision (`R_active`)** — Select the row where `channel_id = :channel_id` and `status = 'active'`. **`SELECT … FOR UPDATE`** on `R_active` (or equivalent row lock) so no concurrent writer supersedes it between load and commit.

2. **Compute `now` from MasterClock** — **Single read** of `now` at the start of the write body (after locks acquired). All classifications (Sealed / Live / Pending-old) and all validation of `S_new` use **this** instant only.

3. **Build preserved prefix `P`** — Load all `ScheduleItem` rows for `R_active` ordered by `start_utc` ascending (`T_old`). `P` = every item `I ∈ T_old` such that `I.start_utc ≤ now` (equivalently Sealed ∪ Live per v1.1). Do **not** copy Pending-old rows into `P`.

4. **Validate `S_new` (future-only)** — Reject if `S_new` is empty when the operation is not allowed to produce an empty future (channel rules); otherwise allow only if contract permits. Reject if **any** item has `start_utc ≤ now`. Reject overlaps, wrong order, or illegal gaps **within** `S_new`.

5. **Validate join between `P` and `S_new`** — If `P` is non-empty: let `last_end` = end of the last item in `P` (sort order). First item of `S_new` must satisfy the v1.1 join rule: `start_utc == last_end` unless an **explicit authorized gap** is allowed for that channel; if not allowed, equality is mandatory. If `P` is empty: validate `S_new` against channel open-day / carry-in rules.

6. **Construct `T_new`** — `T_new = P ∥ S_new` (concatenation in `start_utc` order). Re-run **global** non-overlap and ordering checks on `T_new`.

7. **Create `R_new`** — Insert a new `ScheduleRevision` row; status transitions to `active` only within the same transaction after items exist (insert as `draft` then flip, or insert `active` only after validation — no intermediate commit).

8. **Insert `ScheduleItem` rows for `T_new`** — For each row in `T_new`, insert a new `ScheduleItem` with `revision_id = R_new.id`. Preserved rows from `P` are **copies** (new primary keys), not updates to old rows.

9. **Supersede `R_active`** — Set `R_active.status = 'superseded'`, `R_active.superseded_at = now` (or transaction timestamp). Set `R_new.status = 'active'`.

10. **Commit atomically** — Single `COMMIT`. Until commit, no other session may observe `R_new` as active.

---

## Data integrity rules

**Multiple active revisions**

- **Partial unique index:** `UNIQUE (channel_id) WHERE status = 'active'` on `schedule_revision`. Application must not bypass with soft flags; `status` is the sole discriminator.

**Overlapping `ScheduleItem` rows**

- **Per revision:** no two items for the same `revision_id` may have overlapping `[start_utc, end_utc)`.
- **Preferred DB enforcement:** `EXCLUDE USING gist` on `(revision_id WITH =, tstzrange(start_utc, end_utc, '[)') WITH &&)` **requires** `btree_gist` and consistent `tstzrange` bounds, **or** a **constraint trigger** / deferred check that asserts no overlaps for a given `revision_id`.
- **Minimum:** deferrable constraint trigger validating non-overlap on insert/update to `schedule_item` for the revision being built.

**Ordering**

- **Unique `(revision_id, start_utc)`** to forbid duplicate starts.
- **Check constraint or trigger:** items are strictly ordered by `start_utc` with each `end_utc` equal to the next `start_utc` when gaps are disallowed; when gaps are allowed, only non-overlap and join rules apply (as validated in the writer).

**Channel consistency**

- Every `ScheduleItem.channel_id` (if denormalized) **must** match its `ScheduleRevision.channel_id` — enforced by trigger or by insert only through a single repository API that sets both.

---

## Transaction model

**Inside one transaction**

- Lock `R_active` (`FOR UPDATE`).
- Read MasterClock `now` once.
- Read `T_old`, build `P`, validate `S_new`, build `T_new`.
- Insert `R_new`, insert all items for `T_new`, update `R_active` and `R_new` statuses.
- Invalidate or refresh any **same-connection** session state required for consistency (no cross-session cache writes that must be visible before commit — those belong to post-commit hooks or “read through” invalidation).

**Must not leak outside the transaction**

- Partial inserts for `R_new` without supersession of `R_active`.
- `R_new` visible as `active` before all `ScheduleItem` rows exist.
- `R_active` superseded while reads could still return its old future Pending items from a cache keyed only by time.

**Race prevention**

- **Mandatory** row-level lock on the current active `ScheduleRevision` for the channel before any read of `T_old` used for splice.
- **Optional:** `pg_advisory_xact_lock(hashtext('schedule:' || channel_id::text))` for the duration of the transaction to serialize all schedule writers for that channel (defense in depth if any path bypasses revision row lock).
- Readers of canonical schedule use `READ COMMITTED` (default) and see **only** committed `active` revision + items; no uncommitted draft.

---

## Interaction with existing invariants

**Replaces `INV-TIMELINE-BOUNDARY-IMMUTABLE-001`**

- That invariant tied immutability to **broadcast-day** and “any item started ⇒ whole day frozen.” It is **retired** as the mutability rule and superseded by **time-splice** semantics.

**New invariants (conceptual IDs — register in `INVARIANTS.md` when implemented)**

- **`INV-SCHEDULE-SPLICE-001`:** Publish **only** via splice: `P` from `T_old` using `now`; `S_new` strictly future; `T_new = P ∥ S_new`; full snapshot under new revision; supersede prior active in one transaction.
- **`INV-SINGLE-ACTIVE-REVISION-001`:** At most one `ScheduleRevision` with `status = 'active'` per `channel_id` (enforced by partial unique index).
- **`INV-SCHEDULE-NO-OVERLAP-001`:** No overlapping `ScheduleItem` intervals within the same `revision_id`.
- **`INV-MASTER-CLOCK-BOUNDARY-001`:** A single MasterClock read classifies Sealed / Live / Pending for a given publish; no mixed `now` within one transaction.

Together these replace the **behavioral** guarantee of the old boundary invariant with **explicit** prefix preservation and future replacement.

---

## Failure handling

**Causes of rejection**

- Validation failure on `S_new` (not strictly future, internal overlap, illegal gaps).
- Join failure between `P` and `S_new`.
- `T_new` fails non-overlap or channel grid/carry-in rules.
- Unique constraint violation on `(channel_id)` active (should not occur if locking is correct; indicates a bug or bypass).
- Exclusion / overlap constraint violation on insert.

**Rollback guarantees**

- Any rejection **before** commit **must** leave **`R_active` unchanged** and **must not** insert `R_new` or orphan items. Standard transaction **ROLLBACK** clears all effects.

**Must never be partially written**

- `R_new` in `active` state without a complete `T_new` item set.
- `R_active` superseded without `R_new` active.
- Items from two revisions both referenced as canonical for overlapping future time.

---

## Compatibility considerations

**Existing `ScheduleRevision` data**

- Rows with `status = 'superseded'` remain **historical**; unchanged.
- Rows with `status = 'active'` today may exist **per `(channel_id, broadcast_day)`** in legacy schemas. **Migration** must reconcile to **at most one active per `channel_id`**: e.g. pick the authoritative active row per policy (latest `created_at`, or the row containing Live/`now`), supersede others, **or** merge item sets into one new active revision via a one-time splice-like copy (offline migration job).

**Migration required**

- **Yes**, if the current unique constraint is `(channel_id, broadcast_day)` for active rows: replace with **`UNIQUE (channel_id) WHERE status = 'active'`** (and drop conflicting partial unique if present). Add overlap / ordering protections on `schedule_item` if missing.

**Legacy revisions validity**

- **Superseded** revisions remain valid **as history** (audit, as-run alignment). They **must not** be used for forward EPG, playlog materialization, or playout after supersession. After migration, any **duplicate active** rows per channel must be resolved to zero before enforcing the new index in production.

---

## Alignment with Scheduling Contract v1.1

- **Splice:** Implemented by writer steps 3–6; preserved rows are **copies** into `R_new`.
- **Atomic publish:** Steps 7–10 in **one** transaction.
- **Single timeline authority:** Partial unique index on active revision per channel + `FOR UPDATE` on `R_active` + no mixed revision reads for canonical paths.
