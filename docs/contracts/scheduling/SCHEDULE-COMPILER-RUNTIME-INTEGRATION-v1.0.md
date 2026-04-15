# Domain — Schedule Compiler & Runtime Integration v1.0

**Status:** Authoritative integration design  
**Aligns with:** [SCHEDULING-CONTRACT-v1.1.md](SCHEDULING-CONTRACT-v1.1.md), [SCHEDULE-PERSISTENCE-DESIGN-v1.0.md](SCHEDULE-PERSISTENCE-DESIGN-v1.0.md)  
**Version:** 1.0  
**Date:** 2026-04-14

---

## Compiler responsibility

**Primary output**

- The compiler’s **only** persistence-facing product is **`S_new`**: an ordered list of **Pending** `ScheduleItem`-shaped results—every row **must** satisfy `start_utc > now` (using the **same** MasterClock instant the writer will use in the same transaction or an immediately preceding coordination step—see Writer integration).

- The compiler **does not** produce the preserved prefix **`P`**. **`P`** is always **loaded from the database** from the current active revision (`R_active`) by the writer (Schedule Persistence Design v1.0).

**Future window**

- The compiler fills a **forward window** `[compile_start_utc, compile_end_utc)` where:
  - **`compile_start_utc`** is **authoritative input**: it **must** equal the **join anchor**—the instant at which new programming may begin. In normal splice, this is **`last_end`** from **`P`** (end of the last Sealed or Live item in `T_old`). If **`P`** is empty, **`compile_start_utc`** is defined by channel rules (e.g. effective day open / carry-in resolution), not by broadcast-day immutability rules.
  - **`compile_end_utc`** is the **minimum of** (a) the end of the logical compilation scope (e.g. end of the target accounting day’s programmed span) and (b) **`now + H_compile`**, where **`H_compile`** is the **mandatory future coverage horizon** (see S_new generation rules).

**Avoiding past/current items**

- The compiler **must not** emit items with `start_utc ≤ now`. Slots that would have fallen in Sealed or Live time are **not generated**: the **timeline already holds them** in **`P`**.

- DSL / grid / pool logic that historically assumed “a full 24h accounting slice” still runs **internally** as needed for determinism, but **emission** is **clipped** so nothing is emitted before **`compile_start_utc`** and nothing violates **`start_utc > now`**.

---

## Interaction with existing compiler (`_compile_day`)

**Removed (as persistence behavior)**

- Treating “compiled day = full replace of persisted schedule for `(channel, broadcast_day)`.”
- Any step that **materializes or persists** a **full-day** `ScheduleItem` set **without** splice (prefix from DB + suffix from compiler).
- Using **broadcast-day** boundaries to decide **whether** a revision may change (replaced by MasterClock + splice).

**Retained**

- **DSL interpretation**, zone/window semantics, **deterministic seeds** tied to `(channel_id, broadcast_day)` (or equivalent) for **asset selection**, grid alignment, bumpers, pools, templates—everything that defines **editorial shape** for the **future** segment.
- **`_compile_day` (or successor)** as a **named compilation scope** (e.g. “the programming intent for accounting day **D**”) driving **what** fills **`S_new`** for the portion of the timeline that still lies in the future relative to **`now`**.

**Transition: full-day compile → suffix-only**

- **Conceptual change:** `_compile_day` becomes **`_compile_day_suffix`** in responsibility: same internal machinery, but the **external contract** is “generate **`S_new`** for `[compile_start_utc, compile_end_utc)` inside day **D**’s scope,” not “replace the entire day’s rows.”
- **Compile_start** is **not** “start of broadcast day” by default; it is **`last_end`** from **`P`**, which may fall **inside** day **D** after carry-in or mid-day splice.

---

## S_new generation rules

**How far `S_new` must extend**

- **`S_new`** **must** cover every Pending instant from **`compile_start_utc`** up to **`compile_end_utc`** **unless** an explicit **authorized gap** (dark window) is allowed by channel policy—in which case gaps **must** be **explicit** domain objects or **validated** absence-of-programming, never “accidental holes” from under-compilation.

- **`H_compile`** (minimum forward coverage) **must** be large enough that EPG horizon generation, playlog materialization for the rolling playlog window, and playout lookahead for segment planning never see **unfilled** Pending time **for lack of compiler output** when programming is required. Concretely: **`compile_end_utc`** is at least **`now + max(H_epg_slice, H_playlog, H_playout_lookahead)`** capped by the accounting scope, with **`H_*`** taken from existing contracts (EPG = multi-day slice, playlog = hours).

**Ordering and contiguity**

- **`S_new`** is **strictly ordered** by `start_utc` ascending.
- **Adjacent items:** `item[i].end_utc == item[i+1].start_utc` **unless** a **declared gap** is permitted; otherwise **reject** at validation.

**Gaps / dark time**

- **Dark** or **off-air** intervals **must** be represented in a way the writer and validators accept (explicit gap events or explicit “dark” items), **not** as missing rows. Empty **`S_new`** when programming is required **rejects** (aligned with nonempty-programmed-day invariants).

---

## Writer integration

**Passing compiler output**

- A single orchestration path: **`compile → validate S_new → write_active_revision_from_compiled_schedule(channel_id, S_new, metadata)`**.

- **Required pre-writer step:** resolve **`compile_start_utc`**: load **`R_active`**, lock, read **`now`** once, build **`P`**, compute **`last_end`** (or empty **`P`** branch). Set **`compile_start_utc = last_end`** (or channel rule when **`P`** is empty). **Reject** if compiler-produced **`S_new`**’s first `start_utc` ≠ **`compile_start_utc`** when gaps are disallowed.

**Transformations**

- **None** that change editorial meaning: optional **normalization** only (stable ordering, canonical content ids). **No** trimming by the writer except **reject** if compiler violated bounds.

**Guarantees before calling the writer**

- Compiler attests **`S_new`** satisfies: future-only, non-overlap, contiguity (or explicit gaps), join match to **`compile_start_utc`**, and coverage through **`compile_end_utc`** per policy.

---

## Playlog interaction

**After successful splice**

- **Pending-old** playlog rows for instants **strictly after** the join (future relative to superseded state) are **invalid**; they **must not** remain authoritative.

**Approach (single allowed pattern)**

- **Invalidate** future playlog materialization for that channel from **`now`** (or from first affected `start_utc`) **forward**, then **rebuild** from **`R_new`** within the **playlog horizon** in the same transaction **or** in a **subsequent** job that runs **before** any playout request can observe stale playlog—**no** “partial patch” that might leave some rows from **`R_old`** and some from **`R_new`**.

**Forbidden**

- Merging playlog rows from two revisions for overlapping future time.

---

## Playout interaction

**ChannelManager / runtime**

- On successful publish notification (post-commit): **invalidate** in-memory **schedule-derived** structures used to build **future** segments (blocks, playlist slices, cached plans beyond Live).

**Guarantees**

- **Current playback:** the **Live** item is **unchanged** editorially; AIR continues the current segment/plan **without restart** solely due to splice. **No** teardown of the current item because future rows changed.

- **Future playback:** the **next** plan segments built **after** invalidation **must** be derived **only** from **`R_new`** (and playlog rebuilt from **`R_new`**). **No** use of superseded Pending items.

- If a **new** viewer joins **after** publish, **join** and **offset** logic use **`R_new`** for all **Pending** time.

---

## Cache and timeline invalidation

**Must invalidate after publish (post-commit)**

- Per-channel **compiled block cache**, **playlist tail**, **EPG slice cache** for intervals **≥** join anchor, **playlog** materialization for future window.

**Must never cache across revision changes**

- Any structure that maps **absolute time → editorial identity** for **Pending** time **without** a **`revision_id` (or monotonic `revision_seq`)** check.

- **Authoritative** answers **must** read **`R_active`** (or playlog **rebuilt** from it) after invalidation—not a stale `_blocks` list keyed only by channel and time.

---

## Transition strategy

**Moving from full-day compile to suffix-only**

1. **Introduce** orchestration: **`last_end` → compile `S_new` → writer splice** as the **only** automated persistence path for schedule updates.
2. **Change** `_compile_day` callers so they pass **`compile_start_utc`** from **`P`**, not day start only.
3. **Remove** code paths that persist a full day **without** splice.

**Temporary coexistence**

- **Not allowed** for **two persistence semantics** (full-day replace vs splice) in production for the same channel class: **one** writer contract. Short **feature flag** only during rollout, with **migration** completing before general availability.

**Avoid breaking existing channels**

- **Data migration:** reconcile to **single active revision per channel** (Schedule Persistence Design v1.0); **one-time** optional job: load **`R_active`**, if legacy shape, **no-op** or **rewrite** via splice identity copy.
- **Runtime:** after deploy, **first** compile uses **`last_end`** from DB—may **re-fill** only Pending tail; **does not** rewrite Sealed/Live.

---

## Alignment constraints

- **Persistence:** Compiler supplies **`S_new`** only; writer loads **`P`**, validates join, atomic publish.
- **No broadcast-day mutation logic** for **whether** edits are allowed—only MasterClock **`now`** and splice rules.
- **MasterClock:** single **`now`** per publish; compiler output validated against that **`now`**.
- **Playout:** **no divergence** from canonical **`R_active`** for any **Pending** instant; caches invalidated so future plans always trace to **`R_new`**.
