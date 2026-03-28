# DEEP_ANALYSIS.md — Retrovue Architectural Diagnosis

**Generated:** 2026-03-28 (America/New_York)
**Branch:** `refactor/simplify-single-authority-l3`
**Analyst:** OpenClaw subagent — full read of 10,500+ lines of source code

> **What this document is:** A comprehensive, honest architectural autopsy of the Retrovue Core Python codebase as it exists today. It cites specific files, classes, methods, and line numbers. It is not a summary of what the docs say the system *should* be — it is what the code *is*.

---

## Table of Contents

1. How Did We Get Here?
2. Current Authority Map (verified against code, not docs)
3. Complexity Taxonomy
4. Concrete Simplification Targets (ranked by impact)
5. Ghost Surface (TODO/pass, unused scaffolding)
6. Target Architecture
7. Revised Phase Plan

---

## 1. How Did We Get Here?

### 1.1 The AI Layering Pattern

Retrovue shows the canonical AI-assisted development failure mode: **each session added structure that the previous session's structure "needed,"** without removing what was superseded. This is visible in four strata:

**Stratum A — Original Design (clean):**
The core model is well-conceived: ProgramDirector → ChannelManager → Producer → AIR subprocess over gRPC. Editorial truth lives in SchedulePlan; runtime truth lives in PlaylistEvent/BlockPlan; AIR is the execution engine. This design is sound and worth preserving.

**Stratum B — Early Scaffolding (partially consumed):**
Two Protocol definitions for `ScheduleService` and `ProgramDirector` exist in `channel_manager.py` (lines 98–139) as interfaces for testing. These were correct to add. However, the same `ProgramDirector` class name is used for both the Protocol (line 126) and the concrete class (defined in `program_director.py`). This name collision creates confusion about which `ProgramDirector` is being referenced in type hints and tests.

**Stratum C — Mock proliferation (partially vestigial):**
`channel_manager.py` contains `MockGridScheduleService` (line ~1183) and `MockAlternatingScheduleService` (line ~1400). These are production-weight implementations, not lightweight test stubs. Each is >100 lines. The "mock grid" approach was the original development harness; the real DSL schedule service (`DslScheduleService`) has long superseded it as the production path. Yet both remain.

**Stratum D — Parallel HLS stacks (active collision):**
The most damaging AI layering. Two complete HLS delivery systems coexist:

- **Old stack:** `retrovue.streaming.hls_writer.HLSManager` + `HLSWriter` + `HLSSegment` — disk-based, segment files written to disk, served from `/hls/{channel_id}/live.m3u8` and `/hls/{channel_id}/{segment}` (lines 2687–2865 of `program_director.py`)
- **New stack:** `retrovue.runtime.hls.SegmentRing` + `HlsSegmenter` + `ManifestGenerator` + `HlsSessionManager` — in-memory, served from `/channels/{channel_id}/live.m3u8` and `/channels/{channel_id}/seg_{index}.ts` (lines 2895–3078)

Both are instantiated and both have live HTTP endpoints. `INV-HLS-NO-DISK-IO-001` explicitly forbids disk I/O in the new stack — but the old stack still uses disk. `ProgramDirector.__init__` creates `self._hls_manager = HLSManager()` (line 588) for the old stack AND `ChannelManager._init_hls_state()` creates the new `SegmentRing`, `HlsSegmenter`, `ManifestGenerator`, `HlsSessionManager` per channel. Both are wired, both serve, both drain CPU and memory.

**Stratum E — Ghost skeleton (100% dead weight):**
`ProgramDirector` contains a 200-line ghost class body (lines 1642–1805) of `pass`-returning TODO methods: `get_system_health`, `get_channel_status`, `get_all_channels`, `activate_emergency_mode`, `deactivate_emergency_mode`, `enforce_system_policies`, `coordinate_channel_operations`, `monitor_system_performance`, `handle_system_alerts`, `get_emergency_content`, `validate_system_state`. These exist because an AI session planned them before the BlockPlan architecture was established. They are 100% dead weight.

### 1.2 Authority Overlap Introduction

The authority overlaps were introduced by three specific patterns:

1. **Over-parameterization:** `ChannelManager.__init__` takes `program_director` as a concrete instance but the `ProgramDirector` Protocol it uses has only `get_channel_mode()`. This meant CM held a full reference to PD, allowing the callback inversion bug (CM calling PD.stop_channel) that Phase 2 fixed. The fix is in place.

2. **Dual activation paths:** When HLS was introduced as a parallel streaming mode, a second channel activation path was added (`_ensure_channel_active_for_hls`) that parallels the raw TS path. This created a second lifecycle path that could start and stop the channel independently. The phantom session mechanism was the band-aid. The root cause is two activation paths where one should exist.

3. **Naming collision between Protocol and concrete class:** Both `channel_manager.py` and `program_director.py` define things called `ProgramDirector`. The Protocol in `channel_manager.py` (line 126) has a different interface than the concrete class. `ChannelManager.__init__` accepts `program_director: ProgramDirector` typed to the Protocol, but receives the concrete instance. This has caused subtle coupling where CM assumes PD has methods beyond the Protocol.

---

## 2. Current Authority Map (Verified Against Code)

### 2.1 Clock/Timebase

**Designated owner:** `MasterClock` (`runtime/clock.py`)

**Actual code:**

| Component | Usage | Line(s) | Risk |
|---|---|---|---|
| `MasterClock` via `ChannelManager.clock` | All block timing decisions | `channel_manager.py:~900` | Owner — correct |
| `DslScheduleService` | Two bare `datetime.now(timezone.utc)` calls — replaced in Phase 2g | `dsl_schedule_service.py:~1000, 1051` | **FIXED in 652521f** |
| `PlaylistBuilderDaemon` | `datetime.now(timezone.utc)` for DB timestamp at ~line 859 | `playlist_builder_daemon.py` | Medium — not playout-critical but untestable |
| `ProgramDirector._generate_iptv_m3u` | `datetime.now(tz)` for cosmetic display | `program_director.py:2574` | Negligible — logging only |
| `evidence_server.py` | `datetime.now(timezone.utc)` for log timestamps | `evidence_server.py:261,277,294` | Negligible — evidence, not playout |

**Assessment:** Phase 2g fixed the highest-risk cases. `PlaylistBuilderDaemon` remains an untested clock consumer. The invariant `INV-TIME-AUTHORITY-SINGLE-SOURCE` is ~85% enforced.

### 2.2 Segment Window (HLS)

**Designated owner per INV-HLS-RING-* invariants:** `SegmentRing` (`runtime/hls/segment_ring.py`)

**Actual code:**

| Component | Usage | Line(s) | Risk |
|---|---|---|---|
| `SegmentRing.push()` | Atomic segment insertion with FIFO eviction | `segment_ring.py:67–87` | Owner — correct |
| `HlsSegmenter.feed()` | Pushes to ring via `_ring.push()` | `segmenter.py:166` | Delegating correctly |
| `ChannelManager.stop_channel()` | `self._hls_segment_ring.clear()` | `channel_manager.py:~530` | Correct — but a "named boundary" would be better |
| `HLSManager` (old stack) | Owns disk-based segment window | `streaming/hls_writer.py:349` | **Parallel owner — VIOLATION** |

**Critical finding:** Two segment windows exist simultaneously per channel. The `SegmentRing` holds in-memory segments for `/channels/{id}/...` endpoints. `HLSManager` holds disk-based segments for `/hls/{id}/...` endpoints. Both are active. `INV-HLS-NO-DISK-IO-001` is violated by the continued existence of the old stack.

### 2.3 Channel Lifecycle

**Designated owner:** `ProgramDirector` (sole teardown authority per `INV-LIFECYCLE-PD-SOLE-TEARDOWN-001`)

**Actual code — post Phase 2:**

| Component | Decision | Line(s) | Risk |
|---|---|---|---|
| `ProgramDirector._get_or_create_manager()` | Creates ChannelManager | `program_director.py:1027` | Owner — correct |
| `ProgramDirector._stop_channel_internal()` | Sole teardown path | `program_director.py:1268` | Owner — correct |
| `ChannelManager._linger_expire()` | Calls `self.on_linger_expired()` (callback to PD) | `channel_manager.py:~730` | **FIXED in 1ce56d8** |
| `ChannelManager._start_linger()` | Falls back to direct `_stop_producer_if_idle` if no loop/callback | `channel_manager.py:~705` | Residual risk — see below |

**Residual risk in `_start_linger()`** (line ~705):
```python
else:
    # No event loop — do full teardown immediately
    if self.on_linger_expired is not None:
        self.on_linger_expired()
    else:
        self._channel_state = "STOPPED"
        self._stop_reason = "last_viewer_left"
        self._stop_producer_if_idle()
```
The `else` branch (when `on_linger_expired is None`) still does teardown directly inside CM. In the refactored production path, `on_linger_expired` is always injected by PD. But the `else` branch remains as defensive code that re-introduces the CM-drives-teardown pattern for any code path that creates a `ChannelManager` without the callback (tests, for example). This should be converted to an assertion: `assert self.on_linger_expired is not None`.

**Second residual risk — dual activation paths:**
`ProgramDirector._ensure_channel_active_for_hls()` (line 1868) is an alternative channel start path used by the `/channels/{id}/live.m3u8` endpoint. It calls `_get_or_create_manager()` then `tune_in()` with a phantom session ID. The raw TS path (via `/channel/{id}.ts`) uses `start_channel()` → `_get_or_create_manager()`. These two paths converge on the same `_get_or_create_manager()` but the HLS path has 130 lines of additional startup logic (socket draining, phantom management, fanout wiring) that the raw TS path does not. This is a lifecycle fork, not a unified activation model.

### 2.4 Diagnostics

**Designated owner:** `ProgramDirector` (via `_hls_diag_*` methods)

**Actual code:**

| Component | Role | Line(s) | Risk |
|---|---|---|---|
| `ProgramDirector._hls_diag_mode_until` | Per-channel diagnostic window | `program_director.py:~585` | Owner |
| `ProgramDirector._hls_diag_trigger()` | Activation on violations | `program_director.py:663` | Owner |
| `ProgramDirector.hls_diag_event()` | External hook wired to HlsSegmenter | `program_director.py:688` | Coupling point |
| `HlsSegmenter._diagnostic_hook` | Fires into PD from within segmenter | `segmenter.py:74,100` | Reverse dependency: segmenter→PD |
| `ChannelManager._init_hls_state()` | Passes `getattr(self.program_director, "hls_diag_event", None)` to HlsSegmenter | `channel_manager.py:~473` | Cross-boundary callback injection |

**Assessment:** The diagnostic coupling goes CM → PD via the hook injected at `ChannelManager._init_hls_state()`. This means the HlsSegmenter (inside CM) fires events into PD. The chain is: `HlsSegmenter.feed()` → `_diag()` → `diagnostic_hook` → `ProgramDirector.hls_diag_event()`. This is a dependency inversion: the segmenter (owned by CM) has a callback into PD. The Phase 4 target of extracting `HlsDiagnosticsState` into a dataclass will sever this by making the diagnostic state injectable rather than PD-bound.

### 2.5 HTTP Serving

**Designated owner per CLAUDE.md:** `ProgramDirector` (single HTTP server)

**Actual code:** Confirmed — `ProgramDirector` owns one FastAPI+uvicorn server on port 8000. All endpoints are registered in `_register_endpoints()`. This is architecturally clean.

**However:** The endpoint surface has grown to include:
- `/channel/{id}.ts` — raw MPEG-TS (raw TS stack, old fanout model)
- `/hls/{channel_id}/live.m3u8` — old HLS stack (disk-based)
- `/hls/{channel_id}/{segment}` — old HLS stack segments
- `/channels/{channel_id}/live.m3u8` — new HLS stack (in-memory SegmentRing)
- `/channels/{channel_id}/seg_{index}.ts` — new HLS stack segments
- `/test/block/{block_id}.ts` — ephemeral test session endpoint
- `/test/segment/{asset_id}.ts` — `return 501` stub
- `/test/channel/{channel_id}.ts` — `return 501` stub

Three dead endpoints (501 stubs), two parallel HLS stacks. The HTTP surface is 2x larger than needed.

### 2.6 Schedule/Planning Authority

**Designated owner:** `DslScheduleService` for production channels; `SchedulePlan`/`ScheduleDay` derivation chain per LAW-CONTENT-AUTHORITY.

**Actual code:** `DslScheduleService` is the exclusive production path. `MockGridScheduleService` and `MockAlternatingScheduleService` exist only for development harness use. All three are in `channel_manager.py` — but they should be in a `testing/` or `fixtures/` module, not in the production `channel_manager.py` file.

**Key clean invariant:** `INV-CHANNELMANAGER-NO-PLANNING-001` is enforced — CM calls `schedule_service.get_block_at()` and `schedule_service.get_playout_plan_now()` as read-only queries. It never writes schedule state.

### 2.7 Producer Management

**Designated owner:** `ChannelManager` (per-channel)

**Actual code:** Confirmed. `ChannelManager._build_producer_for_mode()` creates the `BlockPlanProducer`. `_ensure_producer_running()` is the single producer lifecycle method. `stop_channel()` tears down the producer. PD does not directly manage producer state except during global teardown (`stop()` method iterates managers and calls `.stop()` on active producers).

**One violation:** In `_get_or_create_manager()` (line 1103), PD monkeypatches `manager._build_producer_for_mode` with a `factory_wrapper` closure:
```python
def factory_wrapper(mode: str, cfg: ChannelConfig = cfg) -> Optional[Any]:
    return _cm_build(manager, mode)
manager._build_producer_for_mode = factory_wrapper
```
This is an instance method replacement that bypasses CM's own factory logic. It appears to be vestigial from an earlier multi-factory design. In the current codebase `_cm_build = ChannelManager._build_producer_for_mode` is the unbound method, and the wrapper calls it with `manager` as self — which does the same thing as calling `manager._build_producer_for_mode(mode)` directly. This wrapper adds zero functionality and should be deleted.

---

## 3. Complexity Taxonomy

### 3.1 Domain-Necessary (keep)

| Source | Reason |
|---|---|
| `BlockPlanProducer._feed_ahead()` credit-based flow control | Domain: backpressure management is inherent to real-time playout |
| `PlayoutSession` gRPC lifecycle (seed/feed/stop) | Domain: Core↔AIR contract boundary |
| `HlsSegmenter` PCR-based keyframe detection | Domain: HLS spec requires keyframe-aligned segments |
| `SegmentRing` bounded eviction with grace margin | Domain: live HLS requires sliding window with safe eviction |
| `DslScheduleService._build_initial()` multi-day compilation | Domain: rolling horizon is required by schedule invariants |
| Linger timeout mechanism | Domain: reuse efficiency (avoid AIR restart on quick reconnect) |
| `INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001` phantom viewer | Domain: HLS clients are polling, not persistent; phantom keeps channel alive |
| Startup prewarm (`_prewarm_channel_schedules`) | Domain: non-blocking startup requires pre-compilation |
| GC freeze/refreeze loop | Domain: Python GC with 100k+ catalog objects requires explicit management |

### 3.2 Accidental (AI layering, duplicate paths, defensive coding — can remove)

| Source | Evidence | Where |
|---|---|---|
| `ProgramDirector` Protocol inside `channel_manager.py` | Redundant; already defined concretely in `program_director.py` | `channel_manager.py:126–139` |
| Old HLS stack (`HLSManager`, `/hls/` endpoints, disk I/O) | Superseded by new SegmentRing stack but never removed | `program_director.py:2687–2865`, `streaming/hls_writer.py` |
| `Playlist` and `PlaylistSegment` dataclasses in `channel_manager.py` | Only consumed by `playlist_schedule_manager.py` (scheduling package, not runtime) | `channel_manager.py:271–316` |
| `ProgramDirector._build_producer_for_mode` monkeypatch wrapper | Zero functional difference from calling CM method directly | `program_director.py:1103–1106` |
| `_start_linger()` fallback branch (no callback, no loop) | Should be `assert on_linger_expired is not None` in production | `channel_manager.py:~705–720` |
| Dual HLS activation paths (`_ensure_channel_active_for_hls` vs `start_channel`) | Should converge into one activation model | `program_director.py:1217–1320, 1868–2055` |
| Two `ScheduleService` Protocol definitions (`channel_manager.py:98` and `program_director.py` has the same structural protocol implied by duck typing) | Fragmentation | `channel_manager.py:98–125` |
| `_hls_manager` (old HLSManager) instantiation in PD | Dead when old HLS stack removed | `program_director.py:588` |

### 3.3 Vestigial (was needed, no longer needed — delete)

| Source | Evidence | Where |
|---|---|---|
| `MockGridScheduleService` (full 150-line mock) | Development harness only; real DSL schedule is in production; this path is gated by `mock_schedule_grid_mode` flag which is never True in production | `channel_manager.py:~1183–1380` |
| `MockAlternatingScheduleService` (100-line mock) | A/B harness; gated by `mock_schedule_ab_mode` flag | `channel_manager.py:~1380–1490` |
| `/test/segment/{asset_id}.ts` — HTTP endpoint | Returns 501 | `program_director.py:~2904–2908` |
| `/test/channel/{channel_id}.ts` — HTTP endpoint | Returns 501 | `program_director.py:~2909–2915` |
| `deferred_teardown_triggered()` | Deleted in Phase 2b — confirmed gone | N/A |
| `compute_jip_position()` | Deleted in Phase 2c — confirmed gone | N/A |
| `_mock_grid_*` methods on ChannelManager | Deleted in Phase 2d — confirmed gone | N/A |
| `StreamingDiagnostics` class | Deleted in Phase 4b — confirmed gone | N/A |
| `_ChannelManagerLaunch` usecase at `retrovue/usecases/__init__.py` | Imported but consumer unclear; needs audit | `usecases/channel_manager_launch.py` |

### 3.4 Aspirational (unimplemented scaffolding — delete immediately)

| Method | Lines | Evidence |
|---|---|---|
| `ProgramDirector.get_system_health()` | 1642–1655 | `return None` via `pass` |
| `ProgramDirector.get_channel_status()` | 1656–1672 | `return None` via `pass` |
| `ProgramDirector.get_all_channels()` | 1673–1685 | `return None` via `pass` |
| `ProgramDirector.activate_emergency_mode()` | 1686–1703 | `return None` via `pass` |
| `ProgramDirector.deactivate_emergency_mode()` | 1704–1718 | `return None` via `pass` |
| `ProgramDirector.enforce_system_policies()` | 1719–1732 | `return None` via `pass` |
| `ProgramDirector.coordinate_channel_operations()` | 1733–1746 | `return None` via `pass` |
| `ProgramDirector.monitor_system_performance()` | 1747–1760 | `return None` via `pass` |
| `ProgramDirector.handle_system_alerts()` | 1761–1777 | `return None` via `pass` |
| `ProgramDirector.get_emergency_content()` | 1778–1790 | `return None` via `pass` |
| `ProgramDirector.validate_system_state()` | 1791–1806 | `return None` via `pass` |
| `BlockPlanProducer.play_content()` | `channel_manager.py:~2250` | `return True` — not used in BlockPlan mode |
| `MockBlockPlanProvider` class | `playout_session.py:~760–850` | Test fixture in production file; never referenced in production code |
| `SystemHealth` dataclass | `program_director.py:456–468` | Only used by `get_system_health()` which returns None |
| `ChannelInfo` dataclass | `program_director.py:470–480` | Only used by `get_channel_status()` which returns None |

---

## 4. Concrete Simplification Targets (Ranked by Impact)

### Target 1 — Delete the old HLS stack (HIGH IMPACT, MEDIUM RISK)

**What:** `retrovue.streaming.hls_writer.HLSManager` + all `/hls/` HTTP endpoints (lines 2687–2865 of `program_director.py`) + `self._hls_manager = HLSManager()` (line 588) + `hls_manager.stop_all()` in `stop()` method.

**Why it's complexity:** Two complete HLS delivery systems running simultaneously. Dual CPU cost (both segment from the same MPEG-TS stream). Disk I/O violation per `INV-HLS-NO-DISK-IO-001`. Double the surface area to debug on reconnect. The new stack (`SegmentRing` + `HlsSegmenter` at `/channels/`) is the canonical path per all new invariants.

**How to remove safely:**
1. Confirm `/channels/{id}/live.m3u8` returns valid manifests in production (smoke test)
2. Update Plex and IPTV client M3U playlist URLs if they point to `/hls/`
3. Delete: `streaming/hls_writer.py` entirely
4. Delete from `program_director.py`: import at line 348, `self._hls_manager` at line 588, `_hls_manager.stop_all()` in `stop()`, `/hls/` endpoint group (lines 2687–2865)
5. Remove `hls_manager` parameter from `ChannelStream.__init__` if only used by old stack

**Risk:** Medium — if any active IPTV/Plex client is configured to use `/hls/` URLs. Audit IPTV config before deletion. The M3U generator already outputs `/channels/` URLs; Plex lineup uses `/channel/{id}.ts` (raw TS), not `/hls/`. So deletion should be safe.

**Contracts affected:** `INV-HLS-NO-DISK-IO-001` (fulfillment, not violation), `INV-HLS-QUIET-POLLING-001`, `INV-HLS-DISCONTINUITY-MARKER-001`.

**Net lines removed:** ~550 lines (hls_writer.py 492 + endpoint group ~60 + imports ~5)

---

### Target 2 — Delete ghost skeleton (11 TODO/pass methods) (HIGH IMPACT, ZERO RISK)

**What:** `get_system_health`, `get_channel_status`, `get_all_channels`, `activate_emergency_mode`, `deactivate_emergency_mode`, `enforce_system_policies`, `coordinate_channel_operations`, `monitor_system_performance`, `handle_system_alerts`, `get_emergency_content`, `validate_system_state` — all in `ProgramDirector`, lines 1642–1806.

**Why it's complexity:** These are aspirational scaffolding that returns `None`. They litter the class with dead methods that appear to exist, making it harder to understand what PD actually *does*. They also pull in `SystemHealth` and `ChannelInfo` dataclasses that are never populated.

**How to remove:** Delete all 11 methods and their docstrings. Delete `SystemHealth` and `ChannelInfo` dataclasses (lines 456–480). Delete `SystemMode` enum if only used by the dead skeleton — check: `SystemMode` IS used in `_system_mode = SystemMode.NORMAL` and `get_channel_mode()`. Keep `SystemMode`. Delete `ChannelStatus` enum (lines 450–455) — only referenced in `ChannelInfo` which will be deleted.

**Risk:** Zero — none of these methods return non-None values. No code path depends on them.

**Contracts affected:** None.

**Net lines removed:** ~200 lines.

---

### Target 3 — Delete mock services from channel_manager.py (HIGH IMPACT, LOW RISK)

**What:** `MockGridScheduleService` (lines ~1183–1380, ~200 lines) and `MockAlternatingScheduleService` (lines ~1380–1490, ~110 lines) in `channel_manager.py`.

**Why it's complexity:** These are development harnesses living in a production module. They are never instantiated in production (gated by `mock_schedule_*` flags that default to False and are only set via CLI). `channel_manager.py` is already 2668 lines — 310 lines of mock code is 11.6% of the file for zero production value.

**How to remove safely:**
1. Move both classes to `tests/fixtures/mock_schedule_services.py` or `runtime/dev/mock_schedule_services.py`
2. Update `program_director.py`'s imports of these classes (4 import sites at lines 804, 843, 865, 1173) to use the new location
3. Update any test files that import them from `channel_manager`

**Risk:** Low — these are flag-gated and not in any production code path. Only risk is test breakage if any test imports from `channel_manager` directly (check `scheduling/playlist_schedule_manager.py:28` which imports `Playlist, PlaylistSegment` — different classes, not affected).

**Contracts affected:** None.

**Net lines removed from channel_manager.py:** ~310 lines.

---

### Target 4 — Unify HLS activation path (HIGH IMPACT, MEDIUM RISK)

**What:** `ProgramDirector._ensure_channel_active_for_hls()` (lines 1868–2055, ~190 lines) is a parallel channel activation path for HLS clients that duplicates logic from `start_channel()` → `_get_or_create_manager()`.

**Why it's complexity:** Two entry points for the same outcome (channel started, phantom viewer registered, fanout created). The HLS path has extra logic for socket draining and phantom management that diverges from the raw TS path. Any fix to the reconnect or lifecycle path must be applied in two places.

**How to remove:** Converge on `start_channel()` as the single activation entry point. The extra HLS startup logic (socket draining, phantom drain thread) should be extracted into a `_activate_hls_phantom(channel_id, mgr)` helper that is called from the unified path. The `channels_hls_manifest` endpoint currently calls `_ensure_channel_active_for_hls`; after refactor it should call `start_channel()` then `_activate_hls_phantom()`.

**Risk:** Medium — HLS startup has subtle ordering requirements (socket must be drained immediately or AIR overflows). The refactor must preserve that timing.

**Contracts affected:** `INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001`, `INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001`.

**Net complexity reduction:** ~100 lines removed (after extraction), single lifecycle path.

---

### Target 5 — Remove Playlist/PlaylistSegment from channel_manager.py (MEDIUM IMPACT, LOW RISK)

**What:** `PlaylistSegment` (lines 271–294) and `Playlist` (lines 295–316) dataclasses defined in `channel_manager.py` but consumed only by `scheduling/playlist_schedule_manager.py`.

**Why it's complexity:** These are scheduling domain objects (not runtime) living in the runtime `channel_manager.py`. This pulls scheduling concerns into the runtime module and creates a cross-package import (`scheduling` importing from `runtime`).

**How to remove:** Move to `scheduling/playlist_types.py` or similar. Update `playlist_schedule_manager.py` imports.

**Risk:** Low — pure move, no logic change.

**Net effect:** Eliminates scheduling→runtime cross-package dependency.

---

### Target 6 — Assert on_linger_expired in _start_linger() (LOW IMPACT, ZERO RISK)

**What:** `ChannelManager._start_linger()` `else` branch (lines ~705–720) that does direct teardown when `on_linger_expired is None`.

**Why it's complexity:** This re-introduces the CM-drives-teardown pattern as a fallback. After Phase 2e/2f, `on_linger_expired` is always injected. The fallback is dead code that re-enables a removed anti-pattern.

**How to remove:** Replace the `else` branch with `assert self.on_linger_expired is not None, "on_linger_expired must be injected (INV-LIFECYCLE-PD-SOLE-TEARDOWN-001)"`. Add a test confirming construction without the callback raises.

**Risk:** Zero in production. Slightly raises failure mode from silent incorrect behavior to loud assertion error in tests that create ChannelManager without the callback (which should be fixed anyway).

---

### Target 7 — Delete PD._build_producer_for_mode monkeypatch (LOW IMPACT, ZERO RISK)

**What:** Lines 1103–1106 in `program_director.py`:
```python
_cm_build = ChannelManager._build_producer_for_mode
def factory_wrapper(mode: str, cfg: ChannelConfig = cfg) -> Optional[Any]:
    return _cm_build(manager, mode)
manager._build_producer_for_mode = factory_wrapper
```

**Why it's complexity:** This replaces CM's instance method with an identical wrapper. The wrapper does exactly the same thing as calling `manager._build_producer_for_mode(mode)` directly. Zero functional change.

**How to remove:** Delete the 4 lines. No other changes needed.

**Risk:** Zero.

**Net lines removed:** 4.

---

### Target 8 — Delete MockBlockPlanProvider from playout_session.py (LOW IMPACT, ZERO RISK)

**What:** `MockBlockPlanProvider` class in `playout_session.py` (lines ~760–850, ~90 lines).

**Why it's complexity:** This is a test fixture in a production file. It is never imported by production code. It creates confusion about whether `playout_session.py` is a production or testing module.

**How to remove:** Move to `tests/fixtures/mock_block_plan.py`.

**Risk:** Zero — pure move.

---

## 5. Ghost Surface

### 5.1 Unimplemented (TODO/pass) Methods

**File: `program_director.py`**

| Method | Lines | Status |
|---|---|---|
| `get_system_health()` | 1642–1655 | Returns None (pass). Dead. Delete. |
| `get_channel_status()` | 1656–1672 | Returns None (pass). Dead. Delete. |
| `get_all_channels()` | 1673–1685 | Returns None (pass). Dead. Delete. |
| `activate_emergency_mode()` | 1686–1703 | Returns None (pass). SystemMode.EMERGENCY is set but never used. Delete. |
| `deactivate_emergency_mode()` | 1704–1718 | Returns None (pass). Delete. |
| `enforce_system_policies()` | 1719–1732 | Returns None (pass). Delete. |
| `coordinate_channel_operations()` | 1733–1746 | Returns None (pass). Delete. |
| `monitor_system_performance()` | 1747–1760 | Returns None (pass). Delete. |
| `handle_system_alerts()` | 1761–1777 | Returns None (pass). Delete. |
| `get_emergency_content()` | 1778–1790 | Returns None (pass). Delete. |
| `validate_system_state()` | 1791–1806 | Returns None (pass). Delete. |

**File: `program_director.py` — HTTP stubs**

| Endpoint | Lines | Status |
|---|---|---|
| `/test/segment/{asset_id}.ts` | ~2904–2908 | Returns 501. Delete. |
| `/test/channel/{channel_id}.ts` | ~2909–2915 | Returns 501. Delete. |

### 5.2 Dead Dataclasses

| Class | File | Lines | Used By |
|---|---|---|---|
| `SystemHealth` | `program_director.py` | 456–468 | Only `get_system_health()` (returns None). Delete. |
| `ChannelInfo` | `program_director.py` | 470–480 | Only `get_channel_status()`/`get_all_channels()` (return None). Delete. |
| `ChannelStatus` enum | `program_director.py` | 450–455 | Only `ChannelInfo`. Delete. |

### 5.3 Dead Methods in ChannelManager

| Method | Lines | Status |
|---|---|---|
| `play_content()` | `channel_manager.py:~2250` | Returns True. Docstring says "not used in BlockPlan mode." Delete. |
| `set_blockplan_mode()` | `channel_manager.py:~1135` | `_blockplan_mode` is always True in production; this setter is only a test escape hatch. But `_blockplan_mode = True` hardcoded default means the setter is needed for tests. Keep but simplify. |

### 5.4 Dead Classes

| Class | File | Reason |
|---|---|---|
| `MockBlockPlanProvider` | `playout_session.py:~760` | Test fixture in production module. Move to tests. |
| `MockGridScheduleService` | `channel_manager.py:~1183` | Development harness only. Move to tests/fixtures. |
| `MockAlternatingScheduleService` | `channel_manager.py:~1380` | Development harness only. Move to tests/fixtures. |
| `HLSManager` (old stack) | `streaming/hls_writer.py:349` | Superseded by new SegmentRing stack. Delete. |
| `HLSWriter`, `HLSSegment`, `HLSSegmenter` | `streaming/hls_writer.py:~1–350` | Old stack components. Delete. |

### 5.5 Unused Protocol Definitions

| Protocol | File | Lines | Reason |
|---|---|---|---|
| `ProgramDirector` (Protocol) | `channel_manager.py` | 126–139 | Minimal interface; concrete PD class satisfies duck typing. Can be deleted if `ChannelManager.__init__` types are adjusted. |
| `ScheduleService` (Protocol) | `channel_manager.py` | 98–125 | Useful for testing; retain but move to a shared protocols module. |

### 5.6 INV Governance Gaps (from INVARIANTS.md §Governance Pass Notes)

The following invariants are flagged as having no test matrix entries. They are real enforcement requirements that exist as documentation-only — equivalent to aspirational dead weight at the enforcement level:

- `INV-CADENCE-SOURCE-SYNC-001–004` — No test matrix entry
- `INV-SEAM-BOUNDARY-COUNT-MATCH-001` — No test matrix entry
- `INV-PRODUCER-DEMAND-DRIVEN-001` — No test matrix entry
- `INV-SEAM-CONTINUITY-GUARANTEED-001` — No test matrix entry
- `INV-TIME-MODE-EQUIVALENCE-001` — No test matrix entry
- `INV-SWITCH-BOUNDARY-TIMING` — No Derived From law cited; enforcement unclear

These are not simplification targets (they represent real AIR runtime contracts) but they represent a testing debt that means these invariants are unenforced.

---

## 6. Target Architecture

### 6.1 What ProgramDirector Should Own (Only)

**Sole responsibilities:**
- **HTTP serving:** One FastAPI app, one uvicorn server. All viewer-facing endpoints. All Plex/HDHomeRun endpoints. No dual endpoint sets.
- **Channel lifecycle authority:** `start_channel()` is the single activation path. `_stop_channel_internal()` is the single teardown path. No parallel activation code paths.
- **ChannelManager registry:** Create-on-demand, keep-alive-across-teardowns per `INV-CHANNEL-STARTUP-NONBLOCKING-001`.
- **Schedule prewarm and PlaylistBuilderDaemon management:** At startup, before serving.
- **Global mode** (`SystemMode.NORMAL`/`EMERGENCY`): Only the `get_channel_mode()` method is needed. Emergency mode activation can be a simple setter, not a ghost method.
- **HLS diagnostics state** (in Phase 4 form): A bounded, per-channel `HlsDiagnosticsState` object, not 5+ methods embedded in PD.
- **Pacing loop** (`PaceController`): Drives `on_paced_tick` calls to active producers.

**Removed from PD after cleanup:**
- Ghost skeleton (11 TODO methods)
- `SystemHealth`, `ChannelInfo`, `ChannelStatus` dataclasses
- Old HLS manager (`_hls_manager`, `/hls/` endpoints)
- `_ensure_channel_active_for_hls` (merged into unified `start_channel`)
- `_build_producer_for_mode` monkeypatch wrapper

**Target size:** ~2200 lines (from 3388 current) — a 35% reduction.

### 6.2 What ChannelManager Should Own (Only)

**Sole responsibilities:**
- **Per-channel producer lifecycle:** `_ensure_producer_running()`, `stop_channel()`, producer health monitoring.
- **Viewer count tracking:** `viewer_join()`, `viewer_leave()`, `on_first_viewer()`, `on_last_viewer()`.
- **Linger grace period:** `_start_linger()`, `_cancel_linger()`. Linger expiry notifies PD via `on_linger_expired` callback only.
- **Liveness recovery:** `_on_producer_session_end()`, `_attempt_recovery()`.
- **HLS delivery state:** `SegmentRing`, `HlsSegmenter`, `ManifestGenerator`, `HlsSessionManager` per channel. These are wired from `_init_hls_state()`.
- **MasterClock access:** `self.clock.now_utc()` for authoritative time.

**Removed from CM after cleanup:**
- `MockGridScheduleService`, `MockAlternatingScheduleService` (move to fixtures)
- `Playlist`, `PlaylistSegment` dataclasses (move to scheduling package)
- `play_content()` dead method
- `_start_linger()` fallback branch (assert instead)
- `ProgramDirector` Protocol definition (move to shared protocols)
- `ScheduleService` Protocol definition (move to shared protocols)

**Target size:** ~1800 lines (from 2668 current) — a 33% reduction.

### 6.3 Where HTTP Serving Lives

Exclusively in `ProgramDirector._register_endpoints()`. Single FastAPI app. Clean endpoint set after old HLS removal:

```
GET /channels                      → channel list JSON
GET /channel/{id}.ts               → raw MPEG-TS stream
GET /channels/{id}/live.m3u8       → canonical HLS manifest (SegmentRing)
GET /channels/{id}/seg_{index}.ts  → canonical HLS segment (SegmentRing)
POST /channels/{id}/tune_out       → HLS session disconnect signal
GET /discover.json                 → Plex HDHomeRun discovery
GET /lineup.json                   → Plex channel lineup
GET /lineup_status.json            → Plex tuner status
GET /api/epg                       → EPG data
GET /iptv/guide.xml                → XMLTV guide
GET /playlist.m3u                  → IPTV M3U playlist
GET /watch/{id}                    → HLS web player
GET /epg                           → EPG HTML guide
GET /art/program/{id}.jpg          → Programme artwork
GET /art/channel/{id}.jpg          → Channel artwork
GET /test/block/{id}.ts            → Ephemeral test session (legitimate tool)
```

Dead endpoints removed: `/hls/{id}/live.m3u8`, `/hls/{id}/{segment}`, `/test/segment/...`, `/test/channel/...`.

### 6.4 Where Producers Live

**`BlockPlanProducer`** stays in `channel_manager.py` — it is tightly coupled to `ChannelManager` and that coupling is correct (CM creates it, CM owns it, CM tears it down).

**Mock schedule services** (`MockGridScheduleService`, `MockAlternatingScheduleService`) move to `tests/fixtures/mock_schedule_services.py`.

**`MockBlockPlanProvider`** moves to `tests/fixtures/mock_block_plan.py`.

### 6.5 Where Mocks/Fixtures Live

Target: all test fixtures and mock implementations live in `tests/fixtures/` or `runtime/dev/`. None in production modules. This is a clear boundary: if a class is only instantiated in tests or behind `mock_*` flags, it is not production code.

---

## 7. Revised Phase Plan

The refactor is currently in Phase 4 (diagnostics isolation), step 4c. Based on this analysis, the revised sequencing is:

### Phase 4 (current) — Diagnostics Isolation — Complete 4c

**4c target:** Audit remaining config or coupling in the diagnostics subsystem. Likely clean based on 4a/4b findings. If clean, produce PHASE4_COMPLETE.md and proceed.

**4d (if needed):** Extract `_hls_diag_*` state in PD into a `HlsDiagnosticsState` dataclass. PD holds one instance per channel. This was the original Phase 4 goal per the simplification plan.

---

### Phase 5 — Ghost Surface Deletion (HIGHEST BANG/LINE RATIO)

**Rationale:** Before adding any process gates (original Phase 5), delete the dead weight. Ghost skeleton deletion is zero-regression risk and recovers ~400 lines. Each deleted line is one less line that can diverge, confuse, or mislead future development.

**Sub-steps:**

- **5a:** Delete 11 ghost TODO/pass methods from PD (lines 1642–1806). Delete `SystemHealth`, `ChannelInfo`, `ChannelStatus`. Run tests (floor: 330).
- **5b:** Delete 2 dead HTTP endpoints (`/test/segment/...`, `/test/channel/...`) plus the 501 stubs. Run tests.
- **5c:** Delete `play_content()` dead method from `BlockPlanProducer`. Run tests.
- **5d:** Delete `MockBlockPlanProvider` from `playout_session.py` — move to tests/fixtures.
- **5e:** Delete `_build_producer_for_mode` monkeypatch wrapper from `PD._get_or_create_manager()` (4 lines).
- **5f:** Assert `on_linger_expired is not None` in `_start_linger()` — replace fallback branch.

**Authority map touched:** PD ghost surface (concerns 3, 5), CM lifecycle (concern 3).
**Complexity budget:** 5a–5f net removes ~450 lines, adds 0.
**Contracts affected:** None (all deleted methods are unimplemented).
**Rollback unit:** Each sub-step is independently revertable. Single-PR candidate.

---

### Phase 6 — Old HLS Stack Deletion (HIGH IMPACT)

**Rationale:** The dual HLS stacks are the largest source of live complexity. Removing the old stack eliminates `INV-HLS-NO-DISK-IO-001` violation, reduces steady-state CPU (only one segmenter runs), eliminates one more reconnect edge case surface, and removes ~550 lines.

**Pre-condition:** Confirm IPTV/Plex clients are not configured to use `/hls/` URLs (check client config). The M3U generator already outputs `/channels/` URLs; this should be safe.

**Sub-steps:**

- **6a:** Confirm no active production clients use `/hls/` endpoints. Document in commit.
- **6b:** Remove `/hls/{channel_id}/live.m3u8` and `/hls/{channel_id}/{segment}` endpoint handlers from PD. Remove `self._hls_manager` instantiation and `stop_all()` call.
- **6c:** Delete `retrovue.streaming.hls_writer` module entirely (492 lines).
- **6d:** Remove `hls_manager` parameter from `ChannelStream.__init__` if only used for old stack wiring.
- **6e:** Run tests (floor 330). Confirm HLS clients work against `/channels/` endpoints.

**Authority map touched:** Segment window concern (eliminates dual-owner violation).
**Complexity budget:** Removes ~600 lines, adds 0.
**Contracts affected:** `INV-HLS-NO-DISK-IO-001` (now fully enforced), `INV-HLS-QUIET-POLLING-001`.
**Rollback unit:** 6b–6d revertable as one PR if clients complain.

---

### Phase 7 — Mock Relocation (MEDIUM IMPACT, LOW RISK)

**Rationale:** Moving mock services out of production modules completes the "production boundary" cleanup.

**Sub-steps:**

- **7a:** Move `MockGridScheduleService` and `MockAlternatingScheduleService` from `channel_manager.py` to `tests/fixtures/mock_schedule_services.py`. Update import sites in `program_director.py` (4 import sites).
- **7b:** Move `Playlist`, `PlaylistSegment` from `channel_manager.py` to `retrovue/scheduling/playlist_types.py`. Update import in `scheduling/playlist_schedule_manager.py`.
- **7c:** Move `ProgramDirector` and `ScheduleService` Protocols from `channel_manager.py` to `retrovue/runtime/protocols.py`. Update import sites.
- **7d:** Run tests (floor 330).

**Authority map touched:** Scheduling concern (removes cross-boundary import).
**Complexity budget:** Moves ~450 lines, removes from production path.
**Contracts affected:** None.

---

### Phase 8 — HLS Activation Unification (MEDIUM IMPACT, MEDIUM RISK)

**Rationale:** Merge the two activation paths into one. This is the riskiest structural change and should be done last, after Phases 5–7 have reduced surrounding complexity.

**Sub-steps:**

- **8a:** Write contract test: "HLS activation uses same code path as raw TS activation" (currently not testable without both code paths).
- **8b:** Extract phantom management out of `_ensure_channel_active_for_hls` into `_activate_hls_phantom(channel_id, mgr)` helper.
- **8c:** Update `channels_hls_manifest` endpoint to call `start_channel()` → `_activate_hls_phantom()` instead of `_ensure_channel_active_for_hls()`.
- **8d:** Delete `_ensure_channel_active_for_hls()` (190 lines).
- **8e:** Run tests (floor 330). Regression test all HLS client reconnect scenarios.

**Authority map touched:** Channel lifecycle (single activation path).
**Complexity budget:** Removes ~150 lines net.
**Contracts affected:** `INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001`, `INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001`.
**Rollback unit:** Revertable as one PR; 8e provides verification.

---

### Phase 9 (Original Phase 5) — Process Gates

**After the code is clean, add process gates:**
- Authority map check (pre-commit lint that validates no new cross-authority dependencies)
- Complexity budget (reject PRs that grow any module beyond a line budget without explicit override)
- Regression containment rule (reconnect path changes require test coverage)

These gates are only useful when the codebase is clean enough to measure. Adding them before cleanup would just produce false positives.

---

## Summary: Top 3 Findings

### Finding 1 — Dual HLS Stacks in Active Production Violation of INV-HLS-NO-DISK-IO-001

Two complete HLS delivery systems run simultaneously. `HLSManager` (disk-based, `/hls/` endpoints) from `streaming/hls_writer.py` was never removed after the `SegmentRing`-based system (`/channels/` endpoints) was introduced. Every channel streams to both. This is the largest single piece of active dead weight: ~600 lines, disk I/O violations, dual CPU cost, duplicate reconnect edge cases. **Delete the old stack in Phase 6.**

### Finding 2 — 11 Ghost TODO/pass Methods Are 200 Lines of Confusion

`ProgramDirector` contains 11 methods (lines 1642–1806) that exist only as aspirational scaffolding — all return `None` via `pass`. These were planned before the BlockPlan architecture was finalized and have never been implemented. They pollute the class's API surface, making it appear that emergency mode, policy enforcement, and system health monitoring are implemented features. They are not. **Delete all 11 in Phase 5a — zero regression risk.**

### Finding 3 — Dual Activation Paths Fork Channel Lifecycle Authority

`ProgramDirector` has two distinct code paths that start a channel: `start_channel()` (raw TS) and `_ensure_channel_active_for_hls()` (HLS). These do the same thing (create a ChannelManager, tune in a viewer) but via different code. Any fix to channel startup timing or ordering must be applied in two places. The HLS path has 190 lines of extra logic (socket draining, phantom management) that should be an injectable helper, not a parallel activation system. **Unify in Phase 8 after surrounding cleanup.**

---

## Revised Phase Plan Summary

| Phase | Name | Net Lines Removed | Risk | Impact |
|---|---|---|---|---|
| 4c/4d | Diagnostics isolation (complete) | ~50 | Low | Medium |
| 5 | Ghost surface deletion | ~450 | Zero | High |
| 6 | Old HLS stack deletion | ~600 | Medium | High |
| 7 | Mock relocation | ~450 moved (not deleted) | Low | Medium |
| 8 | HLS activation unification | ~150 | Medium | High |
| 9 | Process gates | 0 | Low | High (future protection) |

**Projected total net reduction: ~1,250 lines removed from production modules over phases 5–8.** This reduces `program_director.py` from 3388 → ~2200 lines and `channel_manager.py` from 2668 → ~1800 lines. Combined with Phase 2's 422 deletions (already done), total reduction will be ~1,700 lines — a 20% reduction in the combined runtime module footprint.

---

*End of analysis. Written to /opt/retrovue/DEEP_ANALYSIS.md.*
