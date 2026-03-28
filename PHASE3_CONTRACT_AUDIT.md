# PHASE3_CONTRACT_AUDIT.md — Contract Overlap / Internal Sequencing Audit

> Produced by: Phase 3a atomic step
> Date: 2026-03-28
> Branch: refactor/simplify-single-authority-l3
> Current pass count: 334 (floor: 328, headroom: 6)

---

## Audit Scope

All files under `tests/contracts/` reviewed for tests asserting **internal sequencing
or implementation mechanics** rather than **observable invariants** (externally required
outputs, protocol compliance, authority boundaries).

L3 rule: tests that only prove *how* a thing works (not *what* it guarantees to callers)
are candidates for retirement.

---

## Key Finding: conftest auto-tagging

`tests/contracts/conftest.py` auto-adds `@pytest.mark.contract` to every test collected
from the `tests/contracts/` tree. There are NO explicit `@pytest.mark.contract` decorators
in `test_frame_selection_cadence_contract.py`. Moving files out of `tests/contracts/` removes
them from the `-m "contract and not soak"` run entirely. With 334 passing and a floor of 328,
we have **headroom of 6 tests** maximum we can safely remove.

---

## Candidate List

### PRIMARY CANDIDATE (retire in 3b)
**File:** `tests/contracts/test_frame_selection_cadence_contract.py`
**Retire:** 4 specific tests (NOT the entire file — headroom constraint)

The entire file is a self-contained pure-Python simulation of C++ Bresenham logic
(PipelineManager.cpp lines 1700-1710). Zero imports from `retrovue.*`.
However, the core behavioral tests (ADVANCE/REPEAT ratio, consumption ratio) are
genuine algorithm invariants that are cheap to keep. The following 4 are internal:

| Test method | Class | Reason to retire |
|-------------|-------|-----------------|
| `test_buggy_cascade_violates_pop_invariant` | `TestCadencePopInvariant` | Meta-test: verifies the test harness's buggy simulation behaves badly. Not a production invariant. |
| `test_buggy_consumption_ratio_is_1_0` | `TestConsumptionRatio` | Same — verifies buggy simulation has ratio 1.0. Self-referential. |
| `test_accumulator_budget_bounded` | `TestLongRunStability` | Tests internal `budget` field stays in [0, threshold). Internal state, not observable output. |
| `test_60_to_30_cadence_half` | `TestEdgeCases` | Docstring says "In practice this path would be handled differently." Undefined behavior path. |

**Count removed:** 4 tests → 334 - 4 = **330 passing** (above 328 floor ✓)

---

### SECONDARY CANDIDATE (examine in 3c)
**File:** `tests/contracts/hls_delivery/test_session_manager_direct.py`
**Status:** EXAMINE — may be safe to retire some duplicate class coverage

The file's own docstring states: "validating the same invariants as test_viewer_presence.py".
`test_viewer_presence.py` uses behavioral fakes; `_direct.py` uses the production
`HlsSessionManager` class. Together they cover 38 tests.

Some classes in `_direct.py` are pure duplicates of `test_viewer_presence.py`:
- `TestHlsSessionManagerPresence` / `TestInvHlsViewerPresence001`
- `TestHlsSessionManagerCount` / `TestInvHlsViewerCountAccurate001`
- `TestHlsSessionManagerReapBounded` / `TestInvHlsSessionReapBounded001`
- `TestHlsSessionManagerFirstViewer` / `TestInvHlsSessionFirstViewerOnce001`

**However:** `TestHlsSessionManagerPhantom` in `_direct.py` has no counterpart in
`test_viewer_presence.py`. Keep that class.

**3c action:** Retire the 4 duplicate contract classes from `_direct.py`, keep
`TestHlsSessionManagerPhantom`. Estimate: ~22 tests removed. 330 - 22 = 308 — **below floor!**

**VERDICT:** Cannot retire without ALSO lowering the floor OR adding replacement tests.
Defer 3c to Phase 4 planning. Do NOT retire `test_session_manager_direct.py` in 3c.

---

### TERTIARY CANDIDATE (Phase 4 / defer)
**File:** `tests/contracts/hls_delivery/test_startup_headroom.py`
**Class:** `TestInvAirSessionCleanupOnEnd001` (6 tests)
**Status:** DEFER

Tests internal call ordering (`terminate()` before `on_session_end` callback, process
state tracking via `_process_alive_when_callback_fired` flag). These are sequencing details,
not observable invariants. However removing them would bring count close to or below floor.
Defer until floor is re-evaluated or the 2 pre-existing failures in `test_interstitial_enrichment.py`
are fixed (restoring those 2 to passing would provide more headroom).

---

## Files to KEEP (not candidates)

| File | Reason |
|------|--------|
| `test_lifecycle_authority.py` | Authority boundary — owns Phase 2 work |
| `test_interstitial_enrichment.py` | Genuine output invariants (2 pre-existing failures) |
| `test_traffic_inventory_category_ordering.py` | Observable ordering invariant |
| `test_schedule_explain_preview.py` | Output format invariants |
| `test_schedule_rebuild.py` | Output correctness invariants |
| `hls_delivery/test_channel_lifecycle.py` | Runtime behavior invariants |
| `hls_delivery/test_delivery_endpoints.py` | Protocol + lifecycle invariants |
| `hls_delivery/test_manifest.py` | HLS protocol correctness |
| `hls_delivery/test_hls_activation.py` | Activation authority invariant |
| `hls_delivery/test_hls_phantom_drain.py` | Phantom drain liveness invariant |
| `hls_delivery/test_viewer_presence.py` | Viewer presence behavioral contract (canonical) |
| `hls_delivery/test_segment_ring.py` | Segment window invariant (via HLSSegmenter API) |
| `hls_delivery/test_segment_ring_direct.py` | Segment window invariant (via SegmentRing directly) |
| `hls_delivery/test_segmenter_direct.py` | Segmenter direct path invariants |
| `hls_delivery/test_segment_production.py` | Segment production invariants |
| `hls_delivery/test_startup_headroom.py::TestInvAirSocketBufferStartupHeadroom001` | Buffer sizing structural invariant |
| `hls_delivery/test_session_manager_direct.py::TestHlsSessionManagerPhantom` | No counterpart in _viewer_presence.py |

---

## Execution Plan

| Sub-step | Action | Tests removed | Expected count |
|----------|--------|--------------|----------------|
| 3b | Retire 4 tests from `test_frame_selection_cadence_contract.py` | 4 | 330 |
| 3c | No retirement possible within floor — update 3c to Phase 4 planning | 0 | 330 |
| 3d | Move to Phase 4: Diagnostics isolation audit | — | — |

---

## Pass Count Math
- Current: 334 passing, 2 failing
- After 3b: 330 passing (floor: 328) ✓
- Headroom remaining after 3b: 2 tests

---

*Phase 3a DONE. Next sub-step: 3b — retire 4 internal tests from test_frame_selection_cadence_contract.py.*
