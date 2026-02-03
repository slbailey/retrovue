Task ID: P9-CORE-004
Rule ID: INV-P9-STEADY-007
Governing Law: LAW-TIMELINE
Subsystem: MpegTSOutputSink
Task Type: FIX
File(s) to Modify: pkg/air/src/renderer/MpegTSOutputSink.cpp
Owner: AIR
Blocked By: P9-CORE-002

Instructions:
- Remove any local CT counters in muxer (e.g., `audio_ct_us = 0`)
- Use only producer-provided `frame.ct_us` and `audio_frame.pts_us`
- CT from producer may be hours into channel playback, not 0
- Verify no CT reset on attach or steady-state entry

---

Governing Principle (LAW-TIMELINE):
> TimelineController owns CT mapping; producers are time-blind after lock.

Rule Definition (INV-P9-STEADY-007):
Muxer MUST use producer-provided CT. No local CT counters. No CT resets. Producer computes CT via TimelineController; muxer is a pass-through.

Implementation:

1. REMOVE any local CT initialization:
   ```cpp
   // FORBIDDEN - DELETE THIS:
   int64_t audio_ct_us = 0;

   // FORBIDDEN - DELETE THIS:
   void ResetCT() { audio_ct_us_ = 0; }
   ```

2. Use producer CT directly:
   ```cpp
   void EncodeVideoFrame(const VideoFrame& frame) {
       // Use frame.ct_us directly
       int64_t pts = frame.ct_us;
       // ... encode with pts
   }

   void EncodeAudioFrame(const AudioFrame& frame) {
       // Use frame.pts_us directly - DO NOT substitute local counter
       int64_t pts = frame.pts_us;
       // ... encode with pts
   }
   ```

3. AUDIT for any CT shadowing:
   - Search for `audio_ct_us`, `video_ct_us`, `local_ct`, `ct_counter`
   - Remove any such variables
   - Ensure all encoding uses producer-provided timestamps

4. FORBIDDEN patterns:
   - `int64_t audio_ct_us = 0;`
   - Ignoring `audio_frame.pts_us` from producer
   - Maintaining a separate CT counter that shadows the producer's
   - Resetting CT on attach

Rationale:
Producer CT may start at hours into channel playback (not 0). Muxer resetting to 0 causes audio freeze / A/V desync. Producer owns timeline truth; muxer is a pass-through.

Done Criteria:
No local CT counters in muxer; all encoding uses producer-provided timestamps; CT preserved across attach (e.g., if producer CT = 3600s, first muxed frame PTS = 3600s).
