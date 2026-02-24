# Patch Plan: Tick Cadence → Frame-Selection Cadence (Semantic Alignment)

**Goal:** Align code naming and logs with invariants. No behavior change.

**Contract distinction:**
- **Tick cadence (tick grid)** = when output ticks fire; fixed by session output FPS (house format). INV-FPS-RESAMPLE, INV-TICK-DEADLINE-DISCIPLINE-001.
- **Frame-selection cadence** = repeat-vs-advance policy per tick (e.g. 23.976→30 upsample); refreshed on segment swap. INV-FPS-MAPPING.

---

## Rename Scheme

| Old | New |
|-----|-----|
| `tick_cadence_enabled_` | `frame_selection_cadence_enabled_` |
| `tick_cadence_budget_num_` | `frame_selection_cadence_budget_num_` |
| `tick_cadence_budget_den_` | `frame_selection_cadence_budget_den_` |
| `tick_cadence_increment_` | `frame_selection_cadence_increment_` |
| `InitTickCadenceForLiveBlock` | `InitFrameSelectionCadenceForLiveBlock` |
| `RefreshTickCadenceFromLiveSource` | `RefreshFrameSelectionCadenceFromLiveSource` |
| `on_cadence_refresh` (callback) | `on_frame_selection_cadence_refresh` |
| Log `TICK_CADENCE_INIT` | `FRAME_SELECTION_CADENCE_INIT` |
| Log `TICK_CADENCE_DISABLED` | `FRAME_SELECTION_CADENCE_DISABLED` |
| Log `CADENCE_REFRESH` | `FRAME_SELECTION_CADENCE_REFRESH` |

---

## Files and Symbols

| File | Changes |
|------|---------|
| **pkg/air/include/retrovue/blockplan/PipelineManager.hpp** | Callbacks struct: `on_cadence_refresh` → `on_frame_selection_cadence_refresh`; comment "tick cadence" → "frame-selection cadence". Member vars: `tick_cadence_*` → `frame_selection_cadence_*`. Method decls: `InitTickCadenceForLiveBlock` → `InitFrameSelectionCadenceForLiveBlock`, `RefreshTickCadenceFromLiveSource` → `RefreshFrameSelectionCadenceFromLiveSource`. Comments above members and methods updated. |
| **pkg/air/src/blockplan/PipelineManager.cpp** | All references to the above symbols; function defs; log strings `TICK_CADENCE_*` / `CADENCE_REFRESH` → `FRAME_SELECTION_CADENCE_*` / `FRAME_SELECTION_CADENCE_REFRESH`. Comments: add "Tick grid is fixed by session output FPS (house format)." and "This function only updates repeat-vs-advance policy (frame-selection cadence)." |
| **pkg/air/tests/contracts/BlockPlan/SegmentSeamRaceConditionFixTests.cpp** | `on_cadence_refresh` → `on_frame_selection_cadence_refresh`; comment "tick cadence" → "frame-selection cadence" in test description. (Fixture vars `cadence_refreshes_`, `WaitForCadenceRefresh`, etc. kept for minimal diff; they still mean "frame-selection cadence refresh" and tests don't depend on log text.) |
| **pkg/air/docs/contracts/semantics/TIMING-AUTHORITY-OVERVIEW.md** | New subsection: "Naming: tick cadence vs frame-selection cadence." |
| **pkg/air/docs/contracts/INVARIANT-AUDIT-HOUSE-FORMAT-TICK-CADENCE.md** | Update references to use new names (optional; keeps audit accurate). |

---

## Logic / behavior

- No changes to tick timing, scheduling, or Bresenham math.
- Only identifiers, comments, and log string prefixes.
