# Runtime Lifecycle Authority — v1.0

**Status:** Binding
**Owner:** Core / ChannelManager + ProgramDirector
**Last revised:** 2026-03-02
**Related documents:**
- `docs/domains/SchedulerTier1Authority_v1.0.md` — Tier 1 commitment rules
- `docs/domains/ProgramTemplateAssembly.md` — template DSL and segment resolution
- `pkg/core/src/retrovue/runtime/template_runtime.py` — canonical runtime structure definitions

---

## 1. Purpose

This document defines what happens to RetroVue Core's in-memory runtime state across a process restart. It specifies:

- Which runtime structures are rebuilt from durable storage on startup.
- Which structures are discarded and start empty.
- Whether BLOCKED state is restored or lost.
- Whether `window_uuid` survives a restart.
- Whether an in-progress (ACTIVE) window resumes playback or restarts from the beginning.

This document is binding. Any cold-start or warm-start logic must conform to the rules stated here.

---

## 2. Layer Recap

The runtime model is divided into four layers. Each layer has a distinct persistence posture.

```
L0  TemplateRegistry   — live template definitions from channel config
L1  ScheduleRegistry
    TemplateReferenceIndex
L2  PlaylogRegistry
L3  ChannelActiveState
L4  ChannelRuntimeState (coordinator; not persisted directly)
```

The two relevant storage backends are:

- **Postgres** — durable relational store; owned by Core; survives restart.
- **In-memory** — process-local Python dataclass instances; destroyed on restart.

---

## 3. What Survives a Restart

### 3.1 L0 — TemplateRegistry

**Persistence:** Config file (channel YAML); not Postgres.

TemplateRegistry is rebuilt from the channel config file on every startup. It is never written to Postgres. The in-memory `TemplateRegistry` is reconstructed by the Config loader as part of channel registration.

**After restart:** `TemplateRegistry._templates` is repopulated from the channel YAML. Template definitions are identical to what was in effect before the restart if the config file has not changed. The in-memory object identity is new.

### 3.2 L1 — ScheduleRegistry

**Persistence:** Postgres.

`ScheduledEntry` records are the canonical durable form of Tier 1 commitments. Each `ScheduledEntry` (including its `window_uuid`, `state`, and all `blocked_*` fields) is persisted to Postgres at commit time and updated on any state transition (COMMITTED → BLOCKED).

**After restart:** `ScheduleRegistry._windows` is rebuilt by loading all persisted `ScheduledEntry` records for the channel from Postgres. The in-memory objects are reconstructed; object identity is new but all field values — including `window_uuid` and `state` — are restored exactly.

### 3.3 L1 — TemplateReferenceIndex

**Persistence:** Derived from ScheduleRegistry; not independently persisted.

`TemplateReferenceIndex` is a read-optimised reverse index maintained in memory alongside `ScheduleRegistry`. It is not independently stored in Postgres.

**After restart:** `TemplateReferenceIndex._index` is reconstructed by scanning the restored `ScheduleRegistry._windows` dict and indexing every `ScheduledEntry` with `type == "template"` under its `name`, regardless of `state`. This reconstruction is equivalent to replaying all committed `build_horizon` and `rebuild_window` operations in sequence. The resulting index is identical in content to what was in effect before the restart.

**Invariant preserved across restart:** SCHED-INDEX-001 — every `ScheduledEntry` of type `"template"` (any state) has a corresponding `WindowKey` in the index. This holds after reconstruction because the reconstruction scan covers all states.

### 3.4 L2 — PlaylogRegistry

**Persistence:** Not persisted. Rebuilt on demand.

`PlaylogRegistry._windows` is an in-memory cache of Tier 2 resolution outputs. It contains `PlaylogWindow` and `PlaylogEvent` objects produced by `ProgramDirector` from the current `TemplateDef` and `AssetCatalog` state. These objects are not written to Postgres.

**After restart:** `PlaylogRegistry._windows` starts empty. ProgramDirector rebuilds the playlog horizon lazily as needed for upcoming windows. There is no recovery path from a pre-restart playlog state.

### 3.5 L3 — ChannelActiveState

**Persistence:** Not persisted. Inferred on startup.

`ChannelActiveState` records which `PlaylogWindow` is currently executing (ACTIVE). Since `PlaylogRegistry` is not persisted, there is no in-memory ACTIVE window to restore.

**After restart:** `ChannelActiveState.active_window_key` is `None`. The channel starts in a "dark" state with no active window. The startup sequence (§5) determines which window to activate next.

---

## 4. BLOCKED State Across Restart

`ScheduleWindowState.BLOCKED` is part of `ScheduledEntry` and is persisted to Postgres along with the full entry.

**After restart:** BLOCKED windows are fully restored. `blocked_reason_code`, `blocked_at_ms`, and `blocked_details` are all present in the reconstructed `ScheduledEntry`. The window remains BLOCKED and is excluded from automatic Tier 2 resolution until an explicit operator `rebuild_window` action issues a new `window_uuid` and resets the state to COMMITTED.

**Consequence:** If a channel was shut down while a window was BLOCKED, the restart does not clear that state. The BLOCKED entry continues to occupy its `window_key` in `ScheduleRegistry`, and subsequent `build_schedule_horizon` calls (additive) will skip it. Operator intervention is required to resolve BLOCKED windows, exactly as before the restart.

---

## 5. window_uuid Across Restart

`window_uuid` is a field on `ScheduledEntry` persisted to Postgres.

**After restart:** `window_uuid` values are fully restored. Every `ScheduledEntry` has the same `window_uuid` it had before the restart.

**Consequence for Tier 2:** If ProgramDirector had built a `PlaylogWindow` before the restart, that window is gone (PlaylogRegistry is not persisted). On the first post-restart `extend_horizon` call, ProgramDirector finds no `PlaylogWindow` for the restored `ScheduledEntry` (existing is `None`). `_decide_build_action` returns `BUILD_NEW`. ProgramDirector builds a fresh `PlaylogWindow` from the current template definition and records the restored `window_uuid` as `source_window_uuid`. This is semantically correct: the `window_uuid` has not changed, so the new `PlaylogWindow` correctly represents the current Tier 1 commit.

There is no `window_uuid` collision risk on restart because `window_uuid` values are UUID4 strings assigned once at commit time and never regenerated unless `rebuild_window` is explicitly called.

---

## 6. Active Window on Restart

Before shutdown, a channel may have been actively executing a `PlaylogWindow` (state == ACTIVE). After restart:

- `PlaylogRegistry` is empty.
- `ChannelActiveState.active_window_key` is `None`.
- The previously ACTIVE `PlaylogWindow` object no longer exists.

**Resolution behavior:**

When the first viewer arrives or when ProgramDirector runs its post-restart horizon extension, it determines which window should be airing at wall-clock "now" by consulting the restored `ScheduleRegistry`. It then resolves that window's `ScheduledEntry` through the normal Tier 2 build path. The resulting `PlaylogWindow` starts in `PENDING` state and is immediately activated.

**Mid-program restart:** If the restart occurred in the middle of a movie or program, the resumed playout does NOT seek to the mid-program position. The channel advances to the point that should be airing at the current wall-clock time, as determined by the schedule and the total duration of resolved events. Viewers experience a "tuning in mid-stream" join, which is normal behavior for a linear broadcast model.

The ACTIVE window freeze invariant (PlaylogWindow.state == ACTIVE → no rebuild) does not apply across restart because no ACTIVE windows survive restart. Every post-restart build starts from PENDING.

---

## 7. Cold Start vs Warm Start

RetroVue does not define a separate "warm start" path. Restart is always treated as a cold start for the in-memory runtime:

| Structure | Cold start behavior |
|---|---|
| `TemplateRegistry` | Rebuilt from channel config YAML |
| `ScheduleRegistry` | Rebuilt from Postgres (all committed entries, all states) |
| `TemplateReferenceIndex` | Derived from rebuilt `ScheduleRegistry` |
| `PlaylogRegistry` | Starts empty |
| `ChannelActiveState` | Starts with `active_window_key = None` |
| `window_uuid` on entries | Restored exactly from Postgres |
| `BLOCKED` state | Restored exactly from Postgres |
| Active window position | Not restored; channel advances to current wall-clock position |

**No partial restart:** There is no mechanism to restore a subset of these structures from a pre-restart snapshot. The above postures are unconditional.

---

## 8. Startup Sequence

The following sequence governs channel runtime initialization after process restart. It is a constraint on the order of operations, not an implementation specification.

1. **Config load:** Config loader reads the channel YAML. Constructs `TemplateRegistry` for the channel.

2. **Tier 1 restore:** Scheduler reads `ScheduledEntry` records for the channel from Postgres. Populates `ScheduleRegistry._windows`.

3. **Index rebuild:** Scheduler reconstructs `TemplateReferenceIndex._index` by scanning all entries in `ScheduleRegistry._windows` with `type == "template"`, inserting each `window_key` under the appropriate `template_id` in ascending `wall_start_ms` order.

4. **Active state init:** ChannelManager initializes `ChannelActiveState` with `active_window_key = None`.

5. **Tier 2 horizon extension:** ProgramDirector runs `extend_horizon` for the channel, building `PlaylogWindow` objects for the time range `[now, now + lookahead]`. BLOCKED windows are skipped (as they are in normal operation). Completed windows prior to `now` are not built.

6. **Activation:** ChannelManager activates the first PENDING `PlaylogWindow` whose `wall_start_ms <= now`. If `now` falls within a window, the first qualifying `PlaylogEvent` is determined by consulting the resolved event durations against wall-clock position.

7. **Channel ready:** The channel is available for viewer connections.

Steps 1–3 must complete before step 5 begins. Step 4 has no ordering dependency on 1–3.

---

## 9. Scheduling Clock Authority on Restart

The scheduling clock does not pause during a process restart. Wall time advances continuously regardless of whether the RetroVue process is running. This is the fundamental model: channels appear 24×7 to viewers; compute is consumed only when viewers exist.

**Consequence:** On restart, `ScheduledEntry` records for windows that ended before the restart are present in `ScheduleRegistry` (with `state == COMMITTED` or `BLOCKED`) but will not be activated. ProgramDirector only builds `PlaylogWindow` objects for the active lookahead range. Windows that ended before `now` are not built and are not activated.

**No catch-up:** RetroVue does not replay or catch up missed windows after restart. The channel resumes as if it has been airing continuously; only the current and future windows are activated.

---

## 10. Non-Goals

This document does not define:

- **Postgres schema** for `ScheduledEntry` persistence. Schema definition is owned by the Core persistence layer.
- **TemplateReferenceIndex persistence.** The index is always derived from `ScheduleRegistry` and is never independently stored or checkpointed.
- **PlaylogWindow or PlaylogEvent persistence.** These are Tier 2 resolution outputs and are always rebuilt from the current template and asset state.
- **DVR, rewind, or catch-up playback.** Restarting mid-program resumes from the current schedule position, not from where playback stopped.
- **AIR process lifecycle.** AIR is a separate playout subprocess. Its startup and teardown are governed by `pkg/air/CLAUDE.md` and are out of scope here.
- **Multi-channel coordinator startup ordering.** Whether channels are started sequentially or concurrently is an orchestration concern, not a lifecycle authority concern.
- **Horizon size on restart.** The lookahead window size after restart follows the same runtime policy as during normal operation.
