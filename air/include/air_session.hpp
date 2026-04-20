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
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "channel_canonical.hpp"
#include "frame_types.hpp"

namespace retrovue::air {

class FileSourceProducer;
class StandardNormalizer;
class MpegTsEncoder;
class SocketEmitter;
class EgressPacer;
class BootstrapContentGate;

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
  // (Note: in the current channel-centric build the encoder is constructed
  // here because canonical drives encoder config. In a future device-centric
  // mode the encoder would move into AttachOutput with a device canonical.)
  bool AssignContent(const std::string& input_path,
                     const ChannelCanonical& canonical);

  // Phase 3 — start encode loop. Emission begins at the first pulled frame.
  // Preconditions: AttachOutput and AssignContent both succeeded.
  bool OpenAir();

  // Clean shutdown. Signals encode thread to exit, joins it, closes encoder,
  // closes fd. Idempotent.
  void Close();

  // Inspection.
  bool HasOutput() const { return owned_fd_ >= 0; }
  bool HasContent() const { return source_ != nullptr; }
  bool IsOnAir() const { return encode_thread_.joinable(); }

  // Lifecycle state. Safe to read from any thread.
  SessionState State() const { return state_.load(); }

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

  // ---- Content group (swappable per retune) ----
  std::unique_ptr<FileSourceProducer> source_;
  std::unique_ptr<StandardNormalizer> normalizer_;
  ChannelCanonical canonical_{};
  int audio_samples_per_block_ = 0;

  // ---- Byte-production (today: per-session; future: per-device) ----
  std::unique_ptr<MpegTsEncoder> encoder_;

  // ---- On-air execution ----
  std::unique_ptr<EgressPacer> pacer_;
  std::unique_ptr<BootstrapContentGate> gate_;
  std::thread encode_thread_;
  std::atomic<bool> stopping_{false};
  std::atomic<int64_t> frames_encoded_{0};

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
};

}  // namespace retrovue::air

#endif  // AIR_AIR_SESSION_HPP_
