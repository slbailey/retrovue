# HLS Contract Test Migration Plan

## Context

`hls_writer.py` (old disk-based HLS stack) was deleted in commit `99131d7`.
194 contract tests were written against the old `HLSSegmenter` API.
They need to be migrated to the new `HlsSegmenter` + `SegmentRing` API.
These tests cover real invariants — they must be preserved, not deleted.

---

## The API Difference

### Old API (deleted)
```python
from retrovue.streaming.hls_writer import HLSSegmenter, HLSSegment, TS_PACKET_SIZE, TS_SYNC_BYTE

seg = HLSSegmenter("channel-id", target_duration=2.0, max_segments=5)
seg.feed(ts_bytes)
segments = seg.get_segments()   # returns list of HLSSegment
playlist = seg.get_playlist()   # returns M3U8 string
```

### New API (current)
```python
from retrovue.runtime.hls.segmenter import HlsSegmenter, TS_PACKET_SIZE, TS_SYNC_BYTE
from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

ring = SegmentRing(capacity=5, manifest_window=3)
seg = HlsSegmenter(
    channel_id="channel-id",
    segment_ring=ring,
    target_duration_ms=2000,   # milliseconds, not seconds
)
seg.feed(ts_bytes)
segments = ring.snapshot()               # returns list[LiveSegment]
manifest = ManifestGenerator(ring).build()  # returns M3U8 string
```

### Key differences
| Concern | Old | New |
|---|---|---|
| Segment ring | Internal to segmenter | External SegmentRing (passed in) |
| Segment type | HLSSegment | LiveSegment |
| Target duration | target_duration (seconds, float) | target_duration_ms (milliseconds, int) |
| Get segments | seg.get_segments() | ring.snapshot() |
| Get playlist | seg.get_playlist() | ManifestGenerator(ring).build() |
| Max segments | max_segments on segmenter | capacity on SegmentRing |

---

## Files to Migrate (in order — one per cron turn)

### Step 6g-1 — conftest.py (do first — shared fixtures)
File: tests/contracts/hls_delivery/conftest.py

Changes:
1. Replace import: hls_writer.HLSSegmenter -> runtime.hls.segmenter.HlsSegmenter
2. Add imports for SegmentRing, LiveSegment, ManifestGenerator
3. Update all segmenter fixture construction to ring-first pattern
4. Expose ring as fixture attribute alongside segmenter
5. Update get_playlist() calls -> ManifestGenerator(ring).build()
6. Update get_segments() calls -> ring.snapshot()
7. Update HLSSegment type references -> LiveSegment

### Step 6g-2 — test_segment_ring.py
File: tests/contracts/hls_delivery/test_segment_ring.py
- Update segmenter construction to ring-first pattern
- HLSSegmenter.get_segments() -> ring.snapshot()
- HLSSegment -> LiveSegment
- max_segments -> capacity on SegmentRing

### Step 6g-3 — test_segment_production.py
File: tests/contracts/hls_delivery/test_segment_production.py
- Same pattern as 6g-2
- target_duration=2.0 -> target_duration_ms=2000

### Step 6g-4 — test_manifest.py
File: tests/contracts/hls_delivery/test_manifest.py
- Update to use ManifestGenerator(ring).build()
- Segmenter construction update same as above

### Step 6g-5 — test_channel_lifecycle.py
File: tests/contracts/hls_delivery/test_channel_lifecycle.py
- Update construction + ring access

### Step 6g-6 — test_delivery_endpoints.py
File: tests/contracts/hls_delivery/test_delivery_endpoints.py
- Most complex — HTTP endpoint tests, may need PD/CM fixture updates
- Do last in hls_delivery/

### Step 6g-7 — test_inv_hls_no_disk_io.py
File: pkg/core/tests/contracts/runtime/test_inv_hls_no_disk_io.py
- Update to verify SegmentRing uses in-memory storage (satisfies the invariant)

### Step 6g-8 — test_inv_hls_discontinuity_marker.py
File: pkg/core/tests/contracts/runtime/test_inv_hls_discontinuity_marker.py
- HLSSegment -> LiveSegment (has discontinuity: bool field)
- HLSSegmenter -> HlsSegmenter construction update

---

## Success Criteria

After all 8 steps:
- All previously-passing HLS tests pass against the new API
- No test deleted — only construction/accessor patterns updated
- Full contract suite returns >= 330 passed
- CLAUDE.md updated: "HLS contract tests use HlsSegmenter + SegmentRing from retrovue.runtime.hls.*"

---

## Execution Notes

- One file per cron turn
- Start with conftest.py (Step 6g-1) — shared fixtures, gates all others
- After each step: run that file's tests first, then full suite
- Track sub-steps in REFACTOR_STATE.md as 6g-1 through 6g-8
