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
#include <memory>
#include <string>
#include <thread>

#include "channel_canonical.hpp"

namespace retrovue::air {

class FileSourceProducer;
class StandardNormalizer;
class MpegTsEncoder;
class SocketEmitter;
class EgressPacer;

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

  // Diagnostics snapshot (atomic reads of encode-thread state).
  int64_t FramesEncoded() const { return frames_encoded_.load(); }
  int64_t BytesWritten() const;
  int64_t BytesDropped() const;
  int64_t PacerSleepMs() const;
  int64_t PacerLateReleases() const;

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
  std::thread encode_thread_;
  std::atomic<bool> stopping_{false};
  std::atomic<int64_t> frames_encoded_{0};

  // Encode loop body run by encode_thread_.
  void EncodeLoop();
};

}  // namespace retrovue::air

#endif  // AIR_AIR_SESSION_HPP_
