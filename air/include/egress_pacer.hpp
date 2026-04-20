// AIR vNext — EgressPacer.
//
// Minimal real-time egress pacing. Anchors on the first call, then releases
// each subsequent event at its PTS-relative moment on the monotonic timeline.
//
//   start_mono = monotonic_now() at first WaitFor(pts0)
//   target(pts) = start_mono + (pts - pts0)
//   if now < target: sleep until target
//   if now >= target: return immediately (release late — never throttles,
//                     never speeds up)
//
// Not injected into the Clock vault-authority yet (that's a separate slice);
// uses std::chrono::steady_clock directly. For testing, now/sleep functions
// are injectable via the two-arg constructor.
//
// Product rule: AIR never throttles in response to consumer state. EgressPacer
// throttles in response to *its own clock* — that's the opposite direction,
// and is the broadcast-rate discipline. If the clock says "it's time,"
// release. If compute is behind, release immediately (no make-up burst).
//
// Vault reference: AIR_Pipeline INV-AIR-EGRESS-REALTIME-001.

#ifndef AIR_EGRESS_PACER_HPP_
#define AIR_EGRESS_PACER_HPP_

#include <cstdint>
#include <functional>

namespace retrovue::air {

class EgressPacer {
 public:
  // Production constructor: uses std::chrono::steady_clock and
  // std::this_thread::sleep_for.
  EgressPacer();

  // Test constructor: inject monotonic-now and sleep functions.
  //   now_us_fn()    -> current monotonic time in microseconds.
  //   sleep_us_fn(n) -> block for n microseconds.
  using NowUsFn = std::function<int64_t()>;
  using SleepUsFn = std::function<void(int64_t)>;
  EgressPacer(NowUsFn now_fn, SleepUsFn sleep_fn);

  // Wait until it's the right wall-clock moment to process the event with
  // this PTS (in microseconds, anchor-relative is fine). On the first call,
  // establishes the anchor and returns immediately.
  void WaitFor(int64_t pts_us);

  // Reset the anchor — next WaitFor() will establish a new anchor.
  // Intended for seam / successor transitions that re-anchor the pacing.
  void Reset();

  // Diagnostics.
  bool Anchored() const { return start_mono_us_ >= 0; }
  int64_t TotalSleepUs() const { return total_sleep_us_; }
  int64_t LateReleases() const { return late_releases_; }
  int64_t WaitsIssued() const { return waits_issued_; }

 private:
  NowUsFn now_fn_;
  SleepUsFn sleep_fn_;

  int64_t start_mono_us_ = -1;
  int64_t start_pts_us_ = -1;

  int64_t total_sleep_us_ = 0;
  int64_t late_releases_ = 0;
  int64_t waits_issued_ = 0;
};

}  // namespace retrovue::air

#endif  // AIR_EGRESS_PACER_HPP_
