// AIR vNext — PrimingPipeline.
//
// Owns the raw → priming → primed / failed transitions for queued Segments
// per INV-SEGMENT-PRIMING-SINGLE-001: at most one Segment in `priming` state
// at a time (v1 simplification).
//
// Decoupled from AirSession by design: PrimingPipeline does not reach into
// the execution queue directly. The owner supplies callbacks that expose
// "next raw segment to prime" and receive state-transition notifications +
// primed-source delivery. SeamController and AirSession integration (C1.3+)
// wire these hooks; C1.2 exercises the pipeline in isolation against a fake
// queue.
//
// Scope strictly priming:
//   - No seam logic.
//   - No encode-loop swap.
//   - No block promotion.
//   - No pad-bridge / late-successor handling (C1.4b).
//
// Threading: a single dedicated worker thread owns PrimeOne(). Structural
// single-worker enforcement of INV-SEGMENT-PRIMING-SINGLE-001. Kick() signals
// the worker that new raw segments may be available.

#ifndef AIR_PRIMING_PIPELINE_HPP_
#define AIR_PRIMING_PIPELINE_HPP_

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#include "channel_canonical.hpp"

namespace retrovue::air {

class FileSourceProducer;
class StandardNormalizer;

// Per-Segment runtime state machine:
//   kRaw → kPriming → kPrimed → kActive → kRetired
//          └→ kFailed
//
// Priming transitions (kRaw → kPriming → kPrimed/kFailed) are owned by
// PrimingPipeline. Activation and retirement (kPrimed → kActive → kRetired)
// are owned by AirSession's encode loop around seam firing (C1.4a). The
// SeamController's kArmed phase is coincident with but distinct from
// SegmentPrimeState — seam phase is SeamController's state, segment state
// stays with BlockRuntime.
enum class SegmentPrimeState {
  kRaw,
  kPriming,
  kPrimed,
  kActive,   // currently being emitted (active_segment_index_ points at it)
  kRetired,  // seam swapped past; source retired, normalizer dropped
  kFailed,
};

const char* ToString(SegmentPrimeState s);

// Identifies a Segment to be primed. Everything needed to construct the
// per-segment FileSourceProducer + StandardNormalizer.
struct PrimingRequest {
  std::string block_id;
  int32_t segment_index = 0;
  std::string asset_uri;
  int64_t asset_start_offset_ms = 0;
  ChannelCanonical canonical{};
  // Samples per channel audio block (~ one video-frame-period at channel
  // audio rate). Passed through to the StandardNormalizer. v1: fixed by
  // caller; 1601 for 30000/1001 @ 48kHz.
  int samples_per_channel_audio_block = 1601;
};

// Successful prime output. The primed source is Activated; the normalizer
// borrows it. Ownership transfers to the hook via on_primed; SeamController
// (C1.3+) will install this pair at seam firing.
struct PrimedSegment {
  std::string block_id;
  int32_t segment_index = 0;
  std::unique_ptr<FileSourceProducer> source;
  std::unique_ptr<StandardNormalizer> normalizer;
};

// Structured priming event. Consumed by LifecycleObserver-style hooks for
// logs, metrics, and test inspection. Mirrors the segment.prime_* event
// surface declared in PHASE_C_IMPLEMENTATION_PLAN.md §Structured events.
enum class PrimingEventKind {
  kStarted,    // segment.prime_started
  kCompleted,  // segment.prime_complete
  kFailed,     // segment.prime_failed
};

const char* ToString(PrimingEventKind k);

struct PrimingEvent {
  PrimingEventKind kind;
  int64_t mono_us = 0;
  std::string block_id;
  int32_t segment_index = 0;
  std::string reason;  // populated only for kFailed
};

using PrimingEventObserver = std::function<void(const PrimingEvent&)>;

// Stable reason codes for prime failure. Written to PrimingEvent.reason and
// forwarded through on_failed. The set is deliberately small in v1; refine
// as real failure modes surface.
inline constexpr const char* kPrimeFailAssetOpen = "ASSET_OPEN_FAILED";
inline constexpr const char* kPrimeFailActivate  = "ACTIVATE_FAILED";
inline constexpr const char* kPrimeFailNoStreams = "NO_VIDEO_OR_AUDIO_STREAM";
inline constexpr const char* kPrimeFailInvalidCanonical = "INVALID_CANONICAL";

class PrimingPipeline {
 public:
  // Integration hooks. Called from the worker thread (when Start()ed) or
  // the caller thread (when using RunOnce()). Implementations must be
  // thread-safe w.r.t. their own state.
  struct Hooks {
    // Return the next raw Segment to prime, or nullopt if nothing is
    // available right now. Pipeline polls this after Kick() and after each
    // completed prime.
    std::function<std::optional<PrimingRequest>()> next_raw;

    // Notify owner that the named Segment is transitioning raw → priming.
    // Called BEFORE the prime work begins.
    std::function<void(const std::string& block_id, int32_t segment_index)>
        on_priming;

    // Deliver the primed source + normalizer on success. Ownership transfers
    // to the owner. Segment state should be set to kPrimed.
    std::function<void(PrimedSegment)> on_primed;

    // Notify owner of prime failure with a stable reason code. Segment state
    // should be set to kFailed.
    std::function<void(const std::string& block_id,
                       int32_t segment_index,
                       const std::string& reason)> on_failed;
  };

  explicit PrimingPipeline(Hooks hooks);
  ~PrimingPipeline();

  PrimingPipeline(const PrimingPipeline&) = delete;
  PrimingPipeline& operator=(const PrimingPipeline&) = delete;

  // Install event observer. Set before Start(); changing observers while
  // the worker runs is not supported.
  void SetEventObserver(PrimingEventObserver obs);

  // Start the worker thread. Idempotent (second call is a no-op). Worker
  // sleeps until Kick() is called.
  void Start();

  // Signal the worker that raw segments may be available. Safe to call
  // from any thread. No-op if the pipeline is not Start()ed.
  void Kick();

  // Signal the worker to exit and join it. Idempotent. Any in-flight prime
  // completes before join returns.
  void Stop();

  // Synchronous one-shot: try to prime exactly one segment in the calling
  // thread. Returns true if a segment was attempted (success OR failure);
  // false if hooks_.next_raw() returned nullopt. Must NOT be called while
  // the worker thread is running — synchronous and asynchronous paths are
  // mutually exclusive.
  bool RunOnce();

  // True if a prime is currently executing. Used by tests to assert
  // INV-SEGMENT-PRIMING-SINGLE-001. Thread-safe.
  bool IsPriming() const { return priming_in_progress_.load(); }

 private:
  void WorkerLoop();

  // Execute one prime attempt. Emits kStarted, attempts prepare+activate,
  // emits kCompleted or kFailed, delivers via hooks.
  void PrimeOne(const PrimingRequest& req);

  void Emit(const PrimingEvent& ev);

  Hooks hooks_;
  PrimingEventObserver observer_;

  std::thread worker_;
  std::mutex mu_;
  std::condition_variable cv_;
  bool stop_ = false;
  bool kicked_ = false;
  bool started_ = false;
  std::atomic<bool> priming_in_progress_{false};
};

}  // namespace retrovue::air

#endif  // AIR_PRIMING_PIPELINE_HPP_
