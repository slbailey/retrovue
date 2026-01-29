// Repository: Retrovue-playout
// Component: IOutputSink Interface
// Purpose: Interface for output sinks that consume frames from OutputBus.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_IOUTPUT_SINK_H_
#define RETROVUE_OUTPUT_IOUTPUT_SINK_H_

#include <functional>
#include <string>

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}  // namespace retrovue::buffer

namespace retrovue::output {

// SinkStatus represents the current state of an output sink.
enum class SinkStatus {
  kIdle,          // Sink created but not started
  kStarting,      // Sink is initializing
  kRunning,       // Sink is actively consuming frames
  kBackpressure,  // Sink is experiencing backpressure (queue full)
  kError,         // Sink encountered an error
  kStopping,      // Sink is shutting down
  kStopped        // Sink has stopped
};

// SinkStatusCallback is invoked when sink status changes.
// Callback receives the new status and an optional message.
using SinkStatusCallback = std::function<void(SinkStatus status, const std::string& message)>;

// IOutputSink is the interface for output sinks.
//
// An OutputSink converts frames into an external representation (e.g. MPEG-TS over TCP).
//
// OutputSink responsibilities:
// - Accept video and audio frames
// - Perform encoding, muxing, and transport
// - Manage its own internal threads and resources
// - Report backpressure or failure to the engine (via status callback)
//
// OutputSink explicitly does NOT:
// - Own engine state
// - Decide when it may attach or detach
// - Know about channels, schedules, or preview/live concepts
// - Interact directly with gRPC
class IOutputSink {
 public:
  virtual ~IOutputSink() = default;

  // Starts the sink (initializes encoder/muxer, starts worker thread).
  // Returns true if started successfully, false on failure.
  // May only be called when sink is in kIdle state.
  virtual bool Start() = 0;

  // Stops the sink gracefully (stops worker thread, closes muxer, encoder).
  // Safe to call multiple times.
  virtual void Stop() = 0;

  // Returns true if sink is currently running (status is kRunning or kBackpressure).
  virtual bool IsRunning() const = 0;

  // Returns the current status of the sink.
  virtual SinkStatus GetStatus() const = 0;

  // Consumes a video frame.
  // Called from the render thread; implementation should copy and queue for encoding.
  // Thread-safe: may be called concurrently with other operations.
  virtual void ConsumeVideo(const buffer::Frame& frame) = 0;

  // Consumes an audio frame.
  // Called from the render thread; implementation should copy and queue for encoding.
  // Thread-safe: may be called concurrently with other operations.
  virtual void ConsumeAudio(const buffer::AudioFrame& audio_frame) = 0;

  // Sets a callback to be invoked when sink status changes.
  // Callback may be invoked from any thread.
  virtual void SetStatusCallback(SinkStatusCallback callback) = 0;

  // Returns a human-readable name for this sink (for logging/diagnostics).
  virtual std::string GetName() const = 0;
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_IOUTPUT_SINK_H_
