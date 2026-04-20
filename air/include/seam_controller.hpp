// AIR vNext — SeamController (C1.3 minimal, intra-block scope).
//
// Owns the seam lifecycle for a single segment transition:
//
//   kIdle → kObserving → kArmed → kCommittedForTick → kFiring → kComplete
//
// Retract() can transition kObserving or kArmed → kIdle (emits
// seam.disarmed). Once kCommittedForTick is reached, the target tick is
// locked per INV-SEGMENT-SEAM-ARM-COMMIT-001 ("firing at tick F is
// deterministic; there is no re-evaluation at F") and the seam MUST execute.
//
// SeamController does NOT own queue state. Segment readiness is queried
// via an injected callback; fence ticks are supplied as inputs to
// ObserveSeam(). State storage lives in BlockRuntime (AirSession-owned),
// not here.
//
// Scope in C1.3:
//   - State machine + transitions.
//   - Arm decision (fence within arm_window_us AND next segment primed).
//   - ShouldCommitAt(current_tick) predicate for the encode loop.
//   - Events: seam.armed / seam.disarmed / seam.committed / seam.executed.
//   - No source swap. No encode-loop wiring. No block promotion.
//     Pad-bridge / late-successor handling (C1.4b) is out of scope.
//
// Threading: SeamController is NOT thread-safe. The encode loop is expected
// to be the sole caller of Tick / ShouldCommitAt / MarkFired. ObserveSeam
// and Retract are called either before the encode loop starts or from the
// same thread. Cross-thread use requires external synchronization.

#ifndef AIR_SEAM_CONTROLLER_HPP_
#define AIR_SEAM_CONTROLLER_HPP_

#include <cstdint>
#include <functional>
#include <optional>
#include <string>

namespace retrovue::air {

// Seam lifecycle phases. Monotonic progression under normal operation;
// Retract() can transition kObserving or kArmed → kIdle and is the only
// mechanism that "resets" the controller.
enum class SeamPhase {
  kIdle,              // No target.
  kObserving,         // Target recorded; arm conditions not yet met.
  kArmed,             // Arm window open AND next segment primed.
  kCommittedForTick,  // Target tick locked; firing is deterministic.
  kFiring,            // current_tick has reached target; swap is due now.
  kComplete,          // MarkFired() received; seam retired.
};

const char* ToString(SeamPhase p);

// The seam target: the transition from one Segment to the next. Populated
// by the caller when ObserveSeam() is invoked. from_* identifies the
// segment whose fence is being armed (i.e., the segment ending); to_*
// identifies the segment that will take over at fence. For intra-block
// seams (C1), from_block_id == to_block_id. For inter-block seams (C2),
// they differ and is_block_transition is set.
struct SeamTarget {
  std::string from_block_id;
  int32_t from_segment_index = 0;
  std::string to_block_id;
  int32_t to_segment_index = 0;
  // Fence tick in monotonic microseconds. Computed by the caller via
  // segment_fence::SegmentFenceMonotonicUs() (INV-SEAM-FENCE-ARITHMETIC-001).
  int64_t fence_monotonic_us = 0;
  // C2 flag: set when this seam crosses a Block boundary. Emitted on
  // seam.executed. For C1 intra-block seams, always false.
  bool is_block_transition = false;
};

struct SeamConfig {
  // Arm window. The seam arms when (fence_monotonic_us - current_tick_us)
  // falls at or below this value AND the next segment is primed. Default
  // 1,000,000 us ≈ 30 frames at 30fps (per PHASE_C arm_window_frames=30).
  int64_t arm_window_us = 1'000'000;
};

enum class SeamEventKind {
  kArmed,      // seam.armed
  kDisarmed,   // seam.disarmed
  kCommitted,  // seam.committed
  kExecuted,   // seam.executed
};

const char* ToString(SeamEventKind k);

struct SeamEvent {
  SeamEventKind kind;
  int64_t mono_us = 0;
  SeamTarget target;
  // Populated only for kDisarmed.
  std::string reason;
  // Populated only for kExecuted.
  int64_t executed_at_tick_us = 0;
};

using SeamEventObserver = std::function<void(const SeamEvent&)>;

// Callback: is the to-segment of the current target primed and ready to
// install at seam? SeamController queries this during Tick() to make arm /
// commit decisions. Returning false while armed keeps the controller in
// kArmed; only Retract() demotes.
using NextSegmentReadyFn = std::function<bool()>;

class SeamController {
 public:
  SeamController(SeamConfig cfg, NextSegmentReadyFn next_ready);

  SeamController(const SeamController&) = delete;
  SeamController& operator=(const SeamController&) = delete;

  void SetEventObserver(SeamEventObserver obs);

  // Begin observing a new seam. Pre: Phase() is kIdle or kComplete.
  // Transitions to kObserving. target.fence_monotonic_us must be finite
  // and >= any prior target's fence (fences are strictly increasing
  // across segments per C1.1 arithmetic); caller's responsibility.
  void ObserveSeam(SeamTarget target);

  // Cancel the current target without firing. Valid only from kObserving
  // or kArmed. Emits seam.disarmed with `reason` and returns to kIdle.
  // From kCommittedForTick or kFiring, Retract is a no-op — commit is
  // sticky per INV-SEGMENT-SEAM-ARM-COMMIT-001. Returns true if a disarm
  // was performed.
  bool Retract(const std::string& reason);

  // Advance state based on current_tick_us. Called by the encode loop on
  // a regular cadence. Transitions:
  //   kObserving → kArmed         when (fence - current) <= arm_window
  //                               AND next_ready() returns true.
  //                               Emits seam.armed.
  //   kArmed     → kCommittedForTick
  //                               on the next Tick after kArmed, provided
  //                               next_ready() is still true. Emits
  //                               seam.committed with target fence tick.
  //   kCommittedForTick → kFiring when current_tick_us >= fence_monotonic_us.
  //                               No event; seam.executed fires on
  //                               MarkFired().
  //   kFiring    → (no auto-transition; waits for MarkFired).
  //
  // Monotonic only. Never regresses.
  void Tick(int64_t current_tick_us);

  // Predicate used by the encode loop each frame. Pure read, no state
  // mutation. Returns true iff Phase() == kFiring.
  bool ShouldCommitAt(int64_t current_tick_us) const;

  // Called by the encode loop after performing the swap. Transitions
  // kFiring → kComplete and emits seam.executed. Pre: Phase() is kFiring.
  // Violating this is a contract error (asserts in debug, no-op in release).
  void MarkFired(int64_t current_tick_us);

  // Reset to kIdle, clearing the target. Used by the encode loop (or tests)
  // after kComplete to accept the next ObserveSeam. Idempotent from kIdle.
  void Reset();

  // Inspection.
  SeamPhase Phase() const { return phase_; }
  const std::optional<SeamTarget>& CurrentTarget() const { return target_; }
  const SeamConfig& Config() const { return cfg_; }

 private:
  void Emit(const SeamEvent& ev);

  SeamConfig cfg_;
  NextSegmentReadyFn next_ready_;
  SeamEventObserver observer_;

  SeamPhase phase_ = SeamPhase::kIdle;
  std::optional<SeamTarget> target_;
};

}  // namespace retrovue::air

#endif  // AIR_SEAM_CONTROLLER_HPP_
