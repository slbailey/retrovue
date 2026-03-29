# Phase 10 HLS Test Review — Summary for ChatGPT

## Context

Retrovue is a broadcast-grade linear TV simulation platform. It has two components:
- **Core** (Python): scheduling, orchestration, HLS delivery
- **AIR** (C++): real-time video encoding

The HLS delivery stack was recently refactored. The old disk-based HLS system (`hls_writer.py`) was deleted and replaced by an in-memory stack (`HlsSegmenter` + `SegmentRing` + `ManifestGenerator`). During the deletion, ~194 contract tests were retired. Phase 10 rewrote those tests against the new API.

**The question:** Are the new Phase 10 tests actually testing the right things, or are they just passing vacuously?

---

## The New HLS Stack (what the tests are testing)

```
MPEG-TS bytes
     ↓
HlsSegmenter.feed()      — detects keyframe-aligned segment boundaries
     ↓
SegmentRing.push()       — bounded in-memory FIFO (e.g. capacity=6, manifest_window=3)
     ↓
ManifestGenerator.build() — generates M3U8 playlist string from ring snapshot
     ↓
HTTP /channels/{id}/live.m3u8  — manifest served to viewers
HTTP /channels/{id}/seg_{n}.ts — segment bytes served to viewers
```

Key classes:
- `HlsSegmenter(channel_id, segment_ring, target_duration_ms=6000)`
- `SegmentRing(capacity=6, manifest_window=3)`
- `LiveSegment` — frozen dataclass: `index: int, data: bytes, duration_s: float, discontinuity: bool, wall_clock_utc_ms: int`
- `ManifestGenerator(ring).build()` — returns M3U8 string or None if ring is empty

---

## The 7 Rewritten Test Files

### 1. test_segment_ring.py (~12 tests)
**What it claims to test:**
- `INV-HLS-RING-BOUNDED-001`: ring never exceeds capacity; oldest segment evicted first (FIFO)
- `INV-HLS-RING-OBSERVATION-001`: every segment in the manifest window is retrievable
- `INV-HLS-RING-PUSH-ATOMIC-001`: concurrent feed+read produces no torn state
- `INV-HLS-RING-WINDOW-VALID-001`: manifest_window <= capacity; window reflects only the last N segments

**Potential concerns to check:**
- Does the concurrent test actually use threads or just simulate it?
- Does FIFO eviction test verify the *oldest* is evicted or just that count stays bounded?
- Does the window test verify the right segments appear in the manifest, or just the count?

---

### 2. test_segment_production.py (~20 tests)
**What it claims to test:**
- `INV-HLS-SEGMENT-IDENTITY-001`: indices are monotonically increasing, start at 0 (or starting_index), increment by exactly 1
- `INV-HLS-SEGMENT-IMMUTABLE-001`: completed segment data is frozen (bytes, not bytearray; stable across reads)
- `INV-HLS-SEGMENT-KEYFRAME-001`: each segment begins at a keyframe (RAI flag in TS packet)
- `INV-HLS-SEGMENT-SELFCONTAINED-001`: each segment starts with a TS sync byte (0x47)
- `INV-HLS-SEGMENT-DURATION-BOUNDS-001`: duration within reasonable tolerance of target
- `INV-HLS-SEGMENT-INDEX-GUARD-001`: index increments by exactly 1

**Potential concerns to check:**
- The keyframe test — does it feed real TS with actual RAI flags, or synthetic packets that just have the flag set by the test? If synthetic, does the segmenter actually *use* the RAI to split?
- Duration bounds test — what tolerance is it using? If too loose it won't catch drift.
- Immutability test — does it verify the dataclass is frozen (raises on mutation attempt), or just that the bytes don't change across reads?

---

### 3. test_manifest.py (~25 tests)
**What it claims to test:**
- `INV-HLS-MANIFEST-LIVE-001`: no `#EXT-X-ENDLIST`, TARGETDURATION valid, required tags present
- `INV-HLS-MANIFEST-SEQUENCE-001`: MEDIA-SEQUENCE equals oldest segment's index, ascending order
- `INV-HLS-MANIFEST-PDT-001`: PROGRAM-DATE-TIME present, ISO 8601 UTC format, before first segment
- `INV-HLS-MANIFEST-DETERMINISTIC-001`: same ring state = same manifest output
- `INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001`: sequence never decreases across calls
- `INV-HLS-MANIFEST-VALID-PLAYLIST-001`: EXTINF before every segment URI, correct format
- `INV-HLS-DISCONTINUITY-MARKER-001`: discontinuity tags propagated correctly

**Potential concerns to check:**
- PDT test — does it verify the wall_clock_utc_ms from LiveSegment is what appears in the manifest, or just that PDT exists and looks like a date?
- Monotonic sequence test — does it push new segments between calls to verify the sequence actually increments, or just call build() twice on the same ring?
- The deterministic test is important — verify it's actually asserting string equality, not just that both return non-None.

---

### 4. test_channel_lifecycle.py (~18 tests)
**What it claims to test:**
- `INV-HLS-RESTART-DISCONTINUITY-001`: first segment after `reset_for_restart()` has `discontinuity=True`
- `INV-HLS-PRODUCER-SEGMENT-FLOW-001`: segments only produced when data is fed; no segments without feed
- `INV-HLS-NO-ORPHAN-PRODUCER-001`: `close()` halts segment acceptance

**Potential concerns to check:**
- Restart discontinuity — does it verify the *manifest* contains `#EXT-X-DISCONTINUITY` before the restarted segment, or just that `LiveSegment.discontinuity == True`? The manifest tag is what clients actually see.
- Orphan producer test — does it verify that feed() after close() is a no-op or raises? Silent drop vs exception matters for debugging.

---

### 5. test_delivery_endpoints.py (~23 tests)
**What it claims to test:**
- `INV-HLS-MANIFEST-LIVE-001`: no EXT-X-ENDLIST in live manifests
- `INV-HLS-SERVE-BYTE-IDENTITY-001`: bytes served from ring are byte-identical to what was pushed
- `INV-HLS-LIFECYCLE-SEGMENT-READY-001`: 503 + Retry-After until first segment ready
- `INV-HLS-ENDPOINT-SESSION-TOUCH-001`: session activity only touched on 200, not 4xx/5xx
- `INV-HLS-MANIFEST-CONTENT-TYPE-001`: correct MIME types
- `INV-HLS-SEGMENT-CACHE-001`: manifests no-cache, segments cacheable
- `INV-HLS-UNKNOWN-SEGMENT-404-001`: missing/evicted segment returns 404
- `INV-HLS-UNKNOWN-CHANNEL-404-001`: unknown channel returns 404

**Important note:** These tests use a "thin fake endpoint layer" that mirrors PD handler logic without spinning up FastAPI. This means they're testing the handler *logic* but not the actual HTTP wiring. The real FastAPI routes in `program_director.py` are untested at the integration level.

**Potential concerns to check:**
- Are the fake endpoints actually reading the same code path as the real ones, or are they reimplementing the logic from scratch? If reimplemented, they prove nothing about the real endpoints.
- Byte identity test — does it push known bytes to the ring and verify the same bytes come back from the endpoint? That's the important check.
- 503 test — does it verify Retry-After header is present and a reasonable value?

---

### 6. test_inv_hls_no_disk_io.py (~13 tests)
**What it claims to test:**
- `INV-HLS-NO-DISK-IO-001`: no disk I/O in SegmentRing, HlsSegmenter, ManifestGenerator, LiveSegment

**Approach:** Static source analysis (grep for `open(`, `os.`, `pathlib`, `tempfile` etc.) + dynamic type checking (LiveSegment raises TypeError if data is not bytes).

**Potential concerns to check:**
- Static analysis is brittle — it checks for known disk I/O patterns but could miss indirect disk access (e.g. through a library call or subprocess). Is this the right approach for this invariant?
- The TypeError test for string data — does the LiveSegment validator run at construction time, or is it a separate validator method?

---

### 7. test_inv_hls_discontinuity_marker.py (~13 tests)
**What it claims to test:**
- `INV-HLS-DISCONTINUITY-MARKER-001`: `#EXT-X-DISCONTINUITY` tag appears before every discontinuous segment in the manifest
- `INV-HLS-RESTART-DISCONTINUITY-001`: first segment after construction and after `reset_for_restart()` is always discontinuous

**Potential concerns to check:**
- Does it test that the tag appears *before* the segment URI in the manifest (ordering matters for HLS clients)?
- Does it test a mix of continuous and discontinuous segments in the window to verify no false positives?
- Multiple discontinuous segments — does each get its own tag, or just one?

---

## Questions for ChatGPT to Answer

1. **Are the tests actually exercising the real code paths?** Especially test_delivery_endpoints.py — the fake endpoint layer is a risk.

2. **Are the synthetic TS packets realistic enough?** Several tests build fake TS data (sync bytes, RAI flags, PCR values). If the packets are too simple, the segmenter might behave differently than with real AIR output.

3. **Is the keyframe-alignment test meaningful?** `INV-HLS-SEGMENT-KEYFRAME-001` is critical for HLS clients — a segment that doesn't start on a keyframe causes player stalls. The test should verify the segmenter *splits on* keyframes, not just that the test injects packets with the RAI flag.

4. **Is the concurrent access test strong enough?** `INV-HLS-RING-PUSH-ATOMIC-001` — what happens if a reader snapshots the ring while a writer is mid-push? The test should verify no torn reads.

5. **Are the 2 pre-existing test_interstitial_enrichment failures related to anything HLS?** They're been marked "unrelated" throughout — worth confirming they're genuinely independent.

---

## Files to Read on the Server

SSH into `steve@192.168.1.199`, directory `/opt/retrovue`:

- Test files: `tests/contracts/hls_delivery/*.py` and `pkg/core/tests/contracts/runtime/test_inv_hls_*.py`
- New HLS stack: `pkg/core/src/retrovue/runtime/hls/segment_ring.py`, `segmenter.py`, `manifest_generator.py`
- Contracts: `docs/contracts/INVARIANTS.md` (search for INV-HLS-*)
- Run tests: `cd /opt/retrovue && pkg/core/.venv/bin/python -m pytest tests/contracts/hls_delivery/ -v 2>&1`
