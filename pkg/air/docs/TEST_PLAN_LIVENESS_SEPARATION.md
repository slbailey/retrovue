# Test Plan: Upstream/Downstream Liveness Separation

## Summary of Changes

The previous implementation conflated two independent failure modes:
1. **Upstream starvation**: No frames arriving from the producer/decoder
2. **Downstream backpressure**: Consumer (Core) not draining the UNIX socket

This caused false "LAW-OUTPUT-LIVENESS VIOLATION" logs when Core temporarily
stopped reading, even though frames were flowing correctly from the producer.
The code would incorrectly trigger fallback mode due to downstream issues.

### What Was Wrong

```
OLD LOGIC (CONFLATED):
  GetLastAcceptedTime() stall detected
      → Log "LAW-OUTPUT-LIVENESS VIOLATION"
      → Enter fallback mode (WRONG!)
      → Eventually: SLOW CONSUMER DETACH
```

The `GetLastAcceptedTime()` only updates when SocketSink successfully delivers
bytes to the kernel via `send()`. If Core stops reading, the kernel buffer fills,
send() blocks/fails, and the timestamp stops updating - even though frames are
still arriving from upstream.

### What Is Now Correct

```
NEW LOGIC (SEPARATED):

1. DOWNSTREAM STALL DETECTOR (socket_sink_->GetLastAcceptedTime()):
   - Checks: Has SocketSink delivered bytes to kernel recently?
   - If stalled: Log "DOWNSTREAM STALL: no socket progress for Xms (consumer not draining)"
   - Response: Throttle writes (high-water/low-water), DO NOT enter fallback

2. UPSTREAM STARVATION DETECTOR (last_real_frame_dequeue_time_):
   - Checks: Have real frames been dequeued from producer recently?
   - If starved: Log "UPSTREAM STARVATION: no real frames dequeued for Xms"
   - Response: MAY enter fallback mode (emit pad/freeze frames)
```

### Additional Fixes

- **Late frame threshold**: Only count frames as "late" if >2ms past target (not 1us)
- **Warning accuracy**: Changed "All frames arrived late" to only fire if >80% are >2ms late
- **Throttling instead of detach**: SocketSink now uses high-water/low-water marks
  instead of immediately detaching on buffer overflow

---

## Manual Test Plan

### Test 1: Downstream Stall (Consumer Not Draining)

**Steps:**
1. Start AIR with a channel
2. Attach a consumer socket but DO NOT read from it
3. Observe logs for 5-10 seconds

**Expected Results:**
- [ ] Log shows: `DOWNSTREAM STALL: no socket progress for Xms (consumer not draining)`
- [ ] Log shows: `HIGH-WATER MARK: ... (throttling ON)`
- [ ] Log does NOT show: `UPSTREAM STARVATION` (unless producer actually stalls)
- [ ] AIR does NOT enter fallback mode (no freeze/black frames)
- [ ] AIR does NOT immediately detach (no `SLOW CONSUMER DETACH`)
- [ ] After ~10s: may see throttle warning but connection stays alive

**Rationale:**
Proves that downstream backpressure is correctly identified and does NOT
trigger false fallback or detach.

---

### Test 2: Normal Operation (Consumer Draining)

**Steps:**
1. Start AIR with a channel
2. Attach a consumer that reads continuously (e.g., VLC, ffplay)
3. Stream for 60+ seconds

**Expected Results:**
- [ ] No `DOWNSTREAM STALL` logs
- [ ] No `UPSTREAM STARVATION` logs (unless segment boundaries)
- [ ] No `HIGH-WATER MARK` / `LOW-WATER MARK` logs (buffer stays healthy)
- [ ] Pacing logs show reasonable timing (most frames on-time)
- [ ] No false "All frames arrived late" warnings
- [ ] Continuous playback without stalls

**Rationale:**
Confirms normal operation is not disrupted by the new detection logic.

---

### Test 3: Upstream Starvation (Producer Stall)

**Steps:**
1. Start AIR with a channel
2. Attach a consumer that reads continuously
3. Artificially stall the producer (e.g., pause source file, kill FileProducer)
4. Observe logs

**Expected Results:**
- [ ] Log shows: `UPSTREAM STARVATION: no real frames dequeued for Xms`
- [ ] Log shows: `INV-FALLBACK-001: Grace window expired ... entering fallback mode`
- [ ] Log shows: `INV-TICK-GUARANTEED-OUTPUT: Entering fallback mode`
- [ ] No `DOWNSTREAM STALL` logs (consumer is still draining)
- [ ] Output continues (freeze frames or black frames)

**Rationale:**
Confirms that true upstream starvation correctly triggers fallback, while
the detector correctly identifies it as upstream (not downstream) issue.

---

### Test 4: Recovery From Downstream Stall

**Steps:**
1. Start AIR with a channel
2. Attach consumer but DO NOT read (trigger downstream stall)
3. Wait for `HIGH-WATER MARK` / `DOWNSTREAM STALL` logs
4. Start reading from the consumer socket
5. Observe logs

**Expected Results:**
- [ ] Log shows: `LOW-WATER MARK: ... (throttling OFF)`
- [ ] Status returns to normal (no permanent degradation)
- [ ] Playback resumes without requiring reconnection

**Rationale:**
Confirms that temporary downstream stalls can recover gracefully.

---

## Files Changed

- `pkg/air/include/retrovue/output/SocketSink.h` - Added throttling callbacks and state
- `pkg/air/src/output/SocketSink.cpp` - Implemented high-water/low-water throttling
- `pkg/air/include/retrovue/output/MpegTSOutputSink.h` - Added constants for thresholds
- `pkg/air/src/output/MpegTSOutputSink.cpp` - Split liveness detection, fixed late counting
