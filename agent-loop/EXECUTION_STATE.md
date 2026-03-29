# EXECUTION_STATE.md — What Actually Happened

**Last updated:** 2026-03-29 (pass complete)
**Status: MERGE READY**

---

## Plain English Summary

The refactor branch is now ready to merge. Here's what happened in plain English:

The branch was correctly refactored (old HLS disk stack removed, single-authority architecture enforced), but when we ran the full test suite for the first time properly (with the live server stopped and the right database credentials), 29 tests were failing that weren't failing on main.

We went through each failure group systematically:

1. **JIP (join-in-progress) tests (10):** The refactor deleted a deprecated legacy function `compute_jip_position()` that was still required by contract tests. Restored it verbatim.

2. **Grid alignment tests (10):** Same — the refactor deleted mock grid helper methods (`_floor_to_grid`, `_calculate_join_offset`, etc.) that tests still called. Restored as compatibility shims.

3. **HLS phantom cleanup tests (5):** These tests inspected the old `hls_playlist()` / `hls_segment()` nested functions that the refactor removed. Rewrote the tests against the new `HlsConsumptionAdapter` architecture, asserting the same invariants (activity tracking only on success, phantom cleanup on failure) in the new way.

4. **Channel startup concurrency test (1):** Same pattern — stale structural test for `hls_playlist()`. Rewrote to verify the semaphore guard in `HlsConsumptionAdapter.activate()`.

5. **Schedule retention test (1):** Real regression — `_purge_expired_program_schedule()` uses `self._clock` which was added by the refactor, but the test fixture never set it. Added mock clock to fixture.

---

## Final Test Counts

| Branch | Passed | Failed | Notes |
|--------|--------|--------|-------|
| main | 3078 | 7 | pre-existing failures |
| refactor (this branch) | 3097 | 7 | same 7 pre-existing failures, +19 from compatibility restores |

**The 7 failures are identical on both branches:**
- test_inv_pad_asrun_suppress.py::test_integration_asrun_pad_suppression_time_continuity
- test_playout_log_expander.py::TestAdBlockDurations::test_equal_ad_block_split
- test_traffic_manager.py::TestPadding::test_filler_longer_than_block_partial_play
- test_traffic_manager.py::TestSequentialOffsets::test_ads_have_sequential_offsets
- test_traffic_manager.py::TestSequentialOffsets::test_offset_continues_across_ad_blocks
- test_asset_enrich.py::TestEnrichAssetClearsMetadata::test_clears_fields_even_when_enricher_produces_nothing
- test_asset_enrich.py::TestEnrichAssetClearsMetadata::test_clears_technical_fields

**No new regressions introduced by the refactor.**

---

## Files Modified in This Pass

### Production code
- `pkg/core/src/retrovue/runtime/channel_manager.py` — restored `compute_jip_position()` and 4 mock grid methods as compatibility shims

### Test files
- `pkg/core/tests/contracts/runtime/test_inv_hls_phantom_cleanup.py` — full rewrite for new HLS adapter architecture
- `pkg/core/tests/contracts/runtime/test_inv_channel_startup_concurrency.py` — rewrite of one stale test
- `pkg/core/tests/contracts/scheduling/test_inv_schedule_retention_001.py` — fixture fix (added mock _clock)

---

## Known Limitation (Follow-up Required)

**VLC cold-start HLS 503:** When a channel is cold (no active viewers), the first HLS request returns 503 (correct per architecture). VLC does not honor `Retry-After: 1` and gives up. Root cause is a latent `threading.Lock` contention between the uvicorn event loop and the channel startup executor thread.

This is **not a regression** — it existed before this refactor. It requires a dedicated architectural pass on the lock model.

**All other HLS clients that retry on 503 work correctly. Raw TS stream works for all clients including VLC.**

---

## Stream Status (Verified)
- Raw TS `/channel/cheers-24-7.ts` — HTTP 200, 8.7MB/s confirmed ✅
- HLS warm channel — valid manifest returned ✅
- HLS cold channel — 503 + Retry-After (VLC limitation documented above)
- DB connection — stable via systemd ✅

---

## Merge Readiness: READY

Signed off by: RetrovueBot / Robbie (Architect)
