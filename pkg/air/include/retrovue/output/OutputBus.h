// Repository: Retrovue-playout
// Component: OutputBus
// Purpose: Signal path that routes frames to attached output sinks.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_OUTPUT_BUS_H_
#define RETROVUE_OUTPUT_OUTPUT_BUS_H_

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>

#include "retrovue/output/IOutputSink.h"

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}  // namespace retrovue::buffer

namespace retrovue::runtime {
class PlayoutControl;
}  // namespace retrovue::runtime

namespace retrovue::output {

// Result of an attach/detach operation.
struct OutputBusResult {
  bool success;
  std::string message;

  OutputBusResult(bool s, const std::string& msg) : success(s), message(msg) {}
};

// OutputBus represents the program output signal of a single Air playout session.
//
// OutputBus is a signal path, not a transport.
//
// OutputBus responsibilities:
// - Exists for the lifetime of a playout session
// - Receives rendered video and audio frames
// - Routes frames to currently attached output sinks
// - Manages attachment and detachment of sinks
// - Is governed by PlayoutControl
//
// OutputBus explicitly does NOT:
// - Open sockets
// - Encode media
// - Write bytes
// - Own threads
// - Know about TCP, UDS, files, or protocols
// - Make timing or scheduling decisions
//
// Current enforced invariant: OutputBus allows at most one attached sink.
// Policy is enforced by PlayoutControl, not by OutputBus itself.
class OutputBus {
 public:
  // Constructs an OutputBus with a reference to the state machine for validation.
  // The state machine pointer may be null (no validation performed).
  explicit OutputBus(runtime::PlayoutControl* control = nullptr);

  ~OutputBus();

  // Disable copy and move
  OutputBus(const OutputBus&) = delete;
  OutputBus& operator=(const OutputBus&) = delete;

  // Attaches a sink to this bus.
  // If replace_existing is true and a sink is already attached, detaches old sink first.
  // If replace_existing is false and a sink is already attached, returns error.
  // Returns success/failure with message.
  // Thread-safe.
  OutputBusResult AttachSink(std::unique_ptr<IOutputSink> sink, bool replace_existing = false);

  // Detaches the currently attached sink.
  // If force is true, detaches immediately without waiting for graceful shutdown.
  // Returns success/failure with message.
  // Thread-safe.
  OutputBusResult DetachSink(bool force = false);

  // Returns true if a sink is currently attached.
  // Thread-safe.
  bool IsAttached() const;

  // Routes a video frame to the attached sink (if any).
  // Called from the render thread.
  // Thread-safe.
  void RouteVideo(const buffer::Frame& frame);

  // Routes an audio frame to the attached sink (if any).
  // Called from the render thread.
  // Thread-safe.
  void RouteAudio(const buffer::AudioFrame& audio_frame);

  // Returns the name of the attached sink, or empty string if none attached.
  // Thread-safe.
  std::string GetAttachedSinkName() const;

 private:
  mutable std::mutex mutex_;
  std::unique_ptr<IOutputSink> sink_;
  runtime::PlayoutControl* control_;  // Not owned

  // DEBUG INSTRUMENTATION - remove after diagnosis
  std::atomic<uint64_t> dbg_v_routed_{0};
  std::atomic<uint64_t> dbg_a_routed_{0};
  mutable std::chrono::steady_clock::time_point dbg_bus_heartbeat_time_;
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_OUTPUT_BUS_H_
