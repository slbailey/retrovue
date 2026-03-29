# EXECUTION_STATE.md — What Actually Happened

**Last updated:** 2026-03-29
**Last action:** Smoke test complete, DB fix committed

---

## Current Reality

Branch: `refactor/simplify-single-authority-l3`
Server: `192.168.1.199:/opt/retrovue`
Running via: `sudo systemctl start retrovue`

### Test status
- 357 passing, 2 pre-existing failures
- Pre-existing failures: `test_interstitial_enrichment.py::TestInvInterstitialInferenceFillerDefault001`
  - `test_unmatched_directory_defaults_to_filler`
  - `test_known_type_directory_overrides_filler`
  - These predate the branch — not caused by refactor

### Stream status
- `/channel/cheers-24-7.ts` — HTTP 200, valid H.264/AAC MPEG-TS ✅
- `/channels/cheers-24-7/live.m3u8` — valid HLS manifest when channel warm ✅
- Cold channel HLS: returns 503 on first request (VLC doesn't retry) — known issue

### Last commit
`4959c65` — fix: remove redacted DATABASE_URL default

### Known issues
1. **VLC cold-start**: HLS returns 503 before first segment is ready. VLC doesn't honor Retry-After and gives up. Raw TS endpoint works fine as workaround. Fix: make manifest endpoint wait/poll briefly before returning 503.
2. **Phase 10 tests**: rewritten but not externally reviewed yet. See PHASE10_REVIEW_FOR_GPT.md.

---

## Recommended Next Action for Robbie

Review the VLC cold-start issue and decide:
- Is this worth fixing before merge?
- Or document as known behavior and fix in a follow-up pass?

Write decision to NEXT_INSTRUCTION.md with exact guidance for Claude.
