# Phase 9 Validation Runbook

**Document Type:** Validation Runbook
**Phase:** 9 (Steady-State Playout Correctness)
**Purpose:** Step-by-step instructions for validating Phase 9 exit criteria
**Last Updated:** 2026-02-03

---

## 1. Prerequisites

### 1.1 Build AIR

```bash
# From repo root
cmake -S pkg/air -B pkg/air/build \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo

cmake --build pkg/air/build -j$(nproc)
```

**Verify build:**
```bash
ls -la pkg/air/build/retrovue_air
# Must exist and be recent
```

### 1.2 Activate Core Environment

```bash
source pkg/core/.venv/bin/activate
pip install -r pkg/core/requirements.txt
```

### 1.3 Database Migration (if needed)

```bash
cd pkg/core && alembic upgrade head
```

### 1.4 Verify Test Media Available

```bash
ls -la assets/test-media/
# Should contain test video files
```

---

## 2. Running the System

### 2.1 Option A: Full Stack (ProgramDirector + AIR)

```bash
# Terminal 1: Start ProgramDirector (spawns AIR per channel)
retrovue start --port 8080
```

Wait for log line:
```
ProgramDirector: HTTP server listening on port 8080
```

### 2.2 Option B: Direct Channel Start (Testing)

```bash
# Start a single channel directly (bypasses ProgramDirector)
retrovue start cheers-24-7 --config /opt/retrovue/config/channels.json
```

### 2.3 Verify AIR Started

Check AIR log:
```bash
tail -f pkg/air/logs/cheers-24-7-air.log
```

**Expected:** Log file exists and shows startup messages.

---

## 3. VLC Validation

### 3.1 Open Stream in VLC

```bash
vlc http://localhost:8080/channel/cheers-24-7.ts
```

Or via VLC GUI:
1. Media → Open Network Stream
2. Enter: `http://localhost:8080/channel/cheers-24-7.ts`
3. Click Play

### 3.2 What to Observe in VLC

| Observation | Expected | Failure Indicator |
|-------------|----------|-------------------|
| Video plays | Smooth, no freezes | Stuttering, freezing |
| Audio plays | Sync with video | Pops, silence, desync |
| Duration | Continuous for 60s+ | Stops, restarts |
| Bitrate (Stats) | Stable ~2-4 Mbps | Wild fluctuations |

**VLC Statistics:** Tools → Codec Information → Statistics tab

---

## 4. Log Validation Commands

### 4.1 Monitor AIR Log in Real-Time

```bash
# Full log
tail -f pkg/air/logs/cheers-24-7-air.log

# Filter for invariant messages only
tail -f pkg/air/logs/cheers-24-7-air.log | grep -E "INV-P9-STEADY"
```

### 4.2 Invariant Log Patterns to Grep

#### INV-P9-STEADY-001: Output Owns Pacing Authority (PCR-paced mux)

```bash
grep "INV-P9-STEADY-001" pkg/air/logs/cheers-24-7-air.log
```

**Expected (PASS):**
```
[MpegTSOutputSink] INV-P9-STEADY-001: PCR-paced mux active, first_wait=...
```

**Failure (VIOLATION):**
```
INV-P9-STEADY-001 VIOLATION  # (should never appear)
```

#### INV-P9-STEADY-004: No Pad While Depth High

```bash
grep "INV-P9-STEADY-004" pkg/air/logs/cheers-24-7-air.log
```

**Expected (PASS):** No output (no violations)

**Failure (VIOLATION):**
```
[ProgramOutput] INV-P9-STEADY-004 VIOLATION: Pad emitted while depth=15, threshold=10
```

#### INV-P9-STEADY-005: Buffer Equilibrium Sustained

```bash
grep "INV-P9-STEADY-005" pkg/air/logs/cheers-24-7-air.log
```

**Expected (PASS - restored or no warnings):**
```
[ProgramOutput] INV-P9-STEADY-005: Buffer equilibrium restored, depth=...
```

**Warning (tolerable if transient):**
```
[ProgramOutput] INV-P9-STEADY-005 WARNING: Buffer depth N outside equilibrium range [1, 2N]
```

**Failure (sustained warnings for >1s):**
```
# Multiple warnings with increasing duration_ms
```

#### INV-P9-STEADY-007: Producer CT Authoritative

```bash
grep "INV-P9-STEADY-007" pkg/air/logs/cheers-24-7-air.log
```

**Expected (PASS - enabled):**
```
[EncoderPipeline] INV-P9-STEADY-007: Producer CT authoritative ENABLED
[EncoderPipeline] INV-P9-STEADY-007: First audio PTS=... (producer-provided)
```

**Failure (VIOLATION):**
```
[EncoderPipeline] INV-P9-STEADY-007 VIOLATION: Audio PTS jumped backward by ...
[EncoderPipeline] INV-P9-STEADY-007 VIOLATION: Audio PTS jumped forward by ...
```

#### INV-P9-STEADY-008: No Silence Injection After Attach

```bash
grep "INV-P9-STEADY-008" pkg/air/logs/cheers-24-7-air.log
```

**Expected (PASS):**
```
[MpegTSOutputSink] INV-P9-STEADY-008: silence_injection_disabled=true
```

**Stalling (acceptable if transient):**
```
[MpegTSOutputSink] INV-P9-STEADY-008: Mux STALLING - audio queue empty
```

**Failure:** Silence frames injected after this log line appears.

#### Steady-State Entry Confirmation

```bash
grep "INV-P9-STEADY-STATE: entered" pkg/air/logs/cheers-24-7-air.log
```

**Expected:**
```
[MpegTSOutputSink] INV-P9-STEADY-STATE: entered, depth=N, pcr_paced=true, silence_disabled=true
```

---

## 5. Exit Criteria Checklist

Run the system for **60 seconds minimum**, then verify:

### 5.1 60s No Pad Takeover

```bash
grep "INV-P9-STEADY-004 VIOLATION" pkg/air/logs/cheers-24-7-air.log | wc -l
```

**PASS:** `0`
**FAIL:** Any non-zero count

### 5.2 No Runaway Backpressure

```bash
grep "INV-P9-STEADY-005 WARNING" pkg/air/logs/cheers-24-7-air.log | tail -5
```

**PASS:** No warnings, or warnings that resolve (followed by "equilibrium restored")
**FAIL:** Monotonically increasing `duration_ms` values or `violations_total` counter climbing

Verify equilibrium restored:
```bash
grep "equilibrium restored" pkg/air/logs/cheers-24-7-air.log | tail -1
```

### 5.3 Pacing Evidence

```bash
grep "pcr_paced_active=1" pkg/air/logs/cheers-24-7-air.log | head -1
```

**PASS:** At least one line with `pcr_paced_active=1`
**FAIL:** Only `pcr_paced_active=0` or no matches

Additional pacing evidence:
```bash
grep "INV-P9-STEADY-001: PCR-paced mux active" pkg/air/logs/cheers-24-7-air.log | head -1
```

### 5.4 Timestamp Continuity Evidence

```bash
grep "INV-P9-STEADY-007" pkg/air/logs/cheers-24-7-air.log | grep -v VIOLATION | head -3
```

**PASS:** Shows `First audio PTS=...` with producer-provided value (not 0)
**FAIL:** PTS starts at 0 or shows VIOLATION messages

### 5.5 Combined Exit Criteria Script

```bash
#!/bin/bash
LOG="pkg/air/logs/cheers-24-7-air.log"

echo "=== Phase 9 Exit Criteria Validation ==="
echo ""

# 1. Steady-state entered
echo "1. Steady-state entry:"
if grep -q "INV-P9-STEADY-STATE: entered" "$LOG"; then
  echo "   ✓ PASS: Steady-state entered"
else
  echo "   ✗ FAIL: Steady-state never entered"
fi

# 2. No pad takeover
echo "2. No pad while depth high (60s):"
PAD_VIOLATIONS=$(grep -c "INV-P9-STEADY-004 VIOLATION" "$LOG" 2>/dev/null || echo "0")
if [ "$PAD_VIOLATIONS" -eq 0 ]; then
  echo "   ✓ PASS: 0 violations"
else
  echo "   ✗ FAIL: $PAD_VIOLATIONS violations"
fi

# 3. No runaway backpressure
echo "3. Buffer equilibrium:"
EQ_WARNINGS=$(grep -c "INV-P9-STEADY-005 WARNING" "$LOG" 2>/dev/null || echo "0")
EQ_RESTORED=$(grep -c "equilibrium restored" "$LOG" 2>/dev/null || echo "0")
if [ "$EQ_WARNINGS" -eq 0 ]; then
  echo "   ✓ PASS: No equilibrium warnings"
elif [ "$EQ_RESTORED" -gt 0 ]; then
  echo "   ~ WARN: $EQ_WARNINGS warnings, but equilibrium restored"
else
  echo "   ✗ FAIL: $EQ_WARNINGS warnings, no restoration"
fi

# 4. PCR pacing active
echo "4. PCR-paced mux:"
if grep -q "pcr_paced_active=1" "$LOG" || grep -q "PCR-paced mux active" "$LOG"; then
  echo "   ✓ PASS: PCR pacing confirmed"
else
  echo "   ✗ FAIL: No PCR pacing evidence"
fi

# 5. Silence injection disabled
echo "5. Silence injection disabled:"
if grep -q "silence_injection_disabled=true" "$LOG"; then
  echo "   ✓ PASS: Silence injection disabled"
else
  echo "   ✗ FAIL: Silence injection not disabled"
fi

# 6. Producer CT authoritative
echo "6. Producer CT authoritative:"
CT_VIOLATIONS=$(grep -c "INV-P9-STEADY-007 VIOLATION" "$LOG" 2>/dev/null || echo "0")
if grep -q "Producer CT authoritative ENABLED" "$LOG" && [ "$CT_VIOLATIONS" -eq 0 ]; then
  echo "   ✓ PASS: Producer CT authoritative, no violations"
elif [ "$CT_VIOLATIONS" -gt 0 ]; then
  echo "   ✗ FAIL: $CT_VIOLATIONS CT violations"
else
  echo "   ~ WARN: Producer CT mode not confirmed"
fi

echo ""
echo "=== Validation Complete ==="
```

---

## 6. Failure Diagnostics

### 6.1 If Pad Takeover Occurs (INV-P9-STEADY-004 VIOLATION)

**Hypothesis A:** Output is consuming frames faster than producer provides (PCR pacing not active)

**Falsification Test:**
```bash
grep "pcr_paced_active" pkg/air/logs/cheers-24-7-air.log | tail -10
```
- If `pcr_paced_active=0`: PCR pacing never engaged → **Root cause: P9-CORE-002 not implemented or steady-state entry not detected**
- If `pcr_paced_active=1`: Pacing active but buffer still drains → **Check decode rate below**

**Hypothesis B:** Decoder too slow (not keeping up with real-time)

**Falsification Test:**
```bash
grep "decode_fps" pkg/air/logs/cheers-24-7-air.log | tail -5
```
- If `decode_fps < 28` for 30fps content: Decoder bottleneck → **Not a Phase 9 bug; hardware/media issue**

**Hypothesis C:** Buffer target too low

**Falsification Test:**
```bash
grep "depth=" pkg/air/logs/cheers-24-7-air.log | tail -20
```
- If depth oscillates near 0-2: Target depth might be too aggressive
- Expected: depth oscillates around 3 (default target)

---

### 6.2 If Runaway Backpressure (INV-P9-STEADY-005 sustained violation)

**Hypothesis A:** Producer free-running (decode gating not working)

**Falsification Test:**
```bash
grep "slot_gating" pkg/air/logs/cheers-24-7-air.log | head -5
grep "decode_gate" pkg/air/logs/cheers-24-7-air.log | head -5
```
- If no gate logs: **P9-CORE-005 slot-based gating not implemented**
- If gate logs show "resume" without corresponding "block": **Hysteresis present (P9-CORE-005 violation)**

**Hypothesis B:** A/V not symmetric (one stream running ahead)

**Falsification Test:**
```bash
grep "av_delta" pkg/air/logs/cheers-24-7-air.log | tail -10
grep "steady_state_video_count\|steady_state_audio_count" pkg/air/logs/cheers-24-7-air.log
```
- If `|audio_count - video_count| > 5`: **P9-CORE-006 symmetric backpressure not working**

---

### 6.3 If PCR Pacing Not Active

**Hypothesis:** Steady-state entry conditions not met

**Falsification Test:**
```bash
grep "steady_state_entered" pkg/air/logs/cheers-24-7-air.log
grep "output_attached" pkg/air/logs/cheers-24-7-air.log
grep "buffer_depth" pkg/air/logs/cheers-24-7-air.log | head -10
```

**Expected sequence:**
1. Output attach logged
2. Buffer depth reaches threshold (e.g., ≥ 3)
3. `steady_state_entered=true` logged
4. `pcr_paced_active=true` logged

If step 3 never happens: **P9-CORE-001 steady-state entry detection not working**

---

### 6.4 If Silence Injection Still Occurring

**Hypothesis:** `silence_injection_disabled_` flag not set

**Falsification Test:**
```bash
grep "silence_injection" pkg/air/logs/cheers-24-7-air.log
grep "silence_frames_generated" pkg/air/logs/cheers-24-7-air.log
```
- If `silence_injection_disabled=true` logged but silence still generated: **Race condition in EncoderPipeline**
- If `silence_injection_disabled=true` never logged: **P9-CORE-003 not implemented**

---

### 6.5 If CT Violations (PTS jumps)

**Hypothesis A:** Local CT counter still in use

**Falsification Test:**
```bash
grep "audio_ct_us" pkg/air/logs/cheers-24-7-air.log
grep "SetAudioPts" pkg/air/logs/cheers-24-7-air.log
```
- If `audio_ct_us = 0` logged at attach: **P9-CORE-004 local CT removal incomplete**

**Hypothesis B:** Producer CT discontinuous (segment switch issue)

**Falsification Test:**
```bash
grep "segment_switch\|switch_to_live" pkg/air/logs/cheers-24-7-air.log | head -5
```
- If violations occur right after switch: **Phase 8 issue (frozen, do not modify)**

---

## 7. Invariant → Log → Failure Class Mapping

| Invariant | Log Pattern | Failure Class |
|-----------|-------------|---------------|
| INV-P9-STEADY-001 | `pcr_paced_active=1` | PCR pacing not engaged |
| INV-P9-STEADY-001 | `PCR-paced mux active` | Steady-state never entered |
| INV-P9-STEADY-002 | `decode_gate: blocked` | Producer free-running |
| INV-P9-STEADY-002 | `decode_gate: resume` | Hysteresis present |
| INV-P9-STEADY-003 | `av_delta > 1 frame` | Asymmetric backpressure |
| INV-P9-STEADY-004 | `VIOLATION: Pad emitted while depth=N` | CT tracking bug or flow control bug |
| INV-P9-STEADY-005 | `WARNING: Buffer depth N outside equilibrium` | Backpressure or pacing failure |
| INV-P9-STEADY-005 | `equilibrium restored` | Transient (acceptable) |
| INV-P9-STEADY-006 | Frame rate deviation > 1% | Clock drift or pacing error |
| INV-P9-STEADY-007 | `VIOLATION: Audio PTS jumped` | Local CT counter or discontinuity |
| INV-P9-STEADY-007 | `Producer CT authoritative ENABLED` | Correct behavior proof |
| INV-P9-STEADY-008 | `silence_injection_disabled=true` | Correct behavior proof |
| INV-P9-STEADY-008 | `Mux STALLING - audio queue empty` | Acceptable stall (not failure) |

---

## 8. Running Contract Tests

### 8.1 All Phase 9 Contract Tests

```bash
cd pkg/air/build
ctest -R "Phase9" --output-on-failure -j4
```

### 8.2 Individual Test Suites

```bash
# Buffer equilibrium tests
ctest -R "Phase9BufferEquilibrium" --output-on-failure

# No pad while depth high tests
ctest -R "Phase9NoPadWhileDepthHigh" --output-on-failure

# Steady-state silence tests
ctest -R "Phase9SteadyStateSilence" --output-on-failure

# Symmetric backpressure tests
ctest -R "Phase9SymmetricBackpressure" --output-on-failure

# Output bootstrap tests (Phase 9 prerequisite)
ctest -R "Phase9OutputBootstrap" --output-on-failure
```

### 8.3 Test Results Interpretation

**PASS:** Test exits with code 0
**FAIL:** Test exits with non-zero code; check output for assertion failure

---

## 9. Metrics Validation (Optional)

If metrics server is running:

```bash
curl http://localhost:9100/metrics | grep -E "retrovue_steady|retrovue_buffer_equilibrium|retrovue_pad_while_depth"
```

**Expected metrics:**
- `retrovue_steady_state_active{channel_id="..."} 1`
- `retrovue_buffer_equilibrium_violations_total{channel_id="..."} 0`
- `retrovue_pad_while_depth_high_total{channel_id="..."} 0`

---

## 10. Summary: Phase 9 Exit Criteria

| # | Criterion | How to Verify | Threshold |
|---|-----------|---------------|-----------|
| 1 | All P9-CORE-* implemented | Code review + tests | All tasks checked |
| 2 | All P9-TEST-* pass | `ctest -R Phase9` | 0 failures |
| 3 | 60s no pad takeover | grep VIOLATION count | 0 |
| 4 | 60s no runaway backpressure | equilibrium warnings resolve | violations_total stable |
| 5 | 10min continuous playout | VLC + log monitoring | No stops/restarts |
| 6 | No Phase 8 regressions | `ctest -R Phase8` | 0 failures |

---

## Document References

| Document | Purpose |
|----------|---------|
| `docs/contracts/PHASE9_STEADY_STATE_CORRECTNESS.md` | Authoritative invariant definitions |
| `docs/contracts/PHASE9_TASKS.md` | Task checklist |
| `docs/contracts/PHASE9_EXECUTION_PLAN.md` | Implementation strategy |
| `pkg/air/CLAUDE.md` | AIR build and log instructions |
| `pkg/core/CLAUDE.md` | Core CLI and runtime instructions |
