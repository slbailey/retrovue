# Domain — Scheduling Contract v1.1

**Status:** Authoritative domain contract (implementation-ready)  
**Supersedes:** Time-splice model replaces broadcast-day-level immutability as the mutation rule (see § Interaction with existing invariants in Schedule Persistence Design).  
**Version:** 1.1  
**Date:** 2026-04-14

---

## Purpose

This specification defines **one** enforceable scheduling model per channel: a **single MasterClock-anchored timeline**, **one** authoritative revision head at any instant, **splice-based** future replacement, and **atomic** persistence rules so EPG, playlog, and playout never observe forked or partial timelines.

---

## 1. Single timeline authority

**Authoritative object**

- For each **channel** `C`, at each wall instant `t` (measured in UTC per MasterClock), there is **exactly one** authoritative editorial timeline: the totally ordered set of **committed** `ScheduleItem` intervals that cover the programmed axis for `C`, with **no overlaps** and **no duplicate coverage** of time (subject only to explicit “dark” or **intentional gap** semantics defined for `C` elsewhere; this contract treats gaps as explicit states, not ambiguous duplicates).

**Revision head**

- The **active schedule revision** for `C` is the unique revision identifier `R_active` such that:
  - `R_active.status = active` for `C`, and
  - there is **no** other revision for `C` with `status = active` in the same scope record the persistence layer maintains (exactly one active head per channel).

**Supersession**

- When a new revision `R_new` is successfully published, `R_active` transitions to `superseded` and `R_new` becomes the sole `active` revision for `C` in **one database transaction**. There is **never** a period where two revisions are both `active` for `C`.

**Resolution at instant `t`**

- The schedule truth at `t` is **only** the set of `ScheduleItem` rows owned by `R_active` (after commit). Queries for “what is scheduled at `t`?” **must** use `R_active` and MasterClock `now`; they **must not** merge rows from superseded revisions except for **historical read APIs** that explicitly query by revision id or `as_of` time.

**No ambiguity**

- **Forbidden:** multiple concurrent `active` revisions for one channel; playout or EPG choosing “newer draft” or “in-memory winner”; mixing `ScheduleItem` rows from `R_active` and `R_superseded` for forward-looking editorial answers.

---

## 2. Revision supersession model — splice (prefix preserved, suffix replaced)

This contract adopts **one** model: **revision splice**. There is **no** alternate publish path.

**Definitions (MasterClock `now`)**

Let `now` be the single `MasterClock` instant used inside the publish transaction (read once at transaction start; all classifications use this value).

For each `ScheduleItem` `I` with half-open interval `[start_utc, end_utc)`:

- **Sealed:** `end_utc ≤ now` — already fully aired; immutable forever.
- **Live:** `start_utc ≤ now < end_utc` — currently airing; immutable until it ends (editorial freeze of the whole interval).
- **Pending:** `now < start_utc` — not yet started; replaceable in a splice.

**Splice input**

- The publisher supplies **only** an ordered list `S_new` of **Pending** items: every item in `S_new` **must** satisfy `start_utc > now` when evaluated with the **same** `now` as the transaction. **No** Sealed or Live item may appear in `S_new`.

**Splice construction**

- Let `T_old` be the ordered list of all `ScheduleItem` rows for `R_active` before publish, sorted by `start_utc` ascending.
- **Preserved prefix** `P` is the subsequence of `T_old` consisting of every item that is **Sealed** or **Live**. Equivalently: **`P` = all items in `T_old` with `start_utc ≤ now`** (sorted by `start_utc`). That is exactly **Sealed ∪ Live**.
- **Discarded:** every **Pending-old** item (`now < start_utc`) in `T_old` is removed and **not** carried into `R_new`.
- **Suffix:** `S_new` replaces **all** Pending-old items. The post-splice timeline row list is **`T_new = P ∥ S_new`** (concatenation), in `start_utc` order — `S_new` must already be sorted ascending and must be **pairwise non-overlapping** and **gap-legal** per channel rules.

**Join constraint (mandatory)**

- Let `last_end` be the maximum `end_utc` among items in `P` (if `P` is empty, `last_end` is undefined and channel-specific open-day rules apply). If `P` is non-empty, the first item of `S_new` **must** satisfy `start_utc == last_end` **unless** an explicit **authorized gap** (dark window) is allowed at that join; if gaps are not allowed, equality is **required**. If `P` is empty, `S_new` must satisfy channel day-open / carry-in rules.

**How past items are preserved**

- Every Sealed item in `P` is copied into `R_new` **byte-for-byte** for all editorial fields that define *what airs* (times, content identity, structural keys). Database primary keys may change if the implementation copies rows; **editorial identity** is preserved by the copy operation, not by mutating rows in place.

**How the current (Live) item is preserved**

- The unique Live item in `T_old` (if any) appears **unchanged** in `P` and is copied into `R_new` in full. The splice **never** truncates, splits, or replaces the Live item.

**How future items are replaced**

- All Pending-old items are **dropped** from the authoritative timeline and **supplanted** by `S_new`. The **only** future editorial state after commit is `S_new` (plus join validation).

**Storage shape**

- `R_new` is stored as a **full snapshot** of `T_new` (complete ordered `ScheduleItem` set for the revision). The splice is the **only** allowed way to construct `T_new` from `T_old` and publisher input; hand-built snapshots that skip validation against `P` are **rejected**.

---

## 3. Boundary behavior

**Single `now`**

- The publish transaction reads **`now` once** at entry. All Sealed / Live / Pending classifications use that instant.

**Exact boundary `now`**

- Intervals are **half-open** `[start_utc, end_utc)`.
- If `now == start_utc`, the item is **Live** (not Pending).
- If `now == end_utc`, the item is **Sealed** (the interval has completed; `end_utc` is exclusive, so airtime in `[start, end)` has finished).

**Current item detection**

- **Live** iff `start_utc ≤ now < end_utc`. At most **one** such item may exist for `C` in `T_old` under non-overlap rules; if zero, nothing is Live.

**Protection**

- Any publish that would alter a Sealed or Live item **rejects**. The splice algorithm **never** includes Sealed or Live from `S_new` and **never** modifies rows in `P` — only copies them.

**Partial overlap with boundary**

- **Not allowed.** Items are well-formed intervals; the splice does not create partial items. A Pending-old item is **entirely** removed or **entirely** retained only if it becomes Sealed/Live by waiting — which is not a publish operation. Publishers cannot submit “half replacements.”

---

## 4. Item identity and matching

**Identity classes**

- **Surrogate identity:** `schedule_item_id` (or equivalent) is a **stable row identifier** within a revision **after** commit. It is **not** used to match editorial sameness across revisions for validation of splice copies; it tracks storage rows.

- **Editorial identity** (for audit and conflict detection): the tuple  
  **`(channel_id, start_utc, end_utc, content_ref, structural_variant_id)`**  
  where `content_ref` is the canonical asset/program identifier for *what* airs, and `structural_variant_id` encodes any compile-stable disambiguation (e.g. episode, template id) required by Core. Exact field set is fixed by the schema; this contract requires that tuple to be **complete** for equality checks.

**Same item vs replacement**

- **Within one revision:** two rows with overlapping time ranges are **forbidden** (reject).
- **Across splice:** a row in `R_new` copied from `P` is **the same editorial item** as the source row if all fields in the editorial tuple match. The implementation **copies** preserved rows; **replacement** applies **only** to Pending-old rows superseded by `S_new` entries. New future rows are **new** editorial identities (new surrogate ids).

**Conflict rejection**

- **Reject** publish if:
  - any item in `S_new` has `start_utc ≤ now`;
  - any overlap exists within `S_new` or between `P` and `S_new` (except at the join point `last_end` as specified);
  - `T_new` violates ordering, contiguity, grid, or carry-in invariants;
  - any invariant requires a unique Live item and the data would imply two Live items.

---

## 5. Atomic publish guarantee

**Meaning of atomic publish**

- **Atomic publish** means: one **ACID transaction** in which (1) validation runs, (2) `R_active` is superseded, (3) `R_new` is inserted as the sole `active` revision, (4) all `ScheduleItem` rows for `R_new` are written, (5) transactional caches or derived pointers used for read consistency are updated **within the same commit** (or are **invalidated** in the same commit so no stale read path wins).

**Immediately after successful commit — must all hold**

- **EPG:** forward queries using `now` **read only** `R_new`. The Sealed and Live portions match the pre-publish timeline; all future listings reflect **only** `S_new`.

- **Playlog horizon:** materialized playlog rows within the defined rolling horizon are **either** updated in the same transaction **or** marked stale in a way that forces regeneration from `R_new` before any playout request is served — **no** playlog row may assert a future Pending-old item still exists after publish.

- **Playout:** the next plan built after commit selects segments from **`R_new`**. It **must not** emit editorial content for any instant `≥ now` from superseded Pending-old items. Live and Sealed playback facts are unchanged.

---

## 6. Failure modes

**Publish rejects (non-exhaustive but mandatory)**

- More than one `active` revision would result (constraint violation).
- `S_new` contains any item with `start_utc ≤ now`.
- Join between `P` and `S_new` violates contiguity / gap rules.
- Overlap or ordering violation in `T_new`.
- Attempt to modify Sealed or Live rows in place or to omit required copies into `R_new`.
- MasterClock regression or unset clock (implementation-defined single failure class): **reject** — do not classify boundaries.

**Must never happen**

- **Partial updates:** some `ScheduleItem` rows from `S_new` visible while others are not; `R_new` half-written without supersession of `R_old`.
- **Mixed revision states:** EPG showing `R_new` futures while playlog still lists Pending-old futures; playout reading `_blocks` not invalidated from `R_old`.
- **Forked timelines:** two different future sequences both reachable as “active” for `C` at the same `now` from different APIs or caches.

---

## Non-goals

- Broadcast-day labels as **authority** for mutability (labels remain reporting keys only).
- Editorial mutation of Sealed or Live intervals.
- Any second MasterClock or second active head per channel.

---

## Alignment

- All time comparisons use **MasterClock**; schedule intervals use **absolute UTC**; splice logic is **enforceable** with row-level constraints: single `active` revision per channel, non-overlapping items per revision, transactional supersession plus full snapshot write for `R_new`.
