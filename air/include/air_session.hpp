// AIR vNext — AirSession.
//
// Orchestrates the three-phase startup (AttachOutput → AssignContent →
// OpenAir). Owned member groups are explicitly separated so a future
// device-centric retune can swap content without touching the sink.
//
// Lifecycle:
//   AttachOutput(fd)            — phase 1: sink binding
//   AssignContent(path, canon)  — phase 2: content binding (swappable)
//   OpenAir()                    — phase 3: emission begins (encode loop thread)
//   Close()                      — clean teardown
//
// Vault/memory references:
//   - project_retrovue_air_separation_of_concerns (sink/content/on-air split)
//   - project_retrovue_air_lifecycle_model (bootstrap: first byte is content)
//   - product decisions: never throttle; emit only after fd connected; real-
//     time egress pacing.
//
// Threading: encode loop runs on a dedicated thread started by OpenAir()
// and joined by Close(). gRPC handlers call the three phase methods from
// the gRPC thread; they are non-blocking (no encode work happens inline).

#ifndef AIR_AIR_SESSION_HPP_
#define AIR_AIR_SESSION_HPP_

#include <atomic>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "block.hpp"
#include "block_runtime.hpp"
#include "channel_canonical.hpp"
#include "frame_types.hpp"
#include "priming_pipeline.hpp"
#include "seam_controller.hpp"

namespace retrovue::air {

class MpegTsEncoder;
class SocketEmitter;
class EgressPacer;
class BootstrapContentGate;
class PadSourceProducer;
class IdentityNormalizer;

// Session lifecycle states. See LIFECYCLE_DESIGN.md for the full state
// machine (entry/exit rules, transitions, telemetry).
//
//   Warming   — OpenAir() has started the encode thread; pre-buffering
//               frames, byte path HELD CLOSED (no encoder calls yet).
//   Ready     — Transient: bootstrap gate has fired conditions-met but
//               commit hasn't run yet. Exists as an observable waypoint;
//               the encode thread passes through in one step.
//   OnAir     — Encoder is receiving frames; bytes flowing. Sticky — the
//               system does NOT regress to Warming from here. Pad
//               substitution (future) happens WITHIN OnAir.
//   Stopping  — Close() in progress. Terminal.
//   FailedStart — Irrecoverable pre-OnAir error. Terminal. reason_class
//               available via FailedStartReason().
enum class SessionState {
  Warming,
  Ready,
  OnAir,
  Stopping,
  FailedStart,
};

const char* ToString(SessionState s);

// Structured lifecycle event emitted on every state transition in the
// encode thread. Consumed by an optional LifecycleObserver for logging,
// metrics, or test inspection.
struct StateTransitionEvent {
  int64_t mono_us;          // monotonic timestamp of the transition
  SessionState from;
  SessionState to;
  std::string reason_class; // optional detail, e.g. "SOURCE_EOF_DURING_WARMUP"
};

using LifecycleObserver = std::function<void(const StateTransitionEvent&)>;

class AirSession {
 public:
  AirSession();
  ~AirSession();

  AirSession(const AirSession&) = delete;
  AirSession& operator=(const AirSession&) = delete;

  // Phase 1 — sink attachment. Takes ownership of fd (will close on Close()).
  // Returns false if a session is already active or fd is invalid.
  bool AttachOutput(int fd);

  // Phase 2 — content assignment. Builds source + normalizer + encoder.
  // Preconditions: AttachOutput has been called. Returns false on error
  // (decoder open failure, canonical mismatch, etc.).
  //
  // Two entry points:
  //   AssignContent(path, canonical) — legacy single-file mode. Synthesizes
  //     an internal one-segment Block with a generated block_id. Kept for
  //     backward compatibility with tests that pre-date the segment model.
  //   SeedActiveBlock(block) — queue-based mode. active_block_ is the full
  //     supplied Block record (with its 1..N segment list). Used by
  //     StartChannel when seed_block is provided.
  //
  // In Phase B, both paths establish active_block_ with active_segment_index_=0
  // and leave queued_blocks_ empty. Playback in Phase B still consumes only
  // segment[0] of the active block through to EOF; multi-segment execution
  // and seams arrive in Phase C (SeamController).
  //
  // (Note: in the current channel-centric build the encoder is constructed
  // here because canonical drives encoder config. In a future device-centric
  // mode the encoder would move into AttachOutput with a device canonical.)
  bool AssignContent(const std::string& input_path,
                     const ChannelCanonical& canonical);
  bool SeedActiveBlock(const Block& block);

  // Phase 2b — append a queued block via SupplyBlock RPC. Core pushes; AIR
  // stores. Phase B scope: simple append with basic validation (segments
  // non-empty, session exists). Mutation rules for armed/primed states
  // land in Phase C+.
  //
  // Returns false on rejection; `reason_out` carries a stable reason code:
  //   "NO_SESSION" — no active session to append to.
  //   "EMPTY_SEGMENTS" — block has zero segments (malformed per truth).
  //   (Future: BLOCK_ALREADY_QUEUED, CANONICAL_MISMATCH.)
  bool AddQueuedBlock(const Block& block,
                      const std::string& predecessor_id,
                      std::string* reason_out = nullptr);

  // Phase 3 — start encode loop. Emission begins at the first pulled frame.
  // Preconditions: AttachOutput and AssignContent both succeeded.
  bool OpenAir();

  // Clean shutdown. Signals encode thread to exit, joins it, closes encoder,
  // closes fd. Idempotent.
  void Close();

  // Install a lifecycle observer. Called on every state transition from the
  // encode thread. Set before OpenAir() — not thread-safe to change after
  // the encode thread starts. If no observer is set, a default observer
  // logs structured events to stderr.
  void SetLifecycleObserver(LifecycleObserver obs);

  // Inspection.
  bool HasOutput() const { return owned_fd_ >= 0; }
  bool HasContent() const;
  bool IsOnAir() const { return encode_thread_.joinable(); }

  // Expose the execution queue for tests. Not thread-safe against
  // concurrent mutation; intended for post-teardown or pre-OpenAir
  // inspection, and for integration tests that read state while the
  // encode thread is active but is the only mutator.
  const std::optional<BlockRuntime>& ActiveBlock() const { return active_block_; }
  int32_t ActiveSegmentIndex() const { return active_segment_index_.load(); }

  // Seam-execution diagnostics (updated only from the encode thread).
  int64_t SeamsExecuted() const { return seams_executed_.load(); }

  // Pad-bridge diagnostics. A pad bridge is engaged (C1.4b) when a
  // segment fence arrives before the successor segment is primed. Count
  // is distinct events; ms is cumulative time in pad.
  int64_t PadBridgeEventsTotal() const { return pad_bridge_events_total_.load(); }
  int64_t PadBridgeMsTotal() const { return pad_bridge_ms_total_.load(); }

  // Test hook: inject an artificial sleep before the priming worker
  // returns the next raw PrimingRequest. Used by integration tests to
  // force a genuinely late successor without fake-priming shortcuts.
  // Default 0 = no delay. Safe to set before OpenAir; changes after
  // OpenAir take effect on subsequent priming decisions.
  void SetTestPrimeDelayMs(int64_t ms) { test_prime_delay_ms_.store(ms); }

  // Test hook (multi-segment): per-prime-call delays. Element i is the
  // delay applied to the i-th prime invocation; beyond size, delay is 0.
  // When set to non-empty, takes precedence over SetTestPrimeDelayMs.
  // Must be set before OpenAir; the worker captures the vector by
  // reference via `this` and relies on no mutation after start.
  void SetTestPrimeDelaysMs(std::vector<int64_t> delays) {
    test_prime_delays_ms_ = std::move(delays);
  }

  // Lifecycle state. Safe to read from any thread.
  SessionState State() const { return state_.load(); }

  // Queue diagnostics. Thread-safe.
  //
  // QueueDepth reports Blocks (editorial grain, per
  // INV-QUEUE-DEPTH-AIR-PRIVATE-001): active block (0/1) + queued count.
  //
  // SegmentDepth reports the internal total Segments across active block +
  // queued blocks. Diagnostic only; does not imply execution order beyond
  // the grain.
  int32_t QueueDepth() const;
  int32_t SegmentDepth() const;

  // Diagnostics snapshot (atomic reads of encode-thread state).
  int64_t FramesEncoded() const { return frames_encoded_.load(); }
  int64_t BytesWritten() const;
  int64_t BytesDropped() const;
  int64_t PacerSleepMs() const;
  int64_t PacerLateReleases() const;

  // Bootstrap lifecycle diagnostics.
  // WarmingDurationUs: time spent in Warming before hitting Ready. -1 if
  //   never left Warming. Set once when Ready is entered.
  // BootstrapTotalDurationUs: Warming entry → OnAir entry. -1 if never
  //   reached OnAir. In practice equals WarmingDurationUs + ~0 (Ready is
  //   transient).
  // FailedStartReason: stable reason class string if state is FailedStart,
  //   else empty.
  int64_t WarmingDurationUs() const { return warming_duration_us_.load(); }
  int64_t BootstrapTotalDurationUs() const {
    return bootstrap_total_duration_us_.load();
  }
  std::string FailedStartReason() const;

 private:
  // ---- Sink group (swappable independently; persists across retune) ----
  std::unique_ptr<SocketEmitter> emitter_;
  int owned_fd_ = -1;

  // ---- Content group: canonical config + audio block size ----
  // Per-segment source + normalizer live inside active_block_ /
  // queued_blocks_ (BlockRuntime.segment_runtimes[i]). AirSession no longer
  // holds its own source_ / normalizer_ members — C1.4a unified ownership
  // into BlockRuntime so there is a single active-source owner.
  ChannelCanonical canonical_{};
  int audio_samples_per_block_ = 0;

  // Execution queue. active_block_ is populated by SeedActiveBlock or
  // synthesized by AssignContent (legacy mode). active_segment_index_
  // cursors into active_block_->block().segments. queued_blocks_ receives
  // AddQueuedBlock appends. Mutated only from the gRPC handler thread
  // (serialized by AirControlServiceImpl::mu_). Guarded by queue_mutex_
  // for read-safety from diagnostic accessors.
  //
  // As of C1.3.5, storage is BlockRuntime (not bare Block): each queued
  // Block carries its parallel per-Segment runtime state (raw / priming /
  // primed / failed) and owns the primed FileSourceProducer +
  // StandardNormalizer per segment. PrimingPipeline writes into this
  // state via AirSession hooks (C1.4a); SeamController reads readiness
  // from it via a callback. Active-segment tracking remains on AirSession
  // (active_segment_index_), not SeamController.
  mutable std::mutex queue_mutex_;
  std::optional<BlockRuntime> active_block_;
  // Cursor into active_block_->block().segments. Written only from the
  // encode thread (OpenAir-entry set, seam advance); read from diagnostic
  // accessors. Atomic so readers don't need queue_mutex_.
  std::atomic<int32_t> active_segment_index_{0};
  std::deque<BlockRuntime> queued_blocks_;

  // ---- Byte-production (today: per-session; future: per-device) ----
  std::unique_ptr<MpegTsEncoder> encoder_;

  // ---- On-air execution ----
  std::unique_ptr<EgressPacer> pacer_;
  std::unique_ptr<BootstrapContentGate> gate_;
  std::thread encode_thread_;
  std::atomic<bool> stopping_{false};
  std::atomic<int64_t> frames_encoded_{0};
  std::atomic<int64_t> seams_executed_{0};
  std::atomic<int64_t> pad_bridge_events_total_{0};
  std::atomic<int64_t> pad_bridge_ms_total_{0};
  std::atomic<int64_t> test_prime_delay_ms_{0};
  std::vector<int64_t> test_prime_delays_ms_;
  std::atomic<std::size_t> test_prime_call_idx_{0};
  LifecycleObserver lifecycle_observer_;

  // ---- Seam controller + priming pipeline ----
  // SeamController (C1.4a): owns seam lifecycle; driven by the encode
  // loop. Readiness callback reads BlockRuntime::IsPrimed(next_index).
  // PrimingPipeline (C1.4b): async worker that primes kRaw segments in
  // the execution queue. Started by OpenAir, stopped by Close before
  // BlockRuntime teardown so worker never outlives the state it touches.
  std::unique_ptr<SeamController> seam_controller_;
  std::unique_ptr<PrimingPipeline> priming_pipeline_;

  // ---- Pad bridge state (encode-thread local) ----
  // Engaged when a segment fence arrives before the successor is primed.
  // pad_source_/pad_normalizer_ emit broadcast-safe continuity content
  // through the SAME encoder + pacer (encoder continuity). Reset per
  // engagement so each bridge starts with fresh PTS bookkeeping.
  std::unique_ptr<PadSourceProducer> pad_source_;
  std::unique_ptr<IdentityNormalizer> pad_normalizer_;
  bool in_pad_bridge_ = false;
  int64_t pad_bridge_start_mono_us_ = 0;
  int64_t pad_frames_in_current_bridge_ = 0;

  // Session anchor. Established at OnAir entry: maps monotonic time to
  // wall-clock UTC so segment fence ticks can be computed via
  // SegmentFenceMonotonicUs (INV-SEAM-FENCE-ARITHMETIC-001).
  int64_t anchor_monotonic_us_ = 0;
  int64_t anchor_utc_ms_ = 0;

  // Channel-PTS offset applied to frames pulled from the current segment's
  // normalizer. Each segment's normalizer emits pts_us_relative starting
  // from 0; we add this accumulator so channel PTS does not regress across
  // a seam swap (encoder continuity criterion).
  int64_t channel_pts_offset_us_ = 0;

  // Warmup pre-buffer. Populated during Warming; drained at OnAir entry
  // before further pulls from normalizer resume. These live on the encode
  // thread — not thread-safe, accessed only from EncodeLoop.
  std::deque<VideoFrame> warmup_video_;
  std::deque<AudioBlock> warmup_audio_;

  // Lifecycle state. Transitions are written by the encode thread (for
  // Warming/Ready/OnAir/FailedStart) and by Close() (for Stopping).
  std::atomic<SessionState> state_{SessionState::Warming};

  // Bootstrap diagnostics (written on state transition into that phase).
  std::atomic<int64_t> warming_duration_us_{-1};
  std::atomic<int64_t> bootstrap_total_duration_us_{-1};
  // FailedStart reason. Guarded by failed_start_mutex_ (written on the
  // encode thread, read via FailedStartReason()).
  mutable std::mutex failed_start_mutex_;
  std::string failed_start_reason_;

  // Encode loop body run by encode_thread_.
  void EncodeLoop();

  // Helper: set FailedStart with reason class + mark state_.
  void FailStart(const char* reason_class);

  // Helper: atomic state transition + lifecycle event emission.
  void TransitionTo(SessionState to, const char* reason_class);

  // Helper: construct FileSourceProducer + StandardNormalizer for the
  // named segment and install as kPrimed into the given BlockRuntime.
  // Returns false on prepare/activate failure (segment is marked
  // kFailed with a reason). Scope: synchronous upfront priming used by
  // SeedActiveBlock / AssignContent in the C1.4a happy path; async
  // priming via PrimingPipeline lands later.
  bool PrimeSegmentSync(BlockRuntime& rt, int32_t segment_index);

  // Helper: observe the seam from (active_segment_index_) to
  // (active_segment_index_ + 1) on the SeamController, using the fence
  // arithmetic from segment_fence.hpp and the session anchor. Pre: next
  // segment exists.
  void ObserveNextSeam();

  // PrimingPipeline::Hooks::next_raw impl. Scans active_block_ forward
  // from (active_segment_index_ + 1) for the first kRaw segment and
  // returns a PrimingRequest for it, or nullopt if none.
  std::optional<PrimingRequest> FindNextRawSegment();

  // Engage pad bridge: fence passed with successor not yet primed.
  // Retires the current segment (sets kRetired, advances offset),
  // constructs pad source + normalizer, flags in_pad_bridge_.
  void EngagePadBridge();
};

}  // namespace retrovue::air

#endif  // AIR_AIR_SESSION_HPP_
